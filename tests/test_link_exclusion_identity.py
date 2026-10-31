"""Replay UUID and port-format changes seen in saved CDP/LLDP observations."""

import pytest
import test_link_edits
from netrix import models as m
from netrix.discovery.links import sync_links
from sqlalchemy import select

link_record = test_link_edits.link_record
IDENTITY = "37383638-3330-5A43-3339-323354544D57"


def neighbor(source="lldp", port="80:30:e0:37:32:10", identity=IDENTITY, local="A2"):
    return dict(
        interface_name=local,
        remote_name=identity,
        remote_port=port,
        source=source,
        evidence={source: {"chassis_id" if source == "lldp" else "device_id": identity, "port_id": port}},
    )


def seed(db, record, data, **extra):
    row = m.Link(device_id=record["source"], **data, **extra)
    db.add(row)
    db.commit()
    return row.id


@pytest.mark.parametrize("source", ["lldp", "cdp"])
def test_uuid_deleted_neighbor_stays_deleted_when_port_and_protocol_change(
    admin_client, link_record, env, source
):
    with env() as db:
        row = db.get(m.Link, link_record["id"])
        for key, value in neighbor("cdp", "fo = 1").items():
            setattr(row, key, value)
        db.commit()
    assert admin_client.delete(f"/api/v1/links/{link_record['id']}").status_code == 204
    with env() as db:
        device = db.get(m.Device, link_record["source"])
        for port in ("80 30 e0 37 32 10", "fo = 1 , Port 1", "80:30:e0:37:32:10"):
            sync_links(db, device, {"neighbors": [neighbor(source, port, IDENTITY.lower())]})
            db.commit()
        assert not list(db.scalars(select(m.Link).where(m.Link.is_current.is_(True))))
        # The same UUID on a different local port and a different UUID here are not excluded.
        sync_links(db, device, {"neighbors": [neighbor(local="A3"), neighbor(identity=IDENTITY[:-1] + "8")]})
        db.commit()
        assert len(list(db.scalars(select(m.Link).where(m.Link.is_current.is_(True))))) == 2
    assert (
        admin_client.post(
            "/api/v1/inventory/links/bulk", json={"ids": [link_record["id"]], "action": "restore"}
        ).status_code
        == 200
    )
    with env() as db:
        sync_links(db, db.get(m.Device, link_record["source"]), {"neighbors": [neighbor()]})
        db.commit()
        assert not any(row.auto_add_excluded for row in db.scalars(select(m.Link)))


def test_mac_port_spelling_cannot_bypass_deletion(admin_client, link_record, env):
    with env() as db:
        row = db.get(m.Link, link_record["id"])
        row.remote_port = "80 30 e0 37 32 10"
        row.evidence = {}
        db.commit()
    admin_client.delete(f"/api/v1/links/{link_record['id']}")
    with env() as db:
        data = {**neighbor(), "remote_name": "Old", "evidence": {}}
        sync_links(db, db.get(m.Device, link_record["source"]), {"neighbors": [data]})
        db.commit()
        assert not list(db.scalars(select(m.Link).where(m.Link.is_current.is_(True))))


def test_kept_manual_correction_survives_excluded_duplicate_then_can_be_deleted(
    admin_client, link_record, env
):
    with env() as db:
        deleted_id = seed(db, link_record, neighbor("cdp", "fo = 1"))
        kept_id = seed(
            db,
            link_record,
            neighbor("lldp", "80 30 e0 37 32 10"),
            manual_remote_name="Kept server",
            manual_remote_port="vmnic4",
        )
    admin_client.delete(f"/api/v1/links/{deleted_id}")
    with env() as db:
        for _ in range(2):
            sync_links(
                db,
                db.get(m.Device, link_record["source"]),
                {"neighbors": [neighbor()], "neighbor_protocols_complete": ["lldp", "cdp"]},
            )
            db.commit()
        kept = db.get(m.Link, kept_id)
        assert kept.is_current and not kept.auto_add_excluded
        assert kept.manual_remote_name == "Kept server" and kept.manual_remote_port == "vmnic4"
        assert len(list(db.scalars(select(m.Link).where(m.Link.is_current.is_(True))))) == 1
    assert admin_client.delete(f"/api/v1/links/{kept_id}").status_code == 204
    with env() as db:
        sync_links(db, db.get(m.Device, link_record["source"]), {"neighbors": [neighbor()]})
        db.commit()
        assert not list(db.scalars(select(m.Link).where(m.Link.is_current.is_(True))))


def test_repair_existing_copies_is_idempotent_and_restore_lifts_related_exclusions(
    admin_client, link_record, env
):
    from netrix.discovery.link_deletions import repair_stored_exclusions

    with env() as db:
        deleted_id = seed(
            db, link_record, neighbor("cdp", "fo = 1"), auto_add_excluded=True, is_current=False
        )
        copy_id = seed(db, link_record, neighbor())
        history_id = seed(db, link_record, neighbor("cdp", "fo = 1 , Port 1"), is_current=False)
        kept_id = seed(
            db,
            link_record,
            neighbor("lldp", "80 30 e0 37 32 10"),
            manual_remote_name="Kept",
            manual_remote_port="vmnic4",
        )
        unrelated_id = seed(db, link_record, neighbor(identity="37383638-3330-5A43-3339-323354544E30"))
        result = repair_stored_exclusions(db)
        assert result == {"excluded": 2, "hidden_current": 1}
        db.rollback()  # The maintenance command's default dry run must not persist changes.
        assert not db.get(m.Link, copy_id).auto_add_excluded
        assert repair_stored_exclusions(db) == result
        db.commit()
        assert repair_stored_exclusions(db) == {"excluded": 0, "hidden_current": 0}
        assert db.get(m.Link, copy_id).auto_add_excluded
        assert db.get(m.Link, history_id).auto_add_excluded
        for id in (kept_id, unrelated_id):
            assert db.get(m.Link, id).is_current and not db.get(m.Link, id).auto_add_excluded
    assert (
        admin_client.post(
            "/api/v1/inventory/links/bulk", json={"ids": [deleted_id], "action": "restore"}
        ).status_code
        == 200
    )
    with env() as db:
        for id in (deleted_id, copy_id, history_id):
            assert not db.get(m.Link, id).auto_add_excluded
        assert not db.get(m.Link, history_id).is_current


@pytest.mark.parametrize("identity", ["vmnic4", "37383638-3330-5A43-333...", "HPE Ethernet adapter"])
def test_non_unique_identity_alone_never_suppresses_another_neighbor(identity, link_record, env):
    with env() as db:
        seed(
            db,
            link_record,
            neighbor("cdp", "deleted port", identity),
            auto_add_excluded=True,
            is_current=False,
        )
        sync_links(
            db,
            db.get(m.Device, link_record["source"]),
            {"neighbors": [neighbor("lldp", "different port", identity)]},
        )
        db.commit()
        assert any(
            row.remote_port == "different port" and row.is_current for row in db.scalars(select(m.Link))
        )
