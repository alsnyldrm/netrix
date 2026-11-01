"""Room requirements, cabinet groups, linked inventory position and atomic removals."""

import json

from conftest import make_vlan
from netrix import models as m
from sqlalchemy import select
from test_ipam_hierarchy import site


def test_inventory_cabinet_position_tracks_department_and_placement(
    admin_client, institution, inventory, env
):
    c = admin_client
    root = site(c, institution)
    room_data = {
        "name": "Server room",
        "institution_id": institution["id"],
        "parent_id": root["id"],
        "floor_number": "L-0",
        "department_name": "A",
    }
    room = c.post("/api/v1/sites", json=room_data).json()
    cabinet = c.post(
        "/api/v1/cabinets",
        json={
            "name": "4",
            "site_id": root["id"],
            "sub_site_id": room["id"],
            "units": 42,
        },
    ).json()
    general_location = site(c, institution, name="Device general location")
    with env() as db:
        devices = [
            m.Device(
                name=f"Placement {i}",
                management_ip=f"192.0.2.{i + 1}",
                vrf_id=inventory["vrf"]["id"],
                site_id=general_location["id"],
                discovery_scope_id=inventory["scope"]["id"],
            )
            for i in range(2)
        ]
        db.add_all(devices)
        db.flush()
        ids = [d.id for d in devices]
        db.commit()
    url = f"/api/v1/ipam/cabinets/{cabinet['id']}/placements"
    placement = {"device_id": ids[0], "start_unit": 13, "units": 1}
    assert c.put(url, json=placement).status_code == 200

    def position():
        rows = c.get("/api/v1/inventory/devices").json()["items"]
        by_id = {r["id"]: r for r in rows}
        assert by_id[ids[1]]["cabinet_position"] is None
        assert c.get("/api/v1/devices/" + ids[1]).json()["rack_location"] is None
        return by_id[ids[0]]["cabinet_position"]

    assert position() == "L-0/A/4/13U"
    detail_url = "/api/v1/devices/" + ids[0]
    assert c.get(detail_url).json()["rack_location"] == {
        "site_name": root["name"],
        "floor_number": "L-0",
        "department_name": "A",
        "room_name": "Server room",
        "cabinet_number": "4",
        "start_unit": 13,
    }
    assert c.put("/api/v1/sites/" + room["id"], json={**room_data, "department_name": "B"}).status_code == 200
    assert position() == "L-0/B/4/13U"
    assert c.get(detail_url).json()["rack_location"]["department_name"] == "B"
    assert c.put(url, json={**placement, "start_unit": 14}).status_code == 200
    assert position() == "L-0/B/4/14U"
    assert c.get(detail_url).json()["rack_location"]["start_unit"] == 14
    # Legacy rooms without metadata must show explicit gaps, never a guessed department.
    with env() as db:
        current = db.get(m.Site, room["id"])
        current.floor_number = current.department_name = ""
        db.commit()
    assert position() == "—/—/4/14U"
    assert c.delete(url + "/" + ids[0]).status_code == 204
    assert position() is None
    assert c.get(detail_url).json()["rack_location"] is None


def test_room_required_fields_and_cabinet_room_number(admin_client, institution):
    c = admin_client
    root = site(c, institution)
    room_data = {
        "name": "Room",
        "parent_id": root["id"],
        "institution_id": institution["id"],
        "floor_number": "L-0",
        "department_name": "A",
    }
    for field in ("name", "floor_number", "department_name"):
        assert c.post("/api/v1/sites", json={**room_data, field: "  "}).status_code == 422
    room = c.post("/api/v1/sites", json=room_data).json()
    other = site(c, institution, name="Room 2", parent_id=root["id"])
    payload = {"name": "4", "site_id": root["id"], "sub_site_id": room["id"], "units": 42}
    for field in ("name", "site_id", "sub_site_id", "units"):
        assert (
            c.post("/api/v1/cabinets", json={k: v for k, v in payload.items() if k != field}).status_code
            == 422
        )
    assert c.post("/api/v1/cabinets", json=payload).status_code == 201
    assert c.post("/api/v1/cabinets", json=payload).status_code == 409
    assert c.post("/api/v1/cabinets", json={**payload, "sub_site_id": other["id"]}).status_code == 201
    assert c.post("/api/v1/cabinets", json={**payload, "sub_site_id": root["id"]}).status_code == 422


