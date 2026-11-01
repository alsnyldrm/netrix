"""Primary location IDs cannot contain sublocations, including API and bulk writes."""

import pytest
from conftest import vlan_payload
from test_ipam_hierarchy import site


def payload(resource, inventory, institution, site_id):
    base = {"site_id": site_id, "institution_id": institution["id"], "vrf_id": inventory["vrf"]["id"]}
    return {
        "devices": {
            "name": "Core",
            "management_ip": "192.0.2.1",
            "site_id": site_id,
            "vrf_id": base["vrf_id"],
        },
        "scopes": {
            **base,
            "name": "Scope",
            "cidr": "198.51.100.0/24",
            "credential_ids": [inventory["credential"]["id"]],
        },
        "vlans": vlan_payload({**base, "cidr": "198.51.100.0/24"}),
        "addresses": {**base, "address": "198.51.100.2"},
        "cabinets": {"name": "Rack", "site_id": site_id},
    }[resource]


@pytest.mark.parametrize("resource", ["devices", "scopes", "vlans", "addresses", "cabinets"])
def test_primary_location_rejects_children_on_create_and_edit(admin_client, institution, inventory, resource):
    root = site(admin_client, institution)
    child = site(admin_client, institution, name="Server room", parent_id=root["id"])
    data = payload(resource, inventory, institution, child["id"])
    if resource == "cabinets":
        data.update(sub_site_id=child["id"], units=42)
    if resource == "addresses":
        prefix = admin_client.post(
            "/api/v1/vlans", json=vlan_payload(payload("vlans", inventory, institution, root["id"]))
        )
        assert prefix.status_code == 201, prefix.text
        data["vlan_id"] = prefix.json()["id"]
    response = admin_client.post("/api/v1/" + resource, json=data)
    assert response.status_code == 422, response.text
    assert "ana lokasyon" in response.json()["detail"]
    data["site_id"] = root["id"]
    if resource == "cabinets":
        data.update(sub_site_id=child["id"], units=42)
    response = admin_client.post("/api/v1/" + resource, json=data)
    assert response.status_code == 201, response.text
    id = response.json()["id"]
    data["site_id"] = child["id"]
    assert admin_client.put(f"/api/v1/{resource}/{id}", json=data).status_code == 422
    assert admin_client.get(f"/api/v1/{resource}/{id}").json()["site_id"] == root["id"]
    if resource == "devices":
        response = admin_client.post(
            "/api/v1/inventory/devices/bulk",
            json={"ids": [id], "action": "update", "changes": {"site_id": child["id"]}},
        )
        assert response.status_code == 422
        assert admin_client.get(f"/api/v1/devices/{id}").json()["site_id"] == root["id"]


@pytest.mark.parametrize("resource", ["devices", "scopes", "vlans"])
def test_used_primary_location_cannot_become_child(admin_client, institution, inventory, resource):
    root = site(admin_client, institution)
    other = site(admin_client, institution, name="Other campus")
    response = admin_client.post(
        "/api/v1/" + resource, json=payload(resource, inventory, institution, root["id"])
    )
    assert response.status_code == 201, response.text
    response = admin_client.put(
        "/api/v1/sites/" + root["id"],
        json={
            "name": root["name"],
            "code": root["code"],
            "institution_id": institution["id"],
            "parent_id": other["id"],
            "floor_number": "L-0",
            "department_name": "A",
        },
    )
    assert response.status_code == 409, response.text
    assert admin_client.get("/api/v1/sites/" + root["id"]).json()["parent_id"] is None
