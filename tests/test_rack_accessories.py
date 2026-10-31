from netrix import models as m
from sqlalchemy import func, select


def test_organizer_crud_collision_capacity_and_scope(admin_client, institution, env):
    c = admin_client
    site = c.post("/api/v1/sites", json={"name": "Campus", "institution_id": institution["id"]}).json()
    payload = {"name": "02", "site_id": site["id"], "units": 12}
    cabinet = c.post("/api/v1/cabinets", json=payload).json()
    other = c.post("/api/v1/cabinets", json={**payload, "name": "03"}).json()
    with env() as db:
        vrf = db.scalar(select(m.VRF))
        device = m.Device(name="Switch", vrf_id=vrf.id, management_ip="192.0.2.10")
        db.add(device)
        db.commit()
        device_id = device.id
    base = f"/api/v1/ipam/cabinets/{cabinet['id']}"
    assert (
        c.put(base + "/placements", json={"device_id": device_id, "start_unit": 10, "units": 2}).status_code
        == 200
    )
    url = base + "/accessories"
    assert c.post(url, json={"start_unit": 9, "units": 2}).status_code == 409
    assert c.post(url, json={"start_unit": 12, "units": 2}).status_code == 422
    assert c.post(url, json={"start_unit": 0}).status_code == 422
    assert c.post(url, json={"start_unit": 1, "kind": "unknown"}).status_code == 422
    r = c.post(url, json={"start_unit": 9})
    assert r.status_code == 201, r.text
    organizer = r.json()
    item_url = url + "/" + organizer["id"]
    assert organizer["kind"] == "brush_organizer" and organizer["units"] == 1
    assert len(c.get(base).json()["accessories"]) == 1
    assert c.post(url, json={"start_unit": 8, "units": 2}).status_code == 409
    assert (
        c.put(base + "/placements", json={"device_id": device_id, "start_unit": 8, "units": 2}).status_code
        == 409
    )
    assert c.put(item_url, json={"start_unit": 9}).status_code == 200
    assert c.put(item_url, json={"start_unit": 11}).status_code == 409
    assert c.put(item_url, json={"start_unit": 12}).status_code == 200
    assert c.put("/api/v1/cabinets/" + cabinet["id"], json={**payload, "units": 11}).status_code == 409
    wrong = f"/api/v1/ipam/cabinets/{other['id']}/accessories/{organizer['id']}"
    assert c.put(wrong, json={"start_unit": 1}).status_code == 404
    assert c.delete(wrong).status_code == 404
    assert c.delete("/api/v1/cabinets/" + cabinet["id"]).status_code == 409
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Device)) == 1
        assert db.scalar(select(func.count()).select_from(m.IPAddress)) == 0
        user = db.scalar(select(m.User))
        user.role = "viewer"
        db.commit()
    assert c.get(base).status_code == 200
    assert c.post(url, json={"start_unit": 1}).status_code == 403
    assert c.put(item_url, json={"start_unit": 1}).status_code == 403
    assert c.delete(item_url).status_code == 403
    with env() as db:
        db.scalar(select(m.User)).role = "admin"
        db.commit()
    assert c.delete(item_url).status_code == 204
    assert c.get(base).json()["accessories"] == []
    assert c.put("/api/v1/cabinets/" + cabinet["id"], json={**payload, "units": 11}).status_code == 200
