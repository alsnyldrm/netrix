"""Passive cabling: occupied U checks, manual/inventory references and reverse reads."""

import pytest
from netrix import models as m
from sqlalchemy import func, select
from test_ipam_hierarchy import site as make_site


@pytest.fixture
def rack(admin_client, institution, inventory, env):
    c = admin_client
    site = c.post("/api/v1/sites", json={"name": "Patch Campus", "institution_id": institution["id"]}).json()
    room = make_site(c, institution, name="Room", parent_id=site["id"])
    cabinet = c.post(
        "/api/v1/cabinets", json={"name": "01", "site_id": site["id"], "sub_site_id": room["id"], "units": 12}
    ).json()
    with env() as db:
        devices = []
        for n in (1, 2):
            d = m.Device(
                name=f"SW-{n}",
                management_ip=f"192.0.2.{n}",
                vrf_id=inventory["vrf"]["id"],
                discovery_scope_id=inventory["scope"]["id"],
            )
            db.add(d)
            db.flush()
            port = m.Interface(device_id=d.id, name="A1", is_managed=True)
            db.add(port)
            db.flush()
            devices.append((d.id, port.id))
        db.commit()
    return cabinet, devices


def test_panel_lifecycle_collision_and_capacity(admin_client, rack):
    c = admin_client
    cabinet, devices = rack
    root = f"/api/v1/ipam/cabinets/{cabinet['id']}"
    base = root + "/patch-panels"
    payload = dict(name="CAT-01", kind="cat", start_unit=10, units=1, port_count=24)
    created = c.post(base, json=payload)
    assert created.status_code == 201, created.text
    panel = created.json()
    assert len(c.get(base + f"/{panel['id']}/ports").json()["items"]) == 24
    assert c.get(root).json()["patch_panels"][0]["id"] == panel["id"]
    assert c.post(base, json={**payload, "name": "CAT-02"}).status_code == 409
    assert c.post(root + "/accessories", json={"start_unit": 10}).status_code == 409
    assert (
        c.put(
            root + "/placements", json={"device_id": devices[0][0], "start_unit": 10, "units": 1}
        ).status_code
        == 409
    )
    assert (
        c.put(
            "/api/v1/cabinets/" + cabinet["id"],
            json={
                "name": "01",
                "site_id": cabinet["site_id"],
                "sub_site_id": cabinet["sub_site_id"],
                "units": 9,
            },
        ).status_code
        == 409
    )
    assert c.delete("/api/v1/cabinets/" + cabinet["id"]).status_code == 409
    assert c.post(base, json={**payload, "name": "Too high", "start_unit": 12, "units": 2}).status_code == 422
    assert c.post(base, json={**payload, "port_count": 289}).status_code == 422
    assert c.put(base + f"/{panel['id']}", json={**payload, "port_count": 48}).status_code == 200
    assert len(c.get(base + f"/{panel['id']}/ports").json()["items"]) == 48
    assert c.delete(base + f"/{panel['id']}").status_code == 204
    assert c.get(root).json()["patch_panels"] == []


