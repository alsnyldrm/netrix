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


def test_selected_room_and_manual_connection_remain_explicit_metadata(network, admin_client, institution):
    from test_ipam_hierarchy import site

    sf, vlan_id, row_id, devices = network
    c = admin_client
    campus = site(c, institution, name="FBU-F")
    room = site(c, institution, name="Sunucu Odası", parent_id=campus["id"])
    with sf() as db:
        row = db.get(m.IPAddress, row_id)
        row.institution_id, row.site_id, row.sub_site_id = institution["id"], campus["id"], room["id"]
        row.cabinet = "02"
        row.device_id = devices[0]
        interface = m.Interface(device_id=devices[0], name="MANUAL-A2")
        db.add(interface)
        db.flush()
        row.interface_id = interface.id
        db.commit()
    expected = {
        "site_name": "FBU-F",
        "floor_number": "L-0",
        "department_name": "A",
        "room_name": "Sunucu Odası",
        "cabinet_number": "02",
        "start_unit": None,
    }
    for row in (
        read(network),
        c.get(f"/api/v1/ipam/vlans/{vlan_id}/addresses", params={"q": "FBU-F L-0 Sunucu"}).json()["items"][0],
        c.get(f"/api/v1/ipam/addresses/{row_id}").json(),
    ):
        assert row["manual_location"] == expected
        assert row["rack_location"] is None and row["rack_position"] == ""
        assert row["manual_connection"] == {"device_name": "Gateway", "port": "MANUAL-A2"}
        # An explicit selection never supersedes proven automatic links.
        assert row["connected_device"] == "Access" and row["connected_port"] == "Gi1/0/1"
    # A number on its own cannot identify a room or a physical placement.
    with sf() as db:
        row = db.get(m.IPAddress, row_id)
        row.site_id = row.sub_site_id = row.device_id = row.interface_id = None
        db.commit()
    row = read(network)
    assert row["manual_location"] is None and row["manual_connection"] is None
    assert row["cabinet"] == "02"


@pytest.mark.parametrize("ambiguous", [False, True])
def test_manual_connection_is_searchable_without_becoming_automatic(network, admin_client, ambiguous):
    sf, vlan_id, row_id, devices = network
    with sf() as db:
        row = db.get(m.IPAddress, row_id)
        row.device_id = devices[0]
        interface = m.Interface(device_id=devices[0], name="MANUAL-A2")
        db.add(interface)
        db.flush()
        row.interface_id = interface.id
        # No current automatic evidence: manual data must remain separately identified.
        db.query(m.Observation).delete()
        from test_ipam_source_contract import clear_source_facts
        clear_source_facts(db)
        db.query(m.Link).delete()
        if ambiguous:
            result = m.IPAMResult(
                address_id=row.id, scope_address=row.address, scope_vrf=row.vrf_id, scope_vlan=row.vlan_id
            )
            result.issues = [{"source": "switch", "code": "ambiguous", "message": "Conflicting evidence"}]
            db.add(result)
        db.commit()
    response = admin_client.get(f"/api/v1/ipam/vlans/{vlan_id}/addresses", params={"q": "Gateway MANUAL-A2"})
    assert response.status_code == 200
    row = next(r for r in response.json()["items"] if r["id"] == row_id)
    assert row["connected_device"] == "" and row["connected_port"] == ""
    assert bool(row["connection_ambiguous"]) == ambiguous
    assert row["manual_connection"] == {"device_name": "Gateway", "port": "MANUAL-A2"}
    assert row["rack_location"] is None
