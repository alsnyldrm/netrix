import pytest
import test_link_edits
from netrix import models as m
from netrix.discovery.device_connections import device_connections
from netrix.discovery.links import sync_links
from sqlalchemy import func, select

link_record = test_link_edits.link_record


def delete(client, record):
    return client.delete(f"/api/v1/links/{record['id']}")


def scan(db, record, *, name="Old", port="NIC", local="A2", chassis="38:21:c7:3c:b2:40", source="lldp+cdp"):
    sync_links(
        db,
        db.get(m.Device, record["source"]),
        {
            "neighbors": [
                {
                    "interface_name": local,
                    "remote_name": name,
                    "remote_port": port,
                    "source": source,
                    "evidence": {"lldp": {"chassis_id": chassis, "system_name": name, "port_id": port}},
                }
            ],
            "neighbor_protocols_complete": [],  # Partial walks must respect user deletion too.
        },
    )
    db.commit()


def test_delete_hides_every_view_and_blocks_renamed_protocol_observations(admin_client, link_record, env):
    c = admin_client
    assert (
        c.put(
            f"/api/v1/links/{link_record['id']}/labels",
            json={"remote_name": "User label", "remote_port": "User port"},
        ).status_code
        == 200
    )
    assert delete(c, link_record).status_code == 204
    assert delete(c, link_record).status_code == 204
    for source in ("lldp", "cdp", "lldp+cdp"):
        with env() as db:
            scan(db, link_record, name="Changed advertised name", port="49", source=source)
        assert c.get("/api/v1/links").json()["total"] == 0
        assert c.get("/api/v1/inventory/links").json()["total"] == 0
    with env() as db:
        row = db.get(m.Link, link_record["id"])
        assert row.auto_add_excluded and not row.is_current
        assert row.remote_name == "Old" and row.manual_remote_name == "User label"
        assert row.last_seen_at == link_record["observed"]
        assert db.scalar(select(func.count()).select_from(m.Link)) == 1
        assert (
            db.scalar(select(func.count()).select_from(m.Audit).where(m.Audit.action == "delete_link")) == 1
        )
        assert db.scalar(select(m.Event).where(m.Event.kind == "link_deleted"))
        assert device_connections(db, db.get(m.Device, link_record["source"]))["items"] == []
    directory = c.get("/api/v1/inventory/topology-devices").json()
    assert next(r for r in directory["items"] if r["id"] == link_record["source"])["neighbor_count"] == 0
    assert (
        c.put(
            f"/api/v1/links/{link_record['id']}/labels", json={"remote_name": "X", "remote_port": "1"}
        ).status_code
        == 409
    )


def test_deleted_exact_values_are_blocked_without_evidence_across_protocols(admin_client, link_record, env):
    with env() as db:
        db.get(m.Link, link_record["id"]).evidence = {}
        db.commit()
    delete(admin_client, link_record)
    with env() as db:
        sync_links(
            db,
            db.get(m.Device, link_record["source"]),
            {
                "neighbors": [
                    {"interface_name": "A2", "remote_name": "Old", "remote_port": "NIC", "source": "cdp"}
                ]
            },
        )
        db.commit()
        assert db.scalar(select(func.count()).select_from(m.Link)) == 1
        assert not db.get(m.Link, link_record["id"]).is_current


def test_deletion_suppresses_protocol_duplicates_but_not_other_devices_ports_or_neighbors(
    admin_client, link_record, env
):
    with env() as db:
        row = db.get(m.Link, link_record["id"])
        duplicate = m.Link(
            device_id=row.device_id,
            interface_name="A2",
            remote_name="MAC label",
            remote_port="49",
            source="cdp",
            evidence={"cdp": {"device_id": "38:21:c7:3c:b2:40", "port_id": "49"}},
        )
        db.add(duplicate)
        db.commit()
        duplicate_id = duplicate.id
    delete(admin_client, link_record)
    with env() as db:
        assert db.get(m.Link, duplicate_id).auto_add_excluded
        scan(db, link_record, name="New neighbor", chassis="38:21:c7:00:00:99")
        scan(db, link_record, local="A3")
        scan(db, {**link_record, "source": link_record["new"]})
        current = db.scalars(select(m.Link).where(m.Link.is_current.is_(True))).all()
        assert len(current) == 3
        assert not any(r.auto_add_excluded for r in current)


def test_worker_loaded_before_delete_cannot_reactivate_record(admin_client, link_record, env):
    with env() as worker:
        stale = worker.get(m.Link, link_record["id"])
        assert not stale.auto_add_excluded
        assert delete(admin_client, link_record).status_code == 204
        scan(worker, link_record)
        worker.refresh(stale)
        assert stale.auto_add_excluded and not stale.is_current


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_only_admin_can_delete(admin_client, link_record, env, role):
    with env() as db:
        db.scalar(select(m.User)).role = role
        db.commit()
    assert delete(admin_client, link_record).status_code == 403
    assert admin_client.get("/api/v1/inventory/links").json()["total"] == 1


def test_missing_archived_and_stale_guards(admin_client, link_record, env):
    assert delete(admin_client, {"id": "missing"}).status_code == 404
    with env() as db:
        db.get(m.Link, link_record["id"]).is_current = False
        db.commit()
    assert delete(admin_client, link_record).status_code == 409
    with env() as db:
        db.get(m.Link, link_record["id"]).is_current = True
        db.get(m.Device, link_record["source"]).archived = True
        db.commit()
    assert delete(admin_client, link_record).status_code == 409


def test_deleted_portless_manual_connection_cannot_return_from_discovery(admin_client, link_record, env):
    with env() as db:
        row = db.get(m.Link, link_record["id"])
        row.source, row.interface_name, row.remote_port = "manual", "", ""
        row.evidence = {}
        db.commit()
    assert delete(admin_client, link_record).status_code == 204
    with env() as db:
        scan(db, link_record, local="A8", port="49", source="lldp")
        assert db.scalar(select(func.count()).select_from(m.Link)) == 1
        sync_links(
            db,
            db.get(m.Device, link_record["source"]),
            {
                "neighbors": [
                    {
                        "interface_name": "A8",
                        "remote_name": "Renamed",
                        "remote_port": "49",
                        "source": "lldp",
                        "evidence": {"lldp": {"management_address": "192.0.2.2"}},
                    }
                ]
            },
        )
        db.commit()
        assert db.scalar(select(func.count()).select_from(m.Link)) == 1
