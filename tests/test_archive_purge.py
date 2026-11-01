import pytest
from netrix import models as m
from netrix.identity.security import encrypt
from sqlalchemy import select
from test_inventory_management import records as inventory_records


@pytest.fixture
def archive_records(env, inventory):
    return inventory_records.__wrapped__(env, inventory)


def test_purge_removes_owned_data_preserves_shared_data_and_audit(
    admin_client, archive_records, env, inventory
):
    ids = archive_records["devices"]
    with env() as db:
        for id in ids:
            db.get(m.Device, id).archived = True
        job = m.Job(kind="backup", target_id=ids[0], status="queued", active_key="backup:" + ids[0])
        db.add(job)
        db.flush()
        snap = m.Snapshot(
            device_id=ids[0],
            job_id=job.id,
            encrypted_content=encrypt("fixture-secret"),
            fingerprint="fixture",
            size_bytes=14,
        )
        db.add(snap)
        db.flush()
        db.get(m.Device, ids[0]).base_snapshot_id = snap.id
        vlan = m.VLAN(name="fixture", vid=80, domain="fixture")
        cabinet = m.Cabinet(name="retained cabinet")
        rule = m.AlertRule(name="retained rule", metric="config_change")
        db.add_all([vlan, cabinet, rule])
        db.flush()
        placement = m.RackPlacement(cabinet_id=cabinet.id, device_id=ids[0], start_unit=1, units=1)
        alert = m.Alert(rule_id=rule.id, device_id=ids[0], severity="warning", message="fixture")
        ip = m.IPAddress(
            address="192.0.2.1",
            vrf_id=inventory["vrf"]["id"],
            vlan_id=vlan.id,
            device_id=ids[0],
            interface_id=archive_records["ports"][0],
        )
        event = m.Event(device_id=ids[0], kind="fixture", message="history")
        observation = m.Observation(device_id=ids[0], job_id=job.id, address="192.0.2.1", evidence={})
        link = m.Link(
            device_id=ids[1],
            remote_device_id=ids[0],
            manual_remote_device_id=ids[0],
            remote_name="peer",
            interface_name="1",
            remote_port="2",
        )
        db.add_all([ip, event, observation, link, placement, alert])
        db.commit()
        job_id, snap_id, ip_id, event_id = job.id, snap.id, ip.id, event.id
        cabinet_id, rule_id = cabinet.id, rule.id
    response = admin_client.post("/api/v1/inventory/devices/bulk", json={"ids": ids, "action": "purge"})
    assert response.status_code == 200, response.text
    assert response.json() == {"updated": 2}
    with env() as db:
        assert all(db.get(m.Device, id) is None for id in ids)
        assert db.get(m.Snapshot, snap_id) is None
        assert not list(db.scalars(select(m.Interface)))
        assert not list(db.scalars(select(m.Link)))
        assert not list(db.scalars(select(m.Observation)))
        assert not list(db.scalars(select(m.RackPlacement))) and not list(db.scalars(select(m.Alert)))
        assert db.get(m.Cabinet, cabinet_id) and db.get(m.AlertRule, rule_id)
        assert (
            db.get(m.IPAddress, ip_id).device_id is None and db.get(m.IPAddress, ip_id).interface_id is None
        )
        assert db.get(m.Credential, inventory["credential"]["id"])
        assert db.get(m.Event, event_id).details["deleted_device"]["name"] == "Device 0"
        assert db.get(m.Job, job_id).status == "cancelled" and db.get(m.Job, job_id).active_key is None
        assert len(list(db.scalars(select(m.Audit).where(m.Audit.action == "bulk_purge")))) == 2
    assert "fixture-secret" not in response.text


@pytest.mark.parametrize("invalid", ["active", "missing", "running", "changes"])
def test_purge_rejects_invalid_batch_atomically(admin_client, archive_records, env, invalid):
    ids = archive_records["devices"]
    with env() as db:
        for id in ids:
            db.get(m.Device, id).archived = True
        if invalid == "active":
            db.get(m.Device, ids[1]).archived = False
        if invalid == "running":
            db.add(m.Job(kind="identify", target_id=ids[1], status="running"))
        db.commit()
    payload = {"ids": ids + (["missing"] if invalid == "missing" else []), "action": "purge"}
    if invalid == "changes":
        payload["changes"] = {"model": "no"}
    response = admin_client.post("/api/v1/inventory/devices/bulk", json=payload)
    assert response.status_code == {"active": 409, "missing": 404, "running": 409, "changes": 422}[invalid]
    with env() as db:
        assert all(db.get(m.Device, id) for id in ids)
        assert all(db.get(m.Interface, id) for id in archive_records["ports"])
        assert not list(db.scalars(select(m.Audit).where(m.Audit.action == "bulk_purge")))


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_only_admin_can_purge(admin_client, archive_records, env, role):
    with env() as db:
        db.scalar(select(m.User)).role = role
        db.get(m.Device, archive_records["devices"][0]).archived = True
        db.commit()
    assert (
        admin_client.post(
            "/api/v1/inventory/devices/bulk", json={"ids": archive_records["devices"], "action": "purge"}
        ).status_code
        == 403
    )


def test_purge_rejected_for_other_resources(admin_client, archive_records):
    for resource in ("interfaces", "links"):
        assert (
            admin_client.post(
                f"/api/v1/inventory/{resource}/bulk",
                json={"ids": archive_records["ports"], "action": "purge"},
            ).status_code
            == 422
        )
