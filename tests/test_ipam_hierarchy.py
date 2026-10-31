import json

from netrix import models as m
from netrix.ipam.service import observe
from sqlalchemy import select


def site(c, institution, **kwargs):
    r = c.post("/api/v1/sites", json={"name": "FBU-A", "institution_id": institution["id"], **kwargs})
    assert r.status_code == 201, r.text
    return r.json()


def test_location_codes_gap_reuse_and_hierarchy(admin_client, institution):
    c = admin_client
    assert c.post("/api/v1/sites", json={"name": "Missing institution"}).status_code == 422
    root = site(c, institution, code="01-000001")
    children = [site(c, institution, name=f"Kat {i}", parent_id=root["id"]) for i in range(5)]
    assert [r["code"] for r in children] == [f"01-0000{i}" for i in range(11, 16)]
    assert c.delete("/api/v1/sites/" + children[3]["id"]).status_code == 204
    assert site(c, institution, parent_id=root["id"])["code"] == "01-000014"
    assert (
        c.post(
            "/api/v1/sites",
            json={"name": "Too deep", "institution_id": institution["id"], "parent_id": children[0]["id"]},
        ).status_code
        == 422
    )
    other = c.post("/api/v1/institutions", json={"name": "Other", "code": "02"}).json()
    assert (
        c.post(
            "/api/v1/sites",
            json={"name": "Wrong institution", "institution_id": other["id"], "parent_id": root["id"]},
        ).status_code
        == 422
    )
    assert c.delete("/api/v1/institutions/" + institution["id"]).status_code == 409
    assert c.delete("/api/v1/sites/" + root["id"]).status_code == 409


def test_cabinet_units_placements_atomic_and_inventory_preserved(admin_client, institution, env):
    c = admin_client
    root = site(c, institution)
    sub = site(c, institution, parent_id=root["id"])
    payload = {"name": "K-01", "site_id": root["id"], "sub_site_id": sub["id"], "units": 12}
    cabinet = c.post("/api/v1/cabinets", json=payload).json()
    with env() as db:
        vrf = db.scalar(select(m.VRF))
        devices = [
            m.Device(
                name=f"Switch {i}",
                management_ip=f"192.0.2.{i + 1}",
                vrf_id=vrf.id,
                kind="switch",
                vendor="Aruba",
                model="6100-JL675A",
            )
            for i in range(2)
        ]
        db.add_all(devices)
        db.commit()
        ids = [d.id for d in devices]
    url = f"/api/v1/ipam/cabinets/{cabinet['id']}/placements"
    assert c.put(url, json={"device_id": ids[0], "start_unit": 10, "units": 4}).status_code == 422
    assert c.put(url, json={"device_id": ids[0], "start_unit": 10, "units": 2}).status_code == 200
    assert c.put(url, json={"device_id": ids[1], "start_unit": 11, "units": 1}).status_code == 409
    assert c.put("/api/v1/cabinets/" + cabinet["id"], json={**payload, "units": 10}).status_code == 409
    detail = c.get(f"/api/v1/ipam/cabinets/{cabinet['id']}").json()
    assert len(detail["placements"]) == 1
    assert detail["placements"][0]["image"]["url"].startswith("https://assets.ext.hpe.com/")
    assert c.delete(url + "/" + ids[0]).status_code == 204
    assert c.get("/api/v1/devices/" + ids[0]).status_code == 200


def test_checkbox_authorization_and_cidr_change_revokes(admin_client, inventory):
    c = admin_client
    p = c.post("/api/v1/prefixes", json={"cidr": "192.0.2.0/30", "vrf_id": inventory["vrf"]["id"]}).json()
    base = f"/api/v1/ipam/prefixes/{p['id']}"
    assert c.post(base + "/discover").status_code == 422
    assert c.put(base + "/settings", json={"scan_authorized": True, "ping_enabled": True}).status_code == 200
    assert c.post(base + "/discover").status_code == 202
    assert (
        c.put(base + "/settings", json={"scan_authorized": False, "ping_enabled": True}).json()[
            "ping_enabled"
        ]
        is False
    )
    assert c.post(base + "/ping").status_code == 422
    c.put(base + "/settings", json={"scan_authorized": True})
    c.put("/api/v1/prefixes/" + p["id"], json={"cidr": "198.51.100.0/30", "vrf_id": p["vrf_id"]})
    assert c.post(base + "/ping").status_code == 422


