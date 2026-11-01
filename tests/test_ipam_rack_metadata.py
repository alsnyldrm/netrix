"""Cabinet placement belongs to the endpoint, never its upstream switch."""

from conftest import make_vlan, vlan_payload
from netrix import models as m
from netrix import services
from netrix.ipam import read_cache
from test_ipam_hierarchy import site as make_site


def test_rack_placement_flows_into_ipam_and_invalidates_cached_reads(
    admin_client, inventory, institution, env, monkeypatch
):
    c = admin_client
    monkeypatch.setattr(read_cache, "client", lambda _: services.redis_client())
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    vrf = inventory["vrf"]["id"]
    site = c.post("/api/v1/sites", json={"name": "Campus", "institution_id": institution["id"]}).json()
    room = make_site(c, institution, name="Room", parent_id=site["id"])
    cabinet_payload = {"name": "02", "site_id": site["id"], "sub_site_id": room["id"], "units": 42}
    cabinet = c.post("/api/v1/cabinets", json=cabinet_payload).json()
    prefix = c.post("/api/v1/vlans", json=vlan_payload({"cidr": "192.0.2.0/24", "vrf_id": vrf})).json()
    with env() as db:
        device = m.Device(name="Firewall", management_ip="192.0.2.10", vrf_id=vrf)
        other_vrf = m.VRF(name="Other")
        db.add_all([device, other_vrf])
        db.flush()
        other_prefix = make_vlan(cidr="192.0.2.0/24", vrf_id=other_vrf.id)
        db.add(other_prefix)
        db.flush()
        rows = [
            m.IPAddress(address="192.0.2.10", vrf_id=vrf, vlan_id=prefix["id"]),
            # This endpoint connects to the racked device; it does not own its cabinet.
            m.IPAddress(address="192.0.2.11", vrf_id=vrf, vlan_id=prefix["id"], device_id=device.id),
            m.IPAddress(address="192.0.2.10", vrf_id=other_vrf.id, vlan_id=other_prefix.id),
        ]
        db.add_all(rows)
        db.commit()
        device_id, address_id, other_id = device.id, rows[0].id, rows[2].id
    url = f"/api/v1/ipam/vlans/{prefix['id']}/addresses?allocated=true"
    assert c.get(url).json()["items"][0]["cabinet"] == ""
    assert "hit" in c.get(url).headers["Server-Timing"]
    placement = f"/api/v1/ipam/cabinets/{cabinet['id']}/placements"
    assert c.put(placement, json={"device_id": device_id, "start_unit": 42, "units": 1}).status_code == 200
    response = c.get(url)
    assert "miss" in response.headers["Server-Timing"]
    items = response.json()["items"]
    assert items[0]["cabinet"] == "L-0/A/02/42U"
    assert items[0]["rack_position"] == "L-0/A/02/42U"
    assert items[0]["managed"]["cabinet"] == ""
    assert items[1]["cabinet"] == ""
    assert c.get(f"/api/v1/ipam/addresses/{other_id}").json()["cabinet"] == ""
    assert c.get(f"/api/v1/ipam/addresses/{address_id}").json()["cabinet"] == "L-0/A/02/42U"
    assert c.get(url + "&q=02").json()["items"][0]["cabinet"] == "L-0/A/02/42U"
    assert (
        c.put("/api/v1/cabinets/" + cabinet["id"], json={**cabinet_payload, "name": "03"}).status_code == 200
    )
    assert c.get(url).json()["items"][0]["cabinet"] == "L-0/A/03/42U"
    with env() as db:
        row = db.get(m.IPAddress, address_id)
        assert row.cabinet == ""  # Derived values are never copied into managed fields.
        row.cabinet = "Manual cabinet"
        db.commit()
    services.publish()
    item = c.get(url).json()["items"][0]
    assert item["cabinet"] == "L-0/A/03/42U"
    assert item["managed"]["cabinet"] == "Manual cabinet"
    assert c.put(placement, json={"device_id": device_id, "start_unit": 13, "units": 1}).status_code == 200
    room_change = {
        "name": room["name"],
        "institution_id": room["institution_id"],
        "parent_id": site["id"],
        "floor_number": "L-1",
        "department_name": "B",
    }
    assert c.put("/api/v1/sites/" + room["id"], json=room_change).status_code == 200
    assert c.get(url).json()["items"][0]["cabinet"] == "L-1/B/03/13U"
    assert c.get(url + "&q=L-1/B/03/13U").json()["items"][0]["id"] == address_id
    assert c.get(f"/api/v1/ipam/addresses/{address_id}").json()["cabinet"] == "L-1/B/03/13U"
    with env() as db:
        db.get(m.IPAddress, address_id).cabinet = ""
        db.commit()
    services.publish()
    assert c.delete(placement + "/" + device_id).status_code == 204
    assert c.get(url).json()["items"][0]["cabinet"] == ""


def test_legacy_room_fields_and_many_positions_use_one_query(env, inventory):
    from netrix.ipam import racks
    from test_read_performance import queries

    with env() as db:
        vlan = make_vlan(cidr="192.0.2.0/24", vrf_id=inventory["vrf"]["id"])
        cabinet = m.Cabinet(name="4", units=42)
        db.add_all([vlan, cabinet])
        db.flush()
        rows, device_ids = [], []
        for unit in range(1, 21):
            device = m.Device(name=f"Racked {unit}", management_ip=f"192.0.2.{unit}", vrf_id=vlan.vrf_id)
            db.add(device)
            db.flush()
            device_ids.append(device.id)
            row = m.IPAddress(address=device.management_ip, vrf_id=vlan.vrf_id, vlan_id=vlan.id)
            db.add(row)
            db.add(m.RackPlacement(cabinet_id=cabinet.id, device_id=device.id, start_unit=unit, units=1))
            rows.append(row)
        db.commit()
        with queries() as sql:
            positions = racks.address_cabinets(db, rows)
        assert len(sql) == 1
        assert len(positions) == 20
        assert positions[rows[12].id] == "—/—/4/13U"
        db.get(m.Device, device_ids[0]).archived = True
        db.commit()
        assert rows[0].id not in racks.address_cabinets(db, rows)
