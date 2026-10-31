import pytest
from netrix import models as m
from sqlalchemy import select
from test_ipam_workspace import integration, prefix


def confirmation(c, ids):
    r = c.post("/api/v1/ipam/prefixes/delete-preview", json={"ids": ids})
    assert r.status_code == 200, r.text
    return {"ids": ids, "confirmation": r.json()["confirmation"]}, r.json()


def test_atomic_delete_cleans_ipam_keeps_devices_and_other_scopes(admin_client, inventory, env):
    c = admin_client
    p, q = prefix(c, inventory), prefix(c, inventory, "198.51.100.0/24")
    config = integration(c, p, prefix_ids=[p["id"], q["id"]])
    only = integration(c, p, name="DHCP", kind="windows_dhcp")
    with env() as db:
        ip = m.IPAddress(prefix_id=p["id"], vrf_id=p["vrf_id"], address="192.0.2.1")
        device = m.Device(name="keep", management_ip=ip.address, vrf_id=p["vrf_id"])
        db.add_all([ip, device])
        db.flush()
        db.add(
            m.IPObservation(
                address_id=ip.id, source="icmp", source_key=p["id"], data={"reachability": "reachable"}
            )
        )
        db.commit()
        address_id, device_id = ip.id, device.id
    payload, preview = confirmation(c, [p["id"]])
    assert preview["address_count"] == 1
    assert sorted(x["will_disable"] for x in preview["integrations"]) == [False, True]
    r = c.post("/api/v1/ipam/prefixes/bulk-delete", json=payload)
    assert r.status_code == 200, r.text
    assert r.json() == {"affected": 1, "deleted_addresses": 1}
    with env() as db:
        assert db.get(m.Prefix, p["id"]) is None
        assert db.get(m.Prefix, q["id"])
        assert db.get(m.IPAddress, address_id) is None
        assert not list(db.scalars(select(m.IPObservation)))
        assert db.get(m.Device, device_id)
        assert db.get(m.Integration, config["id"]).prefix_ids == [q["id"]]
        assert db.get(m.Integration, config["id"]).enabled
        assert db.get(m.Integration, only["id"]).prefix_ids == []
        assert not db.get(m.Integration, only["id"]).enabled


@pytest.mark.parametrize("active_target", ["prefix", "address", "integration"])
@pytest.mark.parametrize("status", ["queued", "running"])
def test_active_jobs_are_cancelled_with_selection(admin_client, inventory, env, active_target, status):
    c = admin_client
    p, q = prefix(c, inventory), prefix(c, inventory, "198.51.100.0/24")
    config = integration(c, p)
    with env() as db:
        ip = m.IPAddress(prefix_id=p["id"], vrf_id=p["vrf_id"], address="192.0.2.1")
        db.add(ip)
        db.flush()
        target = {"prefix": q["id"], "address": ip.id, "integration": config["id"]}[active_target]
        job = m.Job(kind="fixture", target_id=target, active_key="fixture:" + target, status=status)
        unrelated = m.Job(kind="fixture", target_id="other", active_key="fixture:other", status="running")
        db.add_all([job, unrelated])
        db.commit()
        job_id, other_id = job.id, unrelated.id
    payload, _ = confirmation(c, [p["id"], q["id"]])
    assert c.post("/api/v1/ipam/prefixes/bulk-delete", json=payload).status_code == 200
    with env() as db:
        assert not db.get(m.Prefix, p["id"]) and not db.get(m.Prefix, q["id"])
        assert db.get(m.Integration, config["id"]).prefix_ids == []
        job = db.get(m.Job, job_id)
        assert job.cancel_requested
        assert job.status == ("cancelled" if status == "queued" else "running")
        assert bool(job.active_key) == (status == "running")
        assert not db.get(m.Job, other_id).cancel_requested