def test_search_filters_bulk_and_observed_address_lock(admin_client, inventory, env):
    c = admin_client
    p = c.post("/api/v1/prefixes", json={"cidr": "192.0.2.0/24", "vrf_id": inventory["vrf"]["id"]}).json()
    with env() as db:
        prefix = db.get(m.Prefix, p["id"])
        for i in range(1, 112):
            row = m.IPAddress(
                address=f"192.0.2.{i}",
                prefix_id=prefix.id,
                vrf_id=prefix.vrf_id,
                hostname=f"Host {i}",
                operating_system="Linux",
                status="active",
            )
            db.add(row)
        db.flush()
        observed = observe(
            db,
            prefix,
            "192.0.2.111",
            "vcenter",
            "vm-1",
            {"mac_address": "aa:bb:cc:dd:ee:ff", "reachability": "no_reply"},
        )
        observed_id = observed.id
        observe(db, prefix, "192.0.2.111", "icmp", prefix.id, {"reachability": "no_reply"})
        db.commit()
    base = f"/api/v1/ipam/prefixes/{p['id']}/addresses"
    r = c.get(base, params={"q": "LINUX ee:ff", "allocated": "true"}).json()
    assert r["total"] == "1" and r["items"][0]["address"] == "192.0.2.111"
    assert r["items"][0]["availability"] == "passive"
    filters = [
        {"field": "hostname", "op": "contains", "value": "110", "join": "and"},
        {"field": "mac_address", "op": "contains", "value": "ee:ff", "join": "or"},
        {"field": "operating_system", "op": "not_contains", "value": "Windows", "join": "and"},
    ]
    r = c.get(base, params={"filters": json.dumps(filters), "allocated": "true"}).json()
    assert r["total"] == "2"
    ids = [row["id"] for row in r["items"]]
    assert (
        c.post(
            "/api/v1/ipam/addresses/bulk",
            json={"ids": ids, "action": "update", "changes": {"address": "192.0.2.200"}},
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/ipam/addresses/bulk",
            json={
                "ids": ids,
                "action": "update",
                "changes": {"hostname": "Updated", "interface_id": "missing"},
            },
        ).status_code
        == 404
    )
    assert c.get("/api/v1/addresses/" + ids[0]).json()["hostname"] != "Updated"
    assert (
        c.post(
            "/api/v1/ipam/addresses/bulk",
            json={"ids": ids, "action": "update", "changes": {"operating_system": "Windows"}},
        ).json()["affected"]
        == 2
    )
    item = c.get("/api/v1/addresses/" + observed_id).json()
    from netrix.schemas import IPInput

    data = {k: item[k] for k in IPInput.model_fields}
    assert (
        c.put("/api/v1/addresses/" + observed_id, json={**data, "address": "192.0.2.200"}).status_code == 409
    )
    assert (
        c.post("/api/v1/ipam/addresses/bulk", json={"ids": ids, "action": "delete"}).json()["affected"] == 2
    )
    assert c.get(base, params={"filters": "[[]]"}).status_code == 422


def test_interface_device_ownership_and_usage_reservations(admin_client, inventory, env):
    c = admin_client
    p = c.post("/api/v1/prefixes", json={"cidr": "192.0.2.0/30", "vrf_id": inventory["vrf"]["id"]}).json()
    with env() as db:
        devices = [
            m.Device(name=f"D{i}", management_ip=f"192.0.2.{i + 1}", vrf_id=p["vrf_id"]) for i in range(2)
        ]
        db.add_all(devices)
        db.flush()
        port = m.Interface(device_id=devices[0].id, name="Port 1", is_managed=True)
        db.add(port)
        db.commit()
        first, second, port_id = devices[0].id, devices[1].id, port.id
    data = dict(address="192.0.2.1", prefix_id=p["id"], vrf_id=p["vrf_id"], interface_id=port_id)
    assert c.post("/api/v1/addresses", json={**data, "device_id": second}).status_code == 422
    assert c.post("/api/v1/addresses", json={**data, "device_id": first}).status_code == 201
    summary = c.put(f"/api/v1/ipam/prefixes/{p['id']}/settings", json={"warning_threshold": 80}).json()
    assert summary["utilization"] == 0 and summary["threshold_exceeded"] is False
    with env() as db:
        observe(db, db.get(m.Prefix, p["id"]), "192.0.2.1", "icmp", p["id"], {"reachability": "reachable"})
        db.commit()
    summary = c.put(f"/api/v1/ipam/prefixes/{p['id']}/settings", json={"warning_threshold": 80}).json()
    assert summary["utilization"] == 50 and summary["threshold_exceeded"] is False
    assert (
        c.put(f"/api/v1/ipam/prefixes/{p['id']}/settings", json={"warning_threshold": 50}).json()[
            "threshold_exceeded"
        ]
        is True
    )
    with env() as db:
        observe(db, db.get(m.Prefix, p["id"]), "192.0.2.1", "icmp", p["id"], {"reachability": "no_reply"})
        db.commit()
    result = c.get(f"/api/v1/ipam/prefixes/{p['id']}/addresses?allocated=true").json()
    assert result["prefix"]["used"] == 0
    assert result["items"][0]["connected_device"] == "D0" and result["items"][0]["connected_port"] == "Port 1"