def test_ports_reverse_inventory_manual_and_validation(admin_client, rack, env):
    c = admin_client
    cabinet, devices = rack
    base = f"/api/v1/ipam/cabinets/{cabinet['id']}/patch-panels"
    payload = dict(name="CAT", kind="cat", start_unit=1, units=1, port_count=2)
    panel = c.post(base, json=payload).json()
    ports_url = base + f"/{panel['id']}/ports"
    ports = c.get(ports_url).json()["items"]
    first = ports_url + "/" + ports[0]["id"]
    data = {"number": "01A", "device_id": devices[0][0], "interface_id": devices[0][1], "cable_model": "Cat6"}
    result = c.put(first, json=data)
    assert result.status_code == 200, result.text
    assert result.json()["device_name"] == "SW-1" and result.json()["port_name"] == "A1"
    reverse = f"/api/v1/devices/{devices[0][0]}/patch-ports"
    info = c.get(reverse).json()["items"][0]
    assert (
        info["cabinet_name"],
        info["panel_name"],
        info["number"],
        info["port_name"],
        info["cable_model"],
    ) == ("01", "CAT", "01A", "A1", "Cat6")
    assert c.put(first, json={**data, "interface_id": devices[1][1]}).status_code == 422
    assert c.put(first, json={**data, "cable_model": "OM3"}).status_code == 422
    assert c.put(first, json={**data, "fiber_mode": "multimode"}).status_code == 422
    assert c.put(first, json={**data, "number": "2"}).status_code == 409
    second = ports_url + "/" + ports[1]["id"]
    assert (
        c.put(
            second, json={"number": "2", "device_name": "sw-2", "port_name": "A1", "cable_model": "Cat7"}
        ).status_code
        == 200
    )
    assert len(c.get(f"/api/v1/devices/{devices[1][0]}/patch-ports").json()["items"]) == 1
    assert c.put(base + "/" + panel["id"], json={**payload, "port_count": 1}).status_code == 409
    assert (
        c.put(
            first,
            json={
                "number": "01A",
                "device_name": "External server",
                "port_name": "eth0",
                "cable_model": "Cat5",
            },
        ).status_code
        == 200
    )
    assert c.get(reverse).json()["items"] == []
    assert c.put(first, json={"number": "01A"}).status_code == 200
    assert c.get(ports_url).json()["items"][0]["device_name"] == ""
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Device)) == 2
        assert db.scalar(select(func.count()).select_from(m.Interface)) == 2
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    assert c.get(ports_url).status_code == 200
    assert c.get(reverse).status_code == 200
    assert c.put(first, json=data).status_code == 403
    assert c.post(base, json=payload).status_code == 403
    assert c.delete(base + "/" + panel["id"]).status_code == 403


@pytest.mark.parametrize("cable", ["OM3", "OM4", "Multimode MM", "Singlemode SM"])
def test_fiber_models_and_panel_scope(admin_client, rack, cable):
    c = admin_client
    cabinet, _ = rack
    base = f"/api/v1/ipam/cabinets/{cabinet['id']}/patch-panels"
    panel = c.post(base, json={"name": "Fiber", "kind": "fiber", "start_unit": 2, "port_count": 12}).json()
    url = base + f"/{panel['id']}/ports"
    port = c.get(url).json()["items"][0]
    assert c.put(url + "/" + port["id"], json={"number": "F-01", "cable_model": cable}).status_code == 200
    assert c.put(url + "/" + port["id"], json={"number": "F-01", "cable_model": "Cat6"}).status_code == 422
    wrong = f"/api/v1/ipam/cabinets/not-this-cabinet/patch-panels/{panel['id']}/ports"
    assert c.get(wrong).status_code == 404


def test_resize_keeps_labels_and_rejects_cable_type_change(admin_client, rack):
    c = admin_client
    cabinet, _ = rack
    base = f"/api/v1/ipam/cabinets/{cabinet['id']}/patch-panels"
    payload = dict(name="CAT", kind="cat", start_unit=1, units=1, port_count=2)
    panel = c.post(base, json=payload).json()
    url = base + f"/{panel['id']}"
    ports = c.get(url + "/ports").json()["items"]
    first = url + "/ports/" + ports[0]["id"]
    assert c.put(first, json={"number": "3", "cable_model": "Cat6"}).status_code == 200
    assert c.put(url, json={**payload, "port_count": 3}).status_code == 409
    assert len(c.get(url + "/ports").json()["items"]) == 2
    assert c.put(url, json={**payload, "kind": "fiber"}).status_code == 409
    assert c.put(first, json={"number": "CAT-A"}).status_code == 200
    assert c.put(url, json={**payload, "port_count": 1}).status_code == 200
    assert c.put(url, json={**payload, "port_count": 3}).status_code == 200
    updated = c.get(url + "/ports").json()["items"]
    assert [p["number"] for p in updated] == ["CAT-A", "2", "3"]
    assert updated[0]["id"] == ports[0]["id"]


