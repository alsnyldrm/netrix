"""VLAN deletion removes its IPs without altering inventory or shared sources."""

import pytest
from netrix import models as m
from netrix import worker
from sqlalchemy import select
from test_ipam_workspace import integration, prefix


def confirmation(client, ids):
    response = client.post("/api/v1/ipam/vlans/delete-preview", json={"ids": ids})
    assert response.status_code == 200, response.text
    return {"ids": ids, "confirmation": response.json()["confirmation"]}, response.json()


def test_atomic_delete_keeps_inventory_and_integrations(admin_client, inventory, env):
    p, q = prefix(admin_client, inventory), prefix(admin_client, inventory, "198.51.100.0/24")
    source = integration(admin_client, p)
    with env() as db:
        row = m.IPAddress(vlan_id=p["id"], vrf_id=p["vrf_id"], address="192.0.2.1")
        device = m.Device(name="keep", management_ip="192.0.2.1", vrf_id=p["vrf_id"])
        db.add_all([row, device])
        db.flush()
        db.add(
            m.IPObservation(
                address_id=row.id, source="icmp", source_key=p["id"], data={"reachability": "reachable"}
            )
        )
        db.commit()
        address_id, device_id = row.id, device.id
    payload, preview = confirmation(admin_client, [p["id"]])
    assert preview["address_count"] == 1
    response = admin_client.post("/api/v1/ipam/vlans/bulk-delete", json=payload)
    assert response.status_code == 200 and response.json() == {"affected": 1, "deleted_addresses": 1}
    with env() as db:
        assert db.get(m.VLAN, p["id"]) is None and db.get(m.VLAN, q["id"])
        assert db.get(m.IPAddress, address_id) is None
        assert not list(db.scalars(select(m.IPObservation)))
        assert db.get(m.Device, device_id) and db.get(m.Scope, inventory["scope"]["id"])
        assert db.get(m.Integration, source["id"]).enabled


@pytest.mark.parametrize("status", ["queued", "running"])
def test_deletion_cancels_vlan_jobs_only(admin_client, inventory, env, status):
    p = prefix(admin_client, inventory)
    source = integration(admin_client, p)
    with env() as db:
        job = db.scalar(select(m.Job).where(m.Job.kind == "ipam_discover", m.Job.target_id == p["id"]))
        job.status = status
        shared = m.Job(
            kind="integration",
            target_id=source["id"],
            status="running",
            active_key="integration:" + source["id"],
        )
        db.add(shared)
        db.commit()
        job_id, shared_id = job.id, shared.id
    payload, _ = confirmation(admin_client, [p["id"]])
    assert admin_client.post("/api/v1/ipam/vlans/bulk-delete", json=payload).status_code == 200
    with env() as db:
        job = db.get(m.Job, job_id)
        assert job.cancel_requested and job.status == ("cancelled" if status == "queued" else "running")
        assert not db.get(m.Job, shared_id).cancel_requested


def test_stale_confirmation_and_missing_selection_are_atomic(admin_client, inventory, env):
    p, q = prefix(admin_client, inventory), prefix(admin_client, inventory, "198.51.100.0/24")
    payload, _ = confirmation(admin_client, [p["id"], q["id"]])
    assert (
        admin_client.post(
            "/api/v1/ipam/vlans/bulk-delete", json={**payload, "ids": [p["id"], "missing"]}
        ).status_code
        == 404
    )
    with env() as db:
        db.get(m.VLAN, p["id"]).name = "Changed"
        db.commit()
    assert admin_client.post("/api/v1/ipam/vlans/bulk-delete", json=payload).status_code == 409
    with env() as db:
        assert db.get(m.VLAN, p["id"]) and db.get(m.VLAN, q["id"])


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_only_admin_can_delete(admin_client, inventory, env, role):
    p = prefix(admin_client, inventory)
    payload, _ = confirmation(admin_client, [p["id"]])
    with env() as db:
        db.scalar(select(m.User)).role = role
        db.commit()
    assert admin_client.post("/api/v1/ipam/vlans/delete-preview", json={"ids": [p["id"]]}).status_code == 403
    assert admin_client.post("/api/v1/ipam/vlans/bulk-delete", json=payload).status_code == 403


def test_stale_collector_cannot_recreate_deleted_vlan(admin_client, inventory, env):
    from netrix.ipam.service import observe

    p = prefix(admin_client, inventory)
    with env() as db:
        old = db.get(m.VLAN, p["id"])
        db.expunge(old)
    assert admin_client.delete("/api/v1/vlans/" + p["id"]).status_code == 204
    with env() as db:
        assert observe(db, old, "192.0.2.1", "icmp", "vlan", {}) is None


@pytest.mark.asyncio
async def test_delete_during_ping_drops_inflight_results(admin_client, inventory, env, monkeypatch):
    from netrix.ipam import adapters

    p = prefix(admin_client, inventory)
    task = admin_client.post(f"/api/v1/ipam/vlans/{p['id']}/discover").json()
    deleted = False

    async def ping(address):
        nonlocal deleted
        if not deleted:
            deleted = True
            assert admin_client.delete("/api/v1/vlans/" + p["id"]).status_code == 204
        return True

    monkeypatch.setattr(adapters, "ping", ping)
    await worker.execute(task["id"])
    with env() as db:
        assert not list(db.scalars(select(m.IPAddress)))
        assert db.get(m.Job, task["id"]).status == "cancelled"
