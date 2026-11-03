"""Exclusive firmware membership, filtered candidates and bounded bulk selection."""

import pytest
from netrix import models as m
from netrix.core import engine
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from test_firmware import fw as firmware_fixture

fw = firmware_fixture


def detail(fw, group):
    return fw["client"].get("/api/v1/firmware/groups/" + group["id"]).json()


def test_editing_own_members_and_atomic_rejection_of_other_group(fw):
    first, second = fw["groups"]
    original = detail(fw, first)
    response = fw["client"].put(
        "/api/v1/firmware/groups/" + first["id"],
        json={"name": first["name"], "description": "Own members stay", "device_ids": original["device_ids"]},
    )
    assert response.status_code == 200
    response = fw["client"].put(
        "/api/v1/firmware/groups/" + first["id"],
        json={"name": "Must roll back", "device_ids": [fw["devices"][2].id]},
    )
    assert response.status_code == 409 and second["name"] in response.json()["detail"]
    after = detail(fw, first)
    assert after["name"] == first["name"] and after["device_ids"] == original["device_ids"]
    assert after["description"] == "Own members stay"


def test_removal_releases_device_and_database_rejects_direct_duplicate(fw):
    first, second = fw["groups"]
    device = fw["devices"][0].id
    with fw["sf"]() as db:
        db.add(m.FirmwareMember(group_id=second["id"], device_id=device))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    remaining = [id for id in first["device_ids"] if id != device]
    assert (
        fw["client"]
        .put("/api/v1/firmware/groups/" + first["id"], json={"name": first["name"], "device_ids": remaining})
        .status_code
        == 200
    )
    assert (
        fw["client"]
        .post("/api/v1/firmware/groups", json={"name": "New owner", "device_ids": [device]})
        .status_code
        == 201
    )


def test_candidate_ownership_and_bulk_selection_respect_editing_context(fw):
    c = fw["client"]
    data = c.get("/api/v1/firmware/devices").json()
    assert data["total"] == 3 and data["selectable_total"] == 0
    assert all(not d["selectable"] and d["firmware_group_name"] for d in data["items"])
    assert c.get("/api/v1/firmware/devices/selection").json()["device_ids"] == []
    own = fw["groups"][0]
    params = {"editing_group_id": own["id"], "assignment": "available"}
    data = c.get("/api/v1/firmware/devices", params=params).json()
    assert data["total"] == data["selectable_total"] == 2
    assert all(d["selectable"] and d["firmware_group_id"] == own["id"] for d in data["items"])
    assert set(c.get("/api/v1/firmware/devices/selection", params=params).json()["device_ids"]) == set(
        own["device_ids"]
    )


def test_advanced_filters_combine_and_keep_literal_search(fw):
    with fw["sf"]() as db:
        device = db.get(m.Device, fw["devices"][0].id)
        device.name, device.adapter, device.vendor = "Corner 6100", "aruba_6100", "HPE Aruba"
        device.model, device.software_version = "6100-JL675A", "PL.10.18.1010"
        site = m.Site(name="Fixture floor", code="FW-FLOOR")
        db.add(site)
        db.flush()
        device.site_id = site.id
        scope, site_id = device.discovery_scope_id, site.id
        db.commit()
    params = {
        "q": "Corner",
        "family": "cx6100",
        "model": "JL675A",
        "vendor": "Aruba",
        "version": "10.18",
        "ip_prefix": "192.0.2.",
        "scope_id": scope,
        "site_id": site_id,
        "assignment": "assigned",
    }
    c = fw["client"]
    data = c.get("/api/v1/firmware/devices", params=params).json()
    assert data["total"] == 1 and data["items"][0]["id"] == fw["devices"][0].id
    assert c.get("/api/v1/firmware/devices", params={**params, "version": "10.17"}).json()["total"] == 0
    for search in ("%", "_", "' OR 1=1 --"):
        assert c.get("/api/v1/firmware/devices", params={"q": search}).json()["total"] == 0
    assert c.get("/api/v1/firmware/devices", params={"family": "invented"}).status_code == 422
    assert c.get("/api/v1/firmware/devices", params={"assignment": "invented"}).status_code == 422
    options = c.get("/api/v1/firmware/device-filters").json()
    assert "6100-JL675A" in options["models"] and "HPE Aruba" in options["vendors"]
    assert any(s["id"] == site_id for s in options["sites"])
    assert any(s["id"] == scope for s in options["scopes"])


def test_bulk_selection_spans_pages_and_is_bounded_without_n_plus_one(fw):
    with fw["sf"]() as db:
        first = db.get(m.Device, fw["devices"][0].id)
        db.add_all(
            m.Device(
                name=f"Bulk {i:04}",
                management_ip=f"198.18.{i // 250}.{i % 250 + 1}",
                vrf_id=first.vrf_id,
                discovery_scope_id=first.discovery_scope_id,
                adapter="aruba_6100",
                model="JL675A",
            )
            for i in range(1001)
        )
        db.commit()
    queries = []

    def before(*args):
        queries.append(args[2])

    event.listen(engine(), "before_cursor_execute", before)
    try:
        response = fw["client"].get(
            "/api/v1/firmware/devices", params={"q": "Bulk", "limit": 10, "offset": 10}
        )
        assert response.json()["total"] == 1001 and len(response.json()["items"]) == 10
        # Includes session/user lookups; ownership must be batched, never one per row.
        assert len(queries) < 12
    finally:
        event.remove(engine(), "before_cursor_execute", before)
    response = fw["client"].get("/api/v1/firmware/devices/selection", params={"q": "Bulk"})
    assert response.status_code == 422 and "1000" in response.json()["detail"]
    response = fw["client"].get("/api/v1/firmware/devices/selection", params={"q": "Bulk 00"})
    assert response.status_code == 200 and len(response.json()["device_ids"]) == 100


def test_failed_new_group_does_not_leave_an_empty_record_and_names_are_unique(fw):
    c = fw["client"]
    before = c.get("/api/v1/firmware/groups").json()
    assert (
        c.post(
            "/api/v1/firmware/groups", json={"name": "Rejected", "device_ids": [fw["devices"][0].id]}
        ).status_code
        == 409
    )
    assert c.get("/api/v1/firmware/groups").json() == before
    assert c.post("/api/v1/firmware/groups", json={"name": fw["groups"][0]["name"]}).status_code == 409