@pytest.mark.parametrize(
    "model,mode",
    [
        ("OM3", "multimode"),
        ("OM4", "multimode"),
        ("OM3", "singlemode"),
        ("OM4", "singlemode"),
        ("", "singlemode"),
        ("OM3", ""),
    ],
)
def test_fiber_grade_and_mode_are_independent_and_reverse_linked(admin_client, rack, model, mode):
    c = admin_client
    cabinet, devices = rack
    base = f"/api/v1/ipam/cabinets/{cabinet['id']}/patch-panels"
    panel_data = dict(name="Fiber", kind="fiber", start_unit=2, port_count=2)
    panel = c.post(base, json=panel_data).json()
    url = base + f"/{panel['id']}/ports"
    port = c.get(url).json()["items"][1]
    endpoint = url + "/" + port["id"]
    data = {
        "number": "2",
        "device_id": devices[0][0],
        "interface_id": devices[0][1],
        "cable_model": model,
        "fiber_mode": mode,
    }
    result = c.put(endpoint, json=data)
    assert result.status_code == 200, result.text
    assert (result.json()["cable_model"], result.json()["fiber_mode"]) == (model, mode)
    stored = c.get(url).json()["items"][1]
    assert (stored["cable_model"], stored["fiber_mode"]) == (model, mode)
    reverse = c.get(f"/api/v1/devices/{devices[0][0]}/patch-ports").json()["items"][0]
    assert (reverse["cable_model"], reverse["fiber_mode"]) == (model, mode)
    assert c.put(base + "/" + panel["id"], json={**panel_data, "port_count": 1}).status_code == 409
    assert c.put(base + "/" + panel["id"], json={**panel_data, "kind": "cat"}).status_code == 409
    assert c.put(endpoint, json={**data, "fiber_mode": "unknown"}).status_code == 422
    assert c.put(endpoint, json={"number": "2", "cable_model": "", "fiber_mode": ""}).status_code == 200
    assert c.put(base + "/" + panel["id"], json={**panel_data, "port_count": 1}).status_code == 200


@pytest.mark.parametrize("legacy,mode", [("Multimode MM", "multimode"), ("Singlemode SM", "singlemode")])
def test_legacy_fiber_mode_input_is_normalized(admin_client, rack, legacy, mode):
    c = admin_client
    cabinet, _ = rack
    base = f"/api/v1/ipam/cabinets/{cabinet['id']}/patch-panels"
    panel = c.post(base, json=dict(name="Fiber", kind="fiber", start_unit=2, port_count=1)).json()
    url = base + f"/{panel['id']}/ports"
    port = c.get(url).json()["items"][0]
    result = c.put(url + "/" + port["id"], json={"number": "1", "cable_model": legacy})
    assert result.status_code == 200, result.text
    assert result.json()["cable_model"] == "" and result.json()["fiber_mode"] == mode
    opposite = "singlemode" if mode == "multimode" else "multimode"
    assert (
        c.put(
            url + "/" + port["id"], json={"number": "1", "cable_model": legacy, "fiber_mode": opposite}
        ).status_code
        == 422
    )


def test_mode_only_port_is_protected_during_panel_changes(admin_client, rack):
    c = admin_client
    cabinet, _ = rack
    base = f"/api/v1/ipam/cabinets/{cabinet['id']}/patch-panels"
    data = dict(name="Fiber", kind="fiber", start_unit=2, port_count=2)
    panel = c.post(base, json=data).json()
    url = base + "/" + panel["id"]
    port = c.get(url + "/ports").json()["items"][1]
    assert (
        c.put(url + "/ports/" + port["id"], json={"number": "2", "fiber_mode": "singlemode"}).status_code
        == 200
    )
    assert c.put(url, json={**data, "port_count": 1}).status_code == 409
    assert c.put(url, json={**data, "kind": "cat"}).status_code == 409
