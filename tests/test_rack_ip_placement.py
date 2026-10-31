import pytest
from netrix import models as m
from netrix.ipam.service import observe
from sqlalchemy import func, select


def setup(c, institution, vrf):
    site = c.post("/api/v1/sites", json={"name": "Server room", "institution_id": institution["id"]}).json()
    cabinet = c.post("/api/v1/cabinets", json={"name": "04", "site_id": site["id"], "units": 42}).json()
    prefix = c.post("/api/v1/prefixes", json={"cidr": "192.0.2.0/24", "vrf_id": vrf}).json()
    return cabinet, prefix


@pytest.mark.parametrize("kind", ["server", "storage", "san_switch"])
def test_ipam_promotes_own_endpoint_and_reuses_central_inventory(
    admin_client, inventory, institution, env, kind
):
    c = admin_client
    cabinet, prefix = setup(c, institution, inventory["vrf"]["id"])
    with env() as db:
        upstream = m.Device(name="Management switch", management_ip="192.0.2.254", vrf_id=prefix["vrf_id"])
        db.add(upstream)
        db.flush()
        address = m.IPAddress(
            address="192.0.2.65",
            hostname="SV-ID-01",
            vrf_id=prefix["vrf_id"],
            prefix_id=prefix["id"],
            device_id=upstream.id,
        )
        db.add(address)
        db.commit()
        address_id, upstream_id = address.id, upstream.id
    base = f"/api/v1/ipam/cabinets/{cabinet['id']}"
    assert (
        c.put(base + "/placements", json={"device_id": upstream_id, "start_unit": 42, "units": 1}).status_code
        == 200
    )
    payload = {
        "address_id": address_id,
        "name": "SV-ID-01",
        "kind": kind,
        "start_unit": 1,
        "units": 2,
        "vendor": "Example",
        "model": "Model X",
    }
    r = c.post(base + "/placements/from-ip", json=payload)
    assert r.status_code == 200, r.text
    device_id = r.json()["selected_device_id"]
    assert device_id != upstream_id
    assert len(r.json()["placements"]) == 2
    assert c.get(f"/api/v1/ipam/addresses/{address_id}").json()["cabinet"] == "04"
    assert (
        c.post(
            base + "/placements/from-ip",
            json={**payload, "name": "Do not overwrite", "kind": "switch", "start_unit": 3},
        ).status_code
        == 200
    )
    with env() as db:
        device = db.get(m.Device, device_id)
        assert (device.name, device.kind, device.management_ip, device.vendor) == (
            "SV-ID-01",
            kind,
            "192.0.2.65",
            "Example",
        )
        assert db.scalar(select(func.count()).select_from(m.Device)) == 2
        assert db.scalar(select(func.count()).select_from(m.Job)) == 0
        assert db.get(m.IPAddress, address_id).device_id == upstream_id
        assert not device.monitoring_enabled and device.snmp_credential_id is None
    # Existing placement must survive a rejected move onto the management switch.
    assert c.post(base + "/placements/from-ip", json={**payload, "start_unit": 41}).status_code == 409
    placements = c.get(base).json()["placements"]
    assert next(p for p in placements if p["device_id"] == device_id)["start_unit"] == 3
    other = c.post("/api/v1/cabinets", json={"name": "05", "site_id": cabinet["site_id"], "units": 42}).json()
    assert c.post(f"/api/v1/ipam/cabinets/{other['id']}/placements/from-ip", json=payload).status_code == 409
    with env() as db:
        db.get(m.Device, device_id).archived = True
        db.commit()
    assert c.post(base + "/placements/from-ip", json=payload).status_code == 422


def test_ip_placement_atomic_validation_vrf_virtual_and_permissions(
    admin_client, inventory, institution, env
):
    c = admin_client
    cabinet, prefix = setup(c, institution, inventory["vrf"]["id"])
    with env() as db:
        other = m.VRF(name="Other")
        db.add(other)
        db.flush()
        db.add(m.Device(name="Unrelated", management_ip="192.0.2.65", vrf_id=other.id))
        ip = m.IPAddress(address="192.0.2.65", vrf_id=prefix["vrf_id"], prefix_id=prefix["id"])
        db.add(ip)
        db.commit()
        address_id = ip.id
    base = f"/api/v1/ipam/cabinets/{cabinet['id']}"
    payload = {"address_id": address_id, "name": "Storage", "kind": "storage", "start_unit": 1, "units": 2}
    assert c.post(base + "/accessories", json={"start_unit": 1}).status_code == 201
    assert c.post(base + "/placements/from-ip", json=payload).status_code == 409
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Device)) == 1
        observe(
            db,
            db.get(m.Prefix, prefix["id"]),
            "192.0.2.65",
            "vcenter",
            "vm",
            {"vm_id": "vm-1", "dvswitch": "dvs"},
        )
        db.commit()
    assert c.post(base + "/placements/from-ip", json={**payload, "start_unit": 3}).status_code == 422
    with env() as db:
        db.query(m.IPObservation).delete()
        db.commit()
    assert (
        c.post(base + "/placements/from-ip", json={**payload, "start_unit": 3, "kind": "missing"}).status_code
        == 422
    )
    r = c.post(base + "/placements/from-ip", json={**payload, "start_unit": 3})
    assert r.status_code == 200, r.text
    with env() as db:
        assert db.get(m.Device, r.json()["selected_device_id"]).vrf_id == prefix["vrf_id"]
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    assert c.post(base + "/placements/from-ip", json=payload).status_code == 403