def test_room_bulk_delete_preserves_devices_addresses_and_other_rooms(
    admin_client, institution, inventory, env
):
    c = admin_client
    root = site(c, institution)
    rooms = [site(c, institution, name=f"Room {n}", parent_id=root["id"]) for n in range(3)]
    cabinets = [
        c.post(
            "/api/v1/cabinets", json={"name": "4", "site_id": root["id"], "sub_site_id": r["id"], "units": 42}
        ).json()
        for r in rooms
    ]
    with env() as db:
        d = m.Device(
            name="Rack server",
            management_ip="192.0.2.80",
            vrf_id=inventory["vrf"]["id"],
            discovery_scope_id=inventory["scope"]["id"],
        )
        db.add(d)
        db.flush()
        db.add(m.RackPlacement(cabinet_id=cabinets[0]["id"], device_id=d.id, start_unit=13, units=1))
        db.add(m.RackAccessory(cabinet_id=cabinets[1]["id"], start_unit=3, units=1))
        panel = m.PatchPanel(
            cabinet_id=cabinets[0]["id"], name="CAT", kind="cat", start_unit=1, units=1, port_count=1
        )
        db.add(panel)
        db.flush()
        db.add(m.PatchPort(panel_id=panel.id, position=1, number="1", device_id=d.id, device_name=d.name))
        vlan = make_vlan(cidr="192.0.2.0/24", vrf_id=inventory["vrf"]["id"])
        db.add(vlan)
        db.flush()
        ip = m.IPAddress(
            vlan_id=vlan.id,
            address="192.0.2.80",
            vrf_id=inventory["vrf"]["id"],
            institution_id=institution["id"],
            site_id=root["id"],
            sub_site_id=rooms[0]["id"],
        )
        db.add(ip)
        db.commit()
        device_id, ip_id = d.id, ip.id
    listing = c.get("/api/v1/inventory/devices?q=Rack%20server").json()
    assert listing["items"][0]["cabinet_position"] == "L-0/A/4/13U"
    assert {"key": "cabinet_position", "label": "Kabin no"} in listing["columns"]
    f = json.dumps([{"field": "cabinet_position", "op": "contains", "value": "L-0/A/4", "join": "and"}])
    assert c.get("/api/v1/inventory/devices", params={"filters": f}).json()["total"] == 1
    assert c.get("/api/v1/inventory/devices", params={"q": "L-0/A/4/13U"}).json()["total"] == 1
    # Reject mixed primary locations/rooms before deleting anything.
    assert (
        c.post("/api/v1/ipam/rooms/bulk-delete", json={"ids": [rooms[0]["id"], root["id"]]}).status_code
        == 422
    )
    assert c.get("/api/v1/cabinets").json()["total"] == 3
    removed = c.post("/api/v1/ipam/rooms/bulk-delete", json={"ids": [r["id"] for r in rooms[:2]]})
    assert removed.status_code == 200, removed.text
    assert removed.json() == {"deleted": 2, "cabinets": 2}
    with env() as db:
        assert db.get(m.Device, device_id) is not None
        assert db.get(m.IPAddress, ip_id).sub_site_id is None
        assert not list(db.scalars(select(m.PatchPort)))
        assert not list(db.scalars(select(m.RackPlacement)))
        assert db.get(m.Site, rooms[2]["id"]) is not None
        assert db.get(m.Cabinet, cabinets[2]["id"]) is not None
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    assert c.post("/api/v1/ipam/cabinets/bulk-delete", json={"ids": [cabinets[2]["id"]]}).status_code == 403
