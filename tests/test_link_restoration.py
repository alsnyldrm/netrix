import json

import pytest
import test_link_deletions
from netrix import models as m
from sqlalchemy import func, select

link_record = test_link_deletions.link_record
scan = test_link_deletions.scan


def restore(client, ids):
    return client.post("/api/v1/inventory/links/bulk", json={"ids": ids, "action": "restore"})


def deleted(client, **params):
    return client.get("/api/v1/inventory/links", params={"deleted": True, **params})


def test_deleted_list_search_filter_sort_and_restore_preserves_edits(admin_client, link_record, env):
    c = admin_client
    c.put(
        f"/api/v1/links/{link_record['id']}/labels",
        json={"remote_name": "User name", "remote_port": "User port"},
    )
    assert c.delete(f"/api/v1/links/{link_record['id']}").status_code == 204
    data = deleted(c, q="User name", sort_by="remote_name").json()
    assert data["total"] == 1
    assert data["items"][0]["remote_name"] == "User name"
    assert data["items"][0]["remote_port"] == "User port"
    assert (
        deleted(
            c, filters=json.dumps([{"field": "remote_name", "op": "not_contains", "value": "User"}])
        ).json()["total"]
        == 0
    )
    assert c.get("/api/v1/inventory/links").json()["total"] == 0
    assert restore(c, [link_record["id"]]).json() == {"updated": 1}
    assert restore(c, [link_record["id"]]).status_code == 200
    assert deleted(c).json()["total"] == 0
    with env() as db:
        row = db.get(m.Link, link_record["id"])
        assert row.is_current and not row.auto_add_excluded
        assert row.manual_remote_name == "User name" and row.manual_remote_port == "User port"
        assert row.last_seen_at == link_record["observed"]
        assert (
            db.scalar(select(func.count()).select_from(m.Audit).where(m.Audit.action == "restore_link")) == 1
        )
        assert db.scalar(select(m.Event).where(m.Event.kind == "link_restored"))
        scan(db, link_record)
    assert c.get("/api/v1/inventory/links").json()["items"][0]["remote_name"] == "User name"


def test_restore_unblocks_protocol_duplicates_but_not_other_ports(admin_client, link_record, env):
    with env() as db:
        duplicate = m.Link(
            device_id=link_record["source"],
            interface_name="A2",
            remote_name="MAC label",
            remote_port="49",
            source="cdp",
            evidence={"cdp": {"device_id": "38:21:c7:3c:b2:40", "port_id": "49"}},
        )
        other = m.Link(
            device_id=link_record["source"],
            interface_name="A3",
            remote_name="Other",
            remote_port="49",
            source="lldp",
            auto_add_excluded=True,
            is_current=False,
        )
        db.add_all([duplicate, other])
        db.commit()
        duplicate_id, other_id = duplicate.id, other.id
    admin_client.delete(f"/api/v1/links/{link_record['id']}")
    assert deleted(admin_client).json()["total"] == 3
    # A worker holding pre-restore ORM objects must reload the lifted exclusion.
    with env() as worker:
        stale = worker.get(m.Link, link_record["id"])
        assert stale.auto_add_excluded
        assert restore(admin_client, [link_record["id"]]).status_code == 200
        scan(worker, link_record)
        worker.refresh(stale)
        assert not stale.auto_add_excluded
    with env() as db:
        assert not db.get(m.Link, duplicate_id).auto_add_excluded
        assert db.get(m.Link, other_id).auto_add_excluded
        assert db.scalar(select(func.count()).select_from(m.Link).where(m.Link.is_current.is_(True))) == 1
    assert deleted(admin_client).json()["total"] == 1


def test_portless_manual_tombstone_is_lifted_with_restored_observation(admin_client, link_record, env):
    with env() as db:
        manual = m.Link(
            device_id=link_record["source"],
            remote_device_id=link_record["old"],
            interface_name="",
            remote_name="Old",
            remote_port="",
            source="manual",
        )
        db.add(manual)
        db.commit()
        manual_id = manual.id
    admin_client.delete(f"/api/v1/links/{manual_id}")
    assert deleted(admin_client).json()["total"] == 2
    assert restore(admin_client, [link_record["id"]]).status_code == 200
    with env() as db:
        assert not db.get(m.Link, manual_id).auto_add_excluded
        assert not db.get(m.Link, manual_id).is_current
        scan(db, link_record)
    assert admin_client.get("/api/v1/inventory/links").json()["total"] == 1


def test_bulk_restore_and_invalid_selection_are_atomic(admin_client, link_record, env):
    with env() as db:
        second = m.Link(
            device_id=link_record["source"],
            interface_name="A3",
            remote_name="Second",
            remote_port="1",
            source="lldp",
            is_current=False,
            auto_add_excluded=True,
        )
        db.add(second)
        db.commit()
        second_id = second.id
    admin_client.delete(f"/api/v1/links/{link_record['id']}")
    assert restore(admin_client, [link_record["id"], "missing"]).status_code == 404
    assert deleted(admin_client).json()["total"] == 2
    assert restore(admin_client, [link_record["id"], second_id]).json() == {"updated": 2}
    assert deleted(admin_client).json()["total"] == 0
    assert admin_client.get("/api/v1/inventory/links").json()["total"] == 2


def test_archived_source_remains_visible_and_must_be_restored_first(admin_client, link_record, env):
    admin_client.delete(f"/api/v1/links/{link_record['id']}")
    with env() as db:
        db.get(m.Device, link_record["source"]).archived = True
        db.commit()
    assert deleted(admin_client).json()["total"] == 1
    assert restore(admin_client, [link_record["id"]]).status_code == 409
    assert deleted(admin_client).json()["total"] == 1


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_restore_admin_only_but_deleted_list_is_readable(admin_client, link_record, env, role):
    admin_client.delete(f"/api/v1/links/{link_record['id']}")
    with env() as db:
        db.scalar(select(m.User)).role = role
        db.commit()
    assert deleted(admin_client).json()["total"] == 1
    assert restore(admin_client, [link_record["id"]]).status_code == 403


def test_stale_observations_are_not_in_recycle_list_and_cannot_be_restored(admin_client, link_record, env):
    with env() as db:
        db.get(m.Link, link_record["id"]).is_current = False
        db.commit()
    assert deleted(admin_client).json()["total"] == 0
    assert restore(admin_client, [link_record["id"]]).status_code == 409
    assert admin_client.get("/api/v1/inventory/devices", params={"deleted": True}).status_code == 422


def test_deleted_query_pagination_and_boolean_filters(admin_client, link_record, env):
    with env() as db:
        db.add_all(
            [
                m.Link(
                    device_id=link_record["source"],
                    interface_name=f"P{i:02}",
                    remote_name=f"Peer {i:02}",
                    remote_port="49",
                    source="lldp",
                    is_current=False,
                    auto_add_excluded=True,
                )
                for i in range(30)
            ]
        )
        db.commit()
    rules = [
        {"field": "remote_name", "op": "contains", "value": "Peer"},
        {"field": "source", "op": "eq", "value": "cdp", "join": "or"},
        {"field": "remote_name", "op": "not_contains", "value": "29", "join": "and"},
    ]
    pages = [
        deleted(admin_client, filters=json.dumps(rules), sort_by="remote_name", offset=offset).json()
        for offset in (0, 25)
    ]
    assert pages[0]["total"] == pages[1]["total"] == 29
    rows = pages[0]["items"] + pages[1]["items"]
    assert len({r["id"] for r in rows}) == 29
    assert [r["remote_name"] for r in rows] == [f"Peer {i:02}" for i in range(29)]