def test_manufacturer_image_exact_model_and_official_urls(admin_client, inventory, env):
    from netrix.ipam.model_images import model_image

    with env() as db:
        assert model_image(db, "Aruba", "Unknown model") is None
        assert model_image(db, "Other", "JL675A") is None
        assert model_image(db, "Aruba", "6100-JL675A")["url"].startswith("https://assets.ext.hpe.com/")
        d = m.Device(
            name="Photo",
            management_ip="192.0.2.40",
            vrf_id=inventory["vrf"]["id"],
            vendor="HPE",
            model="JG962A",
        )
        db.add(d)
        db.commit()
        device_id = d.id
    endpoint = f"/api/v1/ipam/devices/{device_id}/model-image"
    c = admin_client
    data = {"url": "https://assets.ext.hpe.com/is/image/hpedam/model", "source": "https://www.hpe.com/model"}
    for bad in (
        "https://example.com/photo.png",
        "https://assets.ext.hpe.com.evil.test/a",
        "http://assets.ext.hpe.com/a",
        "https://user:password@assets.ext.hpe.com/a",
    ):
        assert c.put(endpoint, json={**data, "url": bad}).status_code == 422
    assert c.put(endpoint, json=data).status_code == 200
    with env() as db:
        assert model_image(db, "hpe", "jg962a") == data
        assert model_image(db, "HPE", "JG962A-other") is None


def test_checkbox_keeps_legacy_exclusions_and_authorizes_inventory(admin_client, inventory, env):
    import pytest
    from netrix.ipam.service import require_scope
    from netrix.services import authorized_device

    c = admin_client
    p = c.post("/api/v1/prefixes", json={"cidr": "198.51.100.0/24", "vrf_id": inventory["vrf"]["id"]}).json()
    with env() as db:
        scope = m.Scope(
            name="Legacy",
            credential_id=inventory["credential"]["id"],
            cidr=p["cidr"],
            vrf_id=p["vrf_id"],
            exclusions=["198.51.100.2/32"],
            enabled=False,
        )
        db.add(scope)
        db.flush()
        db.get(m.Prefix, p["id"]).scope_id = scope.id
        db.commit()
        scope_id = scope.id
    assert (
        c.put(f"/api/v1/ipam/prefixes/{p['id']}/settings", json={"scan_authorized": True}).status_code == 200
    )
    with env() as db:
        prefix = db.get(m.Prefix, p["id"])
        assert prefix.scope_id == scope_id
        assert require_scope(db, prefix).exclusions == ["198.51.100.2/32"]
        allowed = m.Device(
            name="Allowed",
            management_ip="198.51.100.1",
            vrf_id=p["vrf_id"],
            archived=False,
            lifecycle_status="active",
        )
        authorized_device(db, allowed)
        allowed.management_ip = "198.51.100.2"
        with pytest.raises(ValueError):
            authorized_device(db, allowed)


def test_virtual_port_visible_without_claiming_physical_connection(admin_client, inventory, env):
    c = admin_client
    p = c.post("/api/v1/prefixes", json={"cidr": "203.0.113.0/24", "vrf_id": inventory["vrf"]["id"]}).json()
    with env() as db:
        observe(
            db,
            db.get(m.Prefix, p["id"]),
            "203.0.113.2",
            "vcenter",
            "vm-2",
            {"dvport": "42", "dvswitch": "ds-1", "power_state": "poweredOn"},
        )
        db.commit()
    row = c.get(f"/api/v1/ipam/prefixes/{p['id']}/addresses?allocated=true").json()["items"][0]
    assert row["connected_port"] == "42" and row["connected_device"] == "VMware"
    assert "connections" not in row and row["availability"] == "unknown"
