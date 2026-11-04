"""Manual MAC metadata never substitutes for automatic VM or port identity."""

import json

import pytest
from netrix import models as m
from netrix import schemas as s
from netrix.ipam.service import observe
from pydantic import ValidationError
from test_ipam_source_contract import MAC, read
from test_ipam_source_contract import network as network

MANUAL = "02:aa:bb:cc:dd:ee"


def payload(c, row_id, **changes):
    row = c.get(f"/api/v1/addresses/{row_id}").json()
    return {**{k: row[k] for k in ("address", "vrf_id", "vlan_id", "status")}, **changes}


def test_manual_mac_save_search_detail_refresh_and_clear(network, admin_client):
    sf, vlan_id, row_id, _ = network
    c = admin_client
    data = payload(c, row_id, mac_address="02-AA-BB-CC-DD-EE")
    response = c.put(f"/api/v1/addresses/{row_id}", json=data)
    assert response.status_code == 200, response.text
    assert response.json()["mac_address"] == MANUAL
    url = f"/api/v1/ipam/vlans/{vlan_id}/addresses"
    for params in (
        {"allocated": True},
        {"q": MANUAL},
        {"filters": json.dumps([{"field": "mac_address", "op": "eq", "value": MANUAL}])},
    ):
        row = next(r for r in c.get(url, params=params).json()["items"] if r["id"] == row_id)
        assert row["mac_address"] == row["managed"]["mac_address"] == MANUAL
        assert row["field_sources"]["mac_address"] == "manual"
        assert row["automatic_mac_address"] == MAC
        assert row["connected_device"] == "Access" and row["connected_port"] == "Gi1/0/1"
    detail = c.get(f"/api/v1/ipam/addresses/{row_id}").json()
    assert detail["mac_address"] == MANUAL and detail["automatic_mac_address"] == MAC
    # Older clients omitting the new field preserve a stored manual MAC.
    legacy = payload(c, row_id, hostname="legacy-name")
    assert c.put(f"/api/v1/addresses/{row_id}", json=legacy).status_code == 200
    assert read(network)["managed"]["mac_address"] == MANUAL
    with sf() as db:
        from sqlalchemy import select

        events = db.scalars(select(m.Event).where(m.Event.kind == "ip_assignment_change")).all()
        assert any(e.details["changes"].get("mac_address", {}).get("current") == MANUAL for e in events)
    # A source refresh leaves the saved override intact.
    with sf() as db:
        observe(db, db.get(m.VLAN, vlan_id), detail["address"], "dns", "system", {"hostname": "dns.example"})
        db.commit()
    assert read(network)["mac_address"] == MANUAL
    data["mac_address"] = ""
    assert c.put(f"/api/v1/addresses/{row_id}", json=data).status_code == 200
    detail = c.get(f"/api/v1/ipam/addresses/{row_id}").json()
    assert detail["mac_address"] == MAC and detail["managed"]["mac_address"] == ""
    assert detail["field_sources"]["mac_address"] == "gateway"
    # Per-device MAC overrides must not be copied to every selected IP.
    response = c.post(
        "/api/v1/ipam/addresses/bulk",
        json={"ids": [row_id], "action": "update", "changes": {"mac_address": MANUAL}},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "value", ["02:AA:BB:CC:DD:EE", "02-AA-BB-CC-DD-EE", "02aa.bbcc.ddee", "02aabbccddee"]
)
def test_mac_input_normalizes_supported_eui48_formats(value):
    assert (
        s.IPInput(address="192.0.2.1", vrf_id="vrf", vlan_id="vlan", mac_address=value).mac_address == MANUAL
    )


@pytest.mark.parametrize(
    "value",
    [
        "00:00:00:00:00:00",
        "ff:ff:ff:ff:ff:ff",
        "01:11:22:33:44:55",
        "not-a-mac",
        "02:aa:bb:cc:dd",
        "02:aa:bb:cc:dd:ee:ff",
        "02::aa:bb:cc:dd:ee",
    ],
)
def test_invalid_mac_is_rejected(value):
    with pytest.raises(ValidationError):
        s.IPInput(address="192.0.2.1", vrf_id="vrf", vlan_id="vlan", mac_address=value)


def test_manual_mac_never_selects_vm_nic_or_creates_connection(network):
    from test_ipam_vmware_mac import VM_MAC, add_vm

    sf, vlan_id, row_id, _ = network
    with sf() as db:
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        row.mac_address = MANUAL
        add_vm(db, vlan, row, hostname="dns.example")
        db.commit()
    row = read(network)
    assert row["mac_address"] == MANUAL and row["automatic_mac_address"] == VM_MAC
    assert row["connected_device"] == "VM-DS" and row["cabinet"] == "Sanal"
    with sf() as db:
        db.query(m.IPObservation).filter(m.IPObservation.source == "vcenter").delete()
        db.query(m.Observation).delete()
        from test_ipam_source_contract import clear_source_facts
        clear_source_facts(db)
        db.query(m.Link).delete()
        db.commit()
    row = read(network)
    assert row["mac_address"] == MANUAL and row["automatic_mac_address"] == ""
    assert row["connected_device"] == row["connected_port"] == ""
