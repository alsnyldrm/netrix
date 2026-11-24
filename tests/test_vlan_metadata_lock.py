from netrix import models as m
from netrix import schemas, services
from test_ipam_source_contract import network as network


def test_vlan_metadata_save_does_not_wait_for_vrf_scan_lock(admin_client, network, monkeypatch):
    sf, vid, _, _ = network
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        payload = {key: getattr(vlan, key) for key in schemas.VLANInput.model_fields}
    payload["network_type"] = "public"

    def blocked(*_):
        raise AssertionError("Metadata edit waited for the shared scan lock")

    monkeypatch.setattr(services, "lock_vrf", blocked)
    response = admin_client.put(f"/api/v1/vlans/{vid}", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["network_type"] == "public"
    with sf() as db:
        assert db.get(m.VLAN, vid).network_type == "public"
        assert db.get(m.IPAddress, network[2]) is not None


def test_vlan_cidr_change_still_takes_vrf_lock(admin_client, network, monkeypatch):
    sf, vid, _, _ = network
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        payload = {key: getattr(vlan, key) for key in schemas.VLANInput.model_fields}
    payload["cidr"] = "192.0.2.0/25"
    calls = []
    original = services.lock_vrf

    def tracked(db, vrf):
        calls.append(vrf)
        return original(db, vrf)

    monkeypatch.setattr(services, "lock_vrf", tracked)
    response = admin_client.put(f"/api/v1/vlans/{vid}", json=payload)
    assert response.status_code == 200, response.text
    assert calls == [payload["vrf_id"]]
