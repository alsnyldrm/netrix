"""Saved manual metadata is visible without becoming automatic identity evidence."""

import json

import pytest
from netrix import models as m
from sqlalchemy import select
from test_ipam_source_contract import MAC, read
from test_ipam_source_contract import network as network
from test_ipam_vmware_mac import VM_MAC, add_vm


def test_manual_save_list_detail_search_and_clear(network, admin_client):
    sf, vlan_id, row_id, _ = network
    c = admin_client
    detail = c.get(f"/api/v1/addresses/{row_id}").json()
    payload = {k: detail[k] for k in ("address", "vrf_id", "vlan_id", "status")}
    payload.update(hostname="FG-FW-GW-01", operating_system="FortiOS", cabinet="02")
    assert c.put(f"/api/v1/addresses/{row_id}", json=payload).status_code == 200
    url = f"/api/v1/ipam/vlans/{vlan_id}/addresses"
    for params in (
        {"allocated": True},
        {"q": "FG-FW-GW-01 FortiOS"},
        {"filters": json.dumps([{"field": "hostname", "op": "eq", "value": "FG-FW-GW-01"}])},
    ):
        items = c.get(url, params=params).json()["items"]
        row = next(r for r in items if r["id"] == row_id)
        assert row["hostname"] == payload["hostname"]
        assert row["operating_system"] == "FortiOS"
        assert row["cabinet"] == "02"
        assert row["field_sources"]["hostname"] == "manual"
    row = c.get(f"/api/v1/ipam/addresses/{row_id}").json()
    assert row["hostname"] == "FG-FW-GW-01"
    with sf() as db:
        original = db.scalar(select(m.IPObservation).where(m.IPObservation.source == "dns"))
        assert original.data["hostname"] == "dns.example"
    payload.update(hostname="", operating_system="")
    assert c.put(f"/api/v1/addresses/{row_id}", json=payload).status_code == 200
    row = c.get(f"/api/v1/ipam/addresses/{row_id}").json()
    assert row["hostname"] == "dns.example" and row["field_sources"]["hostname"] == "dns"
    assert row["operating_system"] == ""


@pytest.mark.parametrize("vm_hostname,expected_mac", [("dns.example", VM_MAC), ("manual.example", MAC)])
def test_display_name_never_substitutes_for_dns_in_vm_identity(network, vm_hostname, expected_mac):
    sf, vlan_id, row_id, _ = network
    with sf() as db:
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        row.hostname = "manual.example"
        add_vm(db, vlan, row, hostname=vm_hostname)
        db.commit()
    row = read(network)
    assert row["hostname"] == "manual.example" and row["mac_address"] == expected_mac
    assert row["field_sources"]["hostname"] == "manual"
    if expected_mac == VM_MAC:
        assert row["connected_device"] == "VM-DS" and row["connected_port"] == "89"
