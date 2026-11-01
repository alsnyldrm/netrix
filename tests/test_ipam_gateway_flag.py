"""Gateway designation is manual IP metadata, preserved by source updates."""

from conftest import vlan_payload
from netrix import models as m
from netrix import services
from netrix.ipam import read_cache, service


def test_gateway_toggle_persists_without_inventory_writes(admin_client, inventory, env, monkeypatch):
    monkeypatch.setattr(read_cache, "client", lambda _: services.redis_client())
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    c = admin_client
    vlan = c.post(
        "/api/v1/vlans", json=vlan_payload({"cidr": "192.0.2.0/24", "vrf_id": inventory["vrf"]["id"]})
    ).json()
    payload = {"address": "192.0.2.1", "vlan_id": vlan["id"], "vrf_id": vlan["vrf_id"]}
    created = c.post("/api/v1/addresses", json=payload)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["is_gateway"] is False
    detail = f"/api/v1/ipam/addresses/{row['id']}"
    assert c.get(detail).json()["is_gateway"] is False  # prime the read cache
    updated = c.put(f"/api/v1/addresses/{row['id']}", json={**payload, "is_gateway": True})
    assert updated.status_code == 200, updated.text
    assert c.get(detail).json()["is_gateway"] is True
    with env() as db:
        prefix = db.get(m.VLAN, vlan["id"])
        service.observe(db, prefix, payload["address"], "icmp", "probe", {"reachability": "no_reply"})
        db.commit()
        assert db.get(m.IPAddress, row["id"]).is_gateway is True
        assert service.vlan_summary(db, prefix)["used"] == 0
    services.publish()
    listing = c.get(f"/api/v1/ipam/vlans/{vlan['id']}/addresses?allocated=true").json()
    assert listing["items"][0]["is_gateway"] is True
    result = c.post(
        "/api/v1/ipam/addresses/bulk",
        json={"ids": [row["id"]], "action": "update", "changes": {"is_gateway": False}},
    )
    assert result.status_code == 200, result.text
    assert c.get(detail).json()["is_gateway"] is False
    assert c.get("/api/v1/devices").json()["total"] == 0
