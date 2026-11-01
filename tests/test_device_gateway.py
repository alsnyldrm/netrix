import json

import pytest
from netrix import models as m
from netrix.worker import claim, execute
from test_identification import IdentityCollector, create_device


def test_gateway_defaults_off_and_edit_persists_both_states(admin_client, inventory, env):
    device, payload = create_device(admin_client, inventory)
    assert device["is_gateway"] is False
    for enabled in (True, False):
        response = admin_client.put(
            "/api/v1/devices/" + device["id"], json={**payload, "is_gateway": enabled}
        )
        assert response.status_code == 200, response.text
        assert response.json()["is_gateway"] is enabled
        assert admin_client.get("/api/v1/devices/" + device["id"]).json()["is_gateway"] is enabled
        with env() as db:
            assert db.get(m.Device, device["id"]).is_gateway is enabled
    created = admin_client.post(
        "/api/v1/devices", json={**payload, "management_ip": "192.0.2.2", "is_gateway": True}
    )
    assert created.status_code == 201 and created.json()["is_gateway"] is True


def test_gateway_is_available_in_inventory_columns_and_filters(admin_client, inventory):
    gateway, _ = create_device(admin_client, inventory, is_gateway=True)
    create_device(admin_client, inventory, management_ip="192.0.2.2", is_gateway=False)
    response = admin_client.get("/api/v1/inventory/devices").json()
    assert any(c["key"] == "is_gateway" and c["label"] == "Gateway Cihazı" for c in response["columns"])
    found = admin_client.get("/api/v1/inventory/devices", params={"q": "Gateway"}).json()
    assert found["total"] == 1 and found["items"][0]["id"] == gateway["id"]
    for op, value in (("eq", "Evet"), ("ne", "Hayır"), ("contains", "Evet")):
        response = admin_client.get(
            "/api/v1/inventory/devices",
            params={"filters": json.dumps([{"field": "is_gateway", "op": op, "value": value}])},
        ).json()
        assert response["total"] == 1 and response["items"][0]["id"] == gateway["id"]
        assert response["items"][0]["is_gateway"] is True


@pytest.mark.parametrize("enabled", [True, False])
async def test_device_observations_do_not_overwrite_gateway_setting(admin_client, inventory, env, enabled):
    device, _ = create_device(admin_client, inventory, is_gateway=enabled)
    job = admin_client.post("/api/v1/jobs", json={"kind": "identify", "target_id": device["id"]}).json()
    assert claim() == job["id"]
    await execute(
        job["id"],
        IdentityCollector({"vendor": "HP", "model": "J9851A", "kind": "switch", "is_gateway": not enabled}),
    )
    current = admin_client.get("/api/v1/devices/" + device["id"]).json()
    assert current["vendor"] == "HP" and current["is_gateway"] is enabled
    with env() as db:
        assert db.get(m.Job, job["id"]).status == "succeeded"
