from netrix import models as m
from netrix import schemas
from test_ipam_source_contract import network as network


def test_public_description_roundtrip_column_search_and_edit(admin_client, network):
    sf, vid, _, _ = network
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        vlan.network_type = "public"
        vrf = vlan.vrf_id
        db.commit()
    payload = dict(address="192.0.2.22", vrf_id=vrf, vlan_id=vid, description="Turkcell yedek devre")
    response = admin_client.post(f"/api/v1/ipam/vlans/{vid}/addresses", json=payload)
    assert response.status_code == 201, response.text
    rid = response.json()["id"]
    assert response.json()["description"] == payload["description"]
    listing = admin_client.get(f"/api/v1/ipam/vlans/{vid}/addresses?active_only=true&q=yedek").json()
    assert listing["total"] == "1"
    assert listing["items"][0]["description"] == payload["description"]
    assert "description" in {c["key"] for c in listing["columns"]}
    with sf() as db:
        row = db.get(m.IPAddress, rid)
        edited = {key: getattr(row, key) for key in schemas.IPInput.model_fields}
    edited["description"] = "Yeni açıklama"
    response = admin_client.put(f"/api/v1/addresses/{rid}", json=edited)
    assert response.status_code == 200, response.text
    edited.pop("description")
    response = admin_client.put(f"/api/v1/addresses/{rid}", json=edited)
    assert response.status_code == 200
    assert response.json()["description"] == "Yeni açıklama"
    edited["description"] = ""
    response = admin_client.put(f"/api/v1/addresses/{rid}", json=edited)
    assert response.json()["description"] == ""


def test_local_does_not_offer_description_column(admin_client, network):
    _, vid, _, _ = network
    response = admin_client.get(f"/api/v1/ipam/vlans/{vid}/addresses").json()
    assert "description" not in {c["key"] for c in response["columns"]}


def test_reassign_without_description_preserves_existing_text(admin_client, network):
    sf, vid, rid, _ = network
    with sf() as db:
        row = db.get(m.IPAddress, rid)
        row.description = "Korunacak açıklama"
        address, vrf = row.address, row.vrf_id
        db.commit()
    response = admin_client.post(f"/api/v1/ipam/vlans/{vid}/addresses", json={
        "address": address, "vrf_id": vrf, "vlan_id": vid, "status": "active",
    })
    assert response.status_code == 201, response.text
    assert response.json()["description"] == "Korunacak açıklama"
