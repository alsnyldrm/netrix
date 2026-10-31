"""Cabinet placement belongs to the endpoint, never its upstream switch."""

from netrix import models as m
from netrix import services
from netrix.ipam import read_cache


def test_rack_placement_flows_into_ipam_and_invalidates_cached_reads(
    admin_client, inventory, institution, env, monkeypatch
):
    c = admin_client
    monkeypatch.setattr(read_cache, "client", lambda _: services.redis_client())
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    vrf = inventory["vrf"]["id"]
    site = c.post("/api/v1/sites", json={"name": "Campus", "institution_id": institution["id"]}).json()
    cabinet_payload = {"name": "02", "site_id": site["id"], "units": 42}
    cabinet = c.post("/api/v1/cabinets", json=cabinet_payload).json()
    prefix = c.post("/api/v1/prefixes", json={"cidr": "192.0.2.0/24", "vrf_id": vrf}).json()
    with env() as db:
        device = m.Device(name="Firewall", management_ip="192.0.2.10", vrf_id=vrf)
        other_vrf = m.VRF(name="Other")
        db.add_all([device, other_vrf])
        db.flush()
        other_prefix = m.Prefix(cidr="192.0.2.0/24", vrf_id=other_vrf.id)
        db.add(other_prefix)
        db.flush()
        rows = [
            m.IPAddress(address="192.0.2.10", vrf_id=vrf, prefix_id=prefix["id"]),
            # This endpoint connects to the racked device; it does not own its cabinet.
            m.IPAddress(address="192.0.2.11", vrf_id=vrf, prefix_id=prefix["id"], device_id=device.id),
            m.IPAddress(address="192.0.2.10", vrf_id=other_vrf.id, prefix_id=other_prefix.id),
        ]
        db.add_all(rows)
        db.commit()
        device_id, address_id, other_id = device.id, rows[0].id, rows[2].id
    url = f"/api/v1/ipam/prefixes/{prefix['id']}/addresses?allocated=true"
    assert c.get(url).json()["items"][0]["cabinet"] == ""
    assert "hit" in c.get(url).headers["Server-Timing"]
    placement = f"/api/v1/ipam/cabinets/{cabinet['id']}/placements"
    assert c.put(placement, json={"device_id": device_id, "start_unit": 42, "units": 1}).status_code == 200
    response = c.get(url)
    assert "miss" in response.headers["Server-Timing"]
    items = response.json()["items"]
    assert items[0]["cabinet"] == "02"
    assert items[0]["managed"]["cabinet"] == ""
    assert items[1]["cabinet"] == ""
    assert c.get(f"/api/v1/ipam/addresses/{other_id}").json()["cabinet"] == ""
    assert c.get(f"/api/v1/ipam/addresses/{address_id}").json()["cabinet"] == "02"
    assert c.get(url + "&q=02").json()["items"][0]["cabinet"] == "02"
    assert (
        c.put("/api/v1/cabinets/" + cabinet["id"], json={**cabinet_payload, "name": "03"}).status_code == 200
    )
    assert c.get(url).json()["items"][0]["cabinet"] == "03"
    with env() as db:
        row = db.get(m.IPAddress, address_id)
        assert row.cabinet == ""  # Derived values are never copied into managed fields.
        row.cabinet = "Manual cabinet"
        db.commit()
    services.publish()
    assert c.get(url).json()["items"][0]["cabinet"] == "Manual cabinet"
    with env() as db:
        db.get(m.IPAddress, address_id).cabinet = ""
        db.commit()
    services.publish()
    assert c.delete(placement + "/" + device_id).status_code == 204
    assert c.get(url).json()["items"][0]["cabinet"] == ""
