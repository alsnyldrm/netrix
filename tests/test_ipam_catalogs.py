import pytest
from test_ipam_hierarchy import site as make_site


@pytest.mark.parametrize("resource", ["cabinets", "operating-systems"])
def test_catalog_crud_validation_and_audit(admin_client, resource, institution):
    c = admin_client
    url = "/api/v1/" + resource
    extra = {}
    if resource == "cabinets":
        site = c.post(
            "/api/v1/sites", json={"name": "Campus", "code": "campus", "institution_id": institution["id"]}
        ).json()
        room = make_site(c, institution, name="Room", parent_id=site["id"])
        extra = {"site_id": site["id"], "sub_site_id": room["id"], "units": 42}
    assert c.post(url, json={"name": "  "}).status_code == 422
    response = c.post(url, json={"name": "K-01", "description": "Test", **extra})
    assert response.status_code == 201
    item = response.json()
    assert c.post(url, json={"name": "K-01", **extra}).status_code == 409
    assert c.get(url + "?q=K-01").json()["total"] == 1
    updated = c.put(url + "/" + item["id"], json={"name": "K-02", "description": "Updated", **extra})
    assert updated.status_code == 200 and updated.json()["name"] == "K-02"
    assert c.delete(url + "/" + item["id"]).status_code == 204
    assert c.get(url).json()["total"] == 0
    events = c.get("/api/v1/audit").json()["items"]
    assert {e["action"] for e in events if e["entity_type"] == resource} == {"create", "update", "delete"}


def test_cabinet_shared_location_and_referenced_delete(admin_client, institution):
    c = admin_client
    site = c.post(
        "/api/v1/sites", json={"name": "Campus", "code": "campus", "institution_id": institution["id"]}
    ).json()
    room = make_site(c, institution, name="Room", parent_id=site["id"])
    assert c.post("/api/v1/cabinets", json={"name": "K-01", "site_id": "missing"}).status_code in (404, 422)
    r = c.post(
        "/api/v1/cabinets",
        json={"name": "K-01", "site_id": site["id"], "sub_site_id": room["id"], "units": 42},
    )
    assert r.status_code == 201 and r.json()["site_id"] == site["id"]
    assert c.delete("/api/v1/sites/" + site["id"]).status_code == 409


@pytest.mark.parametrize("resource", ["cabinets", "operating-systems"])
def test_catalog_viewer_cannot_mutate(admin_client, resource):
    c = admin_client
    c.post(
        "/api/v1/users",
        json={
            "email": "viewer@example.test",
            "display_name": "Viewer",
            "password": "test-only-viewer-long",
            "role": "viewer",
        },
    )
    c.post("/api/v1/auth/logout")
    assert (
        c.post(
            "/api/v1/auth/login", json={"email": "viewer@example.test", "password": "test-only-viewer-long"}
        ).status_code
        == 200
    )
    assert c.get("/api/v1/" + resource).status_code == 200
    assert c.post("/api/v1/" + resource, json={"name": "Denied"}).status_code == 403
