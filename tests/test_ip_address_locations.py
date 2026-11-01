from conftest import vlan_payload


def test_ip_location_hierarchy_persistence_and_validation(admin_client, institution, inventory):
    c = admin_client
    root = c.post("/api/v1/sites", json={"name": "Campus", "institution_id": institution["id"]}).json()
    child = c.post(
        "/api/v1/sites",
        json={
            "name": "Room",
            "institution_id": institution["id"],
            "parent_id": root["id"],
            "floor_number": "L-0",
            "department_name": "A",
        },
    ).json()
    other = c.post("/api/v1/institutions", json={"name": "Other", "code": "OTHER"}).json()
    prefix = c.post(
        "/api/v1/vlans", json=vlan_payload({"cidr": "192.0.2.0/24", "vrf_id": inventory["vrf"]["id"]})
    ).json()
    payload = {
        "address": "192.0.2.11",
        "vrf_id": prefix["vrf_id"],
        "vlan_id": prefix["id"],
        "institution_id": institution["id"],
        "site_id": root["id"],
        "sub_site_id": child["id"],
    }
    response = c.post("/api/v1/addresses", json=payload)
    assert response.status_code == 201, response.text
    row = response.json()
    url = "/api/v1/addresses/" + row["id"]
    assert row["location"] == "Room"
    for key in ("institution_id", "site_id", "sub_site_id"):
        assert c.get(url).json()[key] == payload[key]
    for changes in (
        {"institution_id": other["id"]},
        {"site_id": child["id"]},
        {"site_id": None},
        {"institution_id": None},
    ):
        assert c.put(url, json={**payload, **changes}).status_code == 422
    assert c.delete("/api/v1/sites/" + child["id"]).status_code == 409
    assert (
        c.put(
            "/api/v1/sites/" + child["id"],
            json={"name": "Room", "institution_id": institution["id"], "parent_id": None},
        ).status_code
        == 409
    )
    # Institution changes in bulk clear incompatible descendants, atomically.
    response = c.post(
        "/api/v1/ipam/addresses/bulk",
        json={"ids": [row["id"]], "action": "update", "changes": {"institution_id": other["id"]}},
    )
    assert response.status_code == 200, response.text
    result = c.get(url).json()
    assert result["institution_id"] == other["id"]
    assert result["site_id"] is None and result["sub_site_id"] is None and result["location"] == ""


def test_legacy_location_is_preserved_and_new_relations_survive_old_clients(
    admin_client, inventory, institution
):
    c = admin_client
    root = c.post("/api/v1/sites", json={"name": "Campus", "institution_id": institution["id"]}).json()
    prefix = c.post(
        "/api/v1/vlans", json=vlan_payload({"cidr": "192.0.2.0/24", "vrf_id": inventory["vrf"]["id"]})
    ).json()
    payload = {
        "address": "192.0.2.12",
        "vrf_id": prefix["vrf_id"],
        "vlan_id": prefix["id"],
        "location": "Legacy room",
    }
    row = c.post("/api/v1/addresses", json=payload).json()
    url = "/api/v1/addresses/" + row["id"]
    assert c.put(url, json={**payload, "hostname": "server"}).json()["location"] == "Legacy room"
    updated = c.put(url, json={**payload, "institution_id": institution["id"], "site_id": root["id"]})
    assert updated.status_code == 200, updated.text
    payload["location"] = "Campus"
    result = c.put(url, json=payload).json()
    assert result["site_id"] == root["id"]
    # Legacy bulk metadata writes must not leave a contradictory hierarchy.
    assert (
        c.post(
            "/api/v1/ipam/addresses/bulk",
            json={"ids": [row["id"]], "action": "update", "changes": {"location": "Old client location"}},
        ).status_code
        == 200
    )
    result = c.get(url).json()
    assert result["location"] == "Old client location" and result["site_id"] is None
