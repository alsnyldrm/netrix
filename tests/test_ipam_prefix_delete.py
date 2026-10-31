import pytest
from netrix import models as m
from netrix.core import now
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
        db.add(m.IPTraffic(address_id=ip.id, source_key="fixture", sampled_at=now(), interval_seconds=5))
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
        assert not list(db.scalars(select(m.IPTraffic)))
        assert db.get(m.Device, device_id)
        assert db.get(m.Integration, config["id"]).prefix_ids == [q["id"]]
        assert db.get(m.Integration, config["id"]).enabled
        assert db.get(m.Integration, only["id"]).prefix_ids == []
        assert not db.get(m.Integration, only["id"]).enabled


@pytest.mark.parametrize("active_target", ["prefix", "address", "integration"])
def test_active_jobs_block_entire_selection(admin_client, inventory, env, active_target):
    c = admin_client
    p, q = prefix(c, inventory), prefix(c, inventory, "198.51.100.0/24")
    config = integration(c, p)
    with env() as db:
        ip = m.IPAddress(prefix_id=p["id"], vrf_id=p["vrf_id"], address="192.0.2.1")
        db.add(ip)
        db.flush()
        target = {"prefix": q["id"], "address": ip.id, "integration": config["id"]}[active_target]
        db.add(m.Job(kind="fixture", target_id=target, active_key="fixture:" + target, status="running"))
        db.commit()
    payload, _ = confirmation(c, [p["id"], q["id"]])
    assert c.post("/api/v1/ipam/prefixes/bulk-delete", json=payload).status_code == 409
    with env() as db:
        assert db.get(m.Prefix, p["id"]) and db.get(m.Prefix, q["id"])
        assert db.get(m.Integration, config["id"]).prefix_ids == [p["id"]]


def test_changed_preview_and_missing_selection_do_not_partially_delete(admin_client, inventory, env):
    c = admin_client
    p, q = prefix(c, inventory), prefix(c, inventory, "198.51.100.0/24")
    payload, _ = confirmation(c, [p["id"], q["id"]])
    with env() as db:
        db.add(m.IPAddress(prefix_id=p["id"], vrf_id=p["vrf_id"], address="192.0.2.1"))
        db.commit()
    assert c.post("/api/v1/ipam/prefixes/bulk-delete", json=payload).status_code == 409
    assert (
        c.post("/api/v1/ipam/prefixes/bulk-delete", json={**payload, "ids": [p["id"], "missing"]}).status_code
        == 404
    )
    payload, _ = confirmation(c, [p["id"], q["id"], p["id"]])
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