def test_changed_preview_and_missing_selection_do_not_partially_delete(admin_client, inventory, env):
    c = admin_client
    p, q = prefix(c, inventory), prefix(c, inventory, "198.51.100.0/24")
    payload, _ = confirmation(c, [p["id"], q["id"]])
    with env() as db:
        db.add(m.IPAddress(prefix_id=p["id"], vrf_id=p["vrf_id"], address="192.0.2.1"))
        db.commit()
    assert (
        c.post("/api/v1/ipam/prefixes/bulk-delete", json={**payload, "ids": [p["id"], "missing"]}).status_code
        == 404
    )
    payload["ids"].append(p["id"])
    r = c.post("/api/v1/ipam/prefixes/bulk-delete", json=payload)
    assert r.status_code == 200 and r.json()["affected"] == 2


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_only_admin_can_preview_or_delete(admin_client, inventory, env, role):
    p = prefix(admin_client, inventory)
    payload, _ = confirmation(admin_client, [p["id"]])
    with env() as db:
        db.scalar(select(m.User)).role = role
        db.commit()
    assert (
        admin_client.post("/api/v1/ipam/prefixes/delete-preview", json={"ids": [p["id"]]}).status_code == 403
    )
    assert admin_client.post("/api/v1/ipam/prefixes/bulk-delete", json=payload).status_code == 403
    assert admin_client.delete("/api/v1/prefixes/" + p["id"]).status_code == 403


def test_changed_integration_scope_requires_new_preview(admin_client, inventory, env):
    p, q = prefix(admin_client, inventory), prefix(admin_client, inventory, "198.51.100.0/24")
    config = integration(admin_client, p)
    payload, _ = confirmation(admin_client, [p["id"]])
    with env() as db:
        db.get(m.Integration, config["id"]).prefix_ids = [p["id"], q["id"]]
        db.commit()
    assert admin_client.post("/api/v1/ipam/prefixes/bulk-delete", json=payload).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_read", [False, True])
async def test_delete_during_integration_read_cancels_worker(
    admin_client, inventory, env, monkeypatch, fail_read
):
    from netrix import worker
    from netrix.ipam import adapters

    p = prefix(admin_client, inventory)
    config = integration(admin_client, p)
    task = admin_client.post(f"/api/v1/integrations/{config['id']}/sync").json()

    def read(*args):
        payload, _ = confirmation(admin_client, [p["id"]])
        r = admin_client.post("/api/v1/ipam/prefixes/bulk-delete", json=payload)
        assert r.status_code == 200, r.text
        if fail_read:
            raise OSError("network failed after deletion")
        return [{"address": "192.0.2.11", "hostname": "stale-host"}]

    monkeypatch.setattr(adapters, "vcenter_records", read)
    await worker.execute(task["id"])
    with env() as db:
        job = db.get(m.Job, task["id"])
        assert job.status == "cancelled" and job.active_key is None
        assert not list(db.scalars(select(m.IPAddress)))


def test_stale_collector_cannot_recreate_deleted_prefix_ips(admin_client, inventory, env):
    from netrix.ipam.service import observe

    p = prefix(admin_client, inventory)
    with env() as stale:
        old = stale.get(m.Prefix, p["id"])
        stale.expunge(old)
    payload, _ = confirmation(admin_client, [p["id"]])
    assert admin_client.post("/api/v1/ipam/prefixes/bulk-delete", json=payload).status_code == 200
    with env() as db:
        assert observe(db, old, "192.0.2.9", "inventory", "device", {}) is None
        db.commit()


@pytest.mark.asyncio
async def test_delete_during_ping_drops_inflight_results(admin_client, inventory, env, monkeypatch):
    from netrix import worker
    from netrix.ipam import adapters

    p = prefix(admin_client, inventory)
    r = admin_client.put(
        f"/api/v1/ipam/prefixes/{p['id']}/settings", json={"scope_id": inventory["scope"]["id"]}
    )
    assert r.status_code == 200, r.text
    with env() as db:
        db.add(m.IPAddress(prefix_id=p["id"], vrf_id=p["vrf_id"], address="192.0.2.1"))
        db.commit()
    task = admin_client.post(f"/api/v1/ipam/prefixes/{p['id']}/ping").json()
    deleted = False

    async def ping(address):
        nonlocal deleted
        if not deleted:
            deleted = True
            payload, _ = confirmation(admin_client, [p["id"]])
            assert admin_client.post("/api/v1/ipam/prefixes/bulk-delete", json=payload).status_code == 200
        return True

    monkeypatch.setattr(adapters, "ping", ping)
    await worker.execute(task["id"])
    assert deleted
    with env() as db:
        assert db.get(m.Job, task["id"]).status == "cancelled"
        assert not list(db.scalars(select(m.IPObservation)))
