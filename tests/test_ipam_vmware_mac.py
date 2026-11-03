"""Verified VMware IP/NIC identity supplies coherent display fields."""

import json
from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.identity.security import encrypt
from netrix.ipam import adapters, jobs, service
from test_ipam_source_contract import MAC, read
from test_ipam_source_contract import network as network

VM_MAC = "00:50:56:a0:42:c0"


def record(**changes):
    return {
        "hostname": "DNS.EXAMPLE.",
        "address": "192.0.2.10",
        "vm_id": "vm-1",
        "nic_key": "4000",
        "mac_address": VM_MAC,
        "operating_system": "Ubuntu",
        "dvswitch_name": "VM-DS",
        "dvport": "89",
        **changes,
    }


def test_vm_mac_comes_from_the_same_hardware_card_as_the_port():
    from types import SimpleNamespace

    from pyVmomi import vim

    card = vim.vm.device.VirtualVmxnet3(
        key=4000,
        macAddress=VM_MAC,
        backing=vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
            port=vim.dvs.PortConnection(switchUuid="uuid-1", portKey="89")
        ),
    )
    guest = SimpleNamespace(
        hostName="dns.example",
        net=[SimpleNamespace(deviceConfigId=4000, macAddress=MAC, ipAddress=["192.0.2.10"])],
    )
    rows = adapters.vm_records("vm-1", {"guest": guest, "config.hardware.device": [card]})
    assert rows[0]["mac_address"] == VM_MAC and rows[0]["dvport"] == "89"


@pytest.mark.parametrize(
    "records,expected",
    [
        ([record()], VM_MAC),
        ([record(hostname="other.example")], ""),
        ([record(hostname="dns")], ""),
        ([record(mac_address="invalid")], ""),
        ([record(), record(vm_id="vm-2")], ""),
        ([record(), record(nic_key="4001", address="192.0.2.11", mac_address=MAC)], VM_MAC),
        ([record(address=""), record(nic_key="4001", address="", mac_address=MAC)], MAC),
        ([record(address=""), record(nic_key="4001", address="", mac_address="00:11:22:33:44:99")], ""),
        ([record(), record(nic_key="4001", mac_address=MAC)], ""),
        ([record(), record(mac_address=MAC)], ""),
        ([record(integration_id="one"), record(integration_id="two")], ""),
    ],
)
def test_hostname_and_card_selection(records, expected):
    selected = service.hostname_vm_records(records, "dns.example", "192.0.2.10", MAC)
    assert (service.normalized_mac(selected[0]["mac_address"]) if selected else "") == expected


def add_vm(db, vlan, row, **changes):
    data = record(**changes)
    data.pop("address")
    service.observe(db, vlan, row.address, "vcenter", "vc:" + data["vm_id"] + ":" + data["nic_key"], data)


def test_vmware_mac_overrides_gateway_and_keeps_same_nic_port(network):
    sf, vlan_id, row_id, _ = network
    with sf() as db:
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        add_vm(db, vlan, row)
        add_vm(db, vlan, row, hostname="unrelated.example", vm_id="old", mac_address=MAC, dvport="wrong")
        db.commit()
        for details in (True, False):
            item = service.enrich(db, [row], details=details, include_options=True)[0]
            assert item["hostname"] == "dns.example"
            assert item["mac_address"] == VM_MAC
            assert item["field_sources"]["mac_address"] == "vcenter"
            assert item["operating_system"] == "Ubuntu"
            assert item["connected_device"] == "VM-DS" and item["connected_port"] == "89"
            assert item["connection_groups"] == []
        assert jobs.connection_options(db, row)["vm_conflict"] is False


@pytest.mark.parametrize(
    "age,present,name", [(25, True, "dns.example"), (0, False, "dns.example"), (0, True, "other.example")]
)
def test_unverified_vm_does_not_replace_gateway(network, age, present, name):
    sf, vlan_id, row_id, _ = network
    with sf() as db:
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        add_vm(db, vlan, row, hostname=name, present=present)
        for obs in service.observations(db, [row])[row.id]:
            if obs.source == "vcenter":
                obs.observed_at = now() - timedelta(hours=age)
        db.commit()
    item = read(network)
    assert item["mac_address"] == MAC and item["field_sources"]["mac_address"] == "gateway"
    assert item["connected_device"] == "Access" and item["connected_port"] == "Gi1/0/1"


def test_vm_mac_never_retains_gateway_fdb_port(network):
    sf, vlan_id, row_id, _ = network
    with sf() as db:
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        add_vm(db, vlan, row, vm_id="vm-1", dvport="", dvswitch_name="", nic_key="4000")
        # It is a VM, but has no proven virtual port. Never keep the old physical hop.
        db.commit()
    item = read(network)
    assert item["mac_address"] == VM_MAC and item["connected_port"] == ""


@pytest.mark.parametrize("duplicate", [False, True])
@pytest.mark.parametrize("guest_address", ["", "192.0.2.10"])
async def test_sync_matches_hostname_without_guest_ip_and_retires_removed_vm(
    network, monkeypatch, duplicate, guest_address
):
    from sqlalchemy import func, select

    sf, vlan_id, row_id, _ = network
    with sf() as db:
        config = m.Integration(
            name="VC",
            kind="vcenter",
            host="vc.test",
            port=443,
            enabled=True,
            encrypted_secret=encrypt(json.dumps({"username": "fixture", "password": "fixture"})),
        )
        db.add(config)
        db.flush()
        job = m.Job(kind="integration", target_id=config.id)
        db.add(job)
        db.commit()
        job_id = job.id
    records = [record(address=guest_address)]
    if duplicate:
        records.append(record(address=guest_address, vm_id="vm-2"))
    monkeypatch.setattr(adapters, "vcenter_records", lambda *_: records)
    await jobs.integration(job_id)
    item = read(network)
    assert item["mac_address"] == (MAC if duplicate else VM_MAC)
    assert item["field_sources"]["mac_address"] == ("gateway" if duplicate else "vcenter")
    if not duplicate:
        assert item["connected_device"] == "VM-DS" and item["connected_port"] == "89"
    with sf() as db:
        changes = db.scalar(select(func.count()).select_from(m.Event))
    await jobs.integration(job_id)
    with sf() as db:
        assert db.scalar(select(func.count()).select_from(m.Event)) == changes
    monkeypatch.setattr(adapters, "vcenter_records", lambda *_: [])
    await jobs.integration(job_id)
    assert read(network)["mac_address"] == MAC


def test_verified_vm_mac_works_without_gateway(network):
    from sqlalchemy import delete

    sf, vlan_id, row_id, device_ids = network
    with sf() as db:
        db.execute(delete(m.Observation).where(m.Observation.device_id == device_ids[0]))
        add_vm(db, db.get(m.VLAN, vlan_id), db.get(m.IPAddress, row_id))
        db.commit()
    item = read(network)
    assert item["mac_address"] == VM_MAC and item["field_sources"]["mac_address"] == "vcenter"
    assert item["connected_device"] == "VM-DS" and item["connected_port"] == "89"


def test_direct_guest_ip_mac_is_visible_despite_different_dns_and_vm_names(network, admin_client):
    from netrix.ipam import table
    from sqlalchemy import delete

    sf, vlan_id, row_id, ids = network
    with sf() as db:
        db.execute(delete(m.Observation).where(m.Observation.device_id == ids[0]))
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        add_vm(db, vlan, row, hostname="VM-INVENTORY-NAME", guest_address=row.address)
        db.commit()
        for details in (True, False):
            item = service.enrich(db, [row], details=details)[0]
            assert item["hostname"] == "dns.example"
            assert item["mac_address"] == item["automatic_mac_address"] == VM_MAC
            assert item["field_sources"]["mac_address"] == "vcenter"
            assert item["operating_system"] == "Ubuntu"
            assert item["connected_device"] == "VM-DS" and item["connected_port"] == "89"
        assert table.addresses(db, vlan, q=VM_MAC)["items"][0]["mac_address"] == VM_MAC
    detail = admin_client.get(f"/api/v1/ipam/addresses/{row_id}").json()
    listed = admin_client.get(f"/api/v1/ipam/vlans/{vlan_id}/addresses", params={"q": VM_MAC}).json()
    assert detail["mac_address"] == listed["items"][0]["mac_address"] == VM_MAC
    filtered = admin_client.get(
        f"/api/v1/ipam/vlans/{vlan_id}/addresses",
        params={"filters": json.dumps([{"field": "mac_address", "op": "eq", "value": VM_MAC}])},
    ).json()
    assert [item["id"] for item in filtered["items"]] == [row_id]


@pytest.mark.parametrize(
    "fault",
    [
        "other_vm",
        "other_nic",
        "conflicting_mac",
        "old",
        "gone",
        "inferred",
        "missing",
        "invalid",
        "gateway_conflict",
    ],
)
def test_direct_guest_ip_mac_requires_unique_current_uncontested_nic(network, fault):
    from sqlalchemy import delete, select

    sf, vlan_id, row_id, ids = network
    with sf() as db:
        if fault != "gateway_conflict":
            db.execute(delete(m.Observation).where(m.Observation.device_id == ids[0]))
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        changes = {"hostname": "VM-INVENTORY-NAME", "guest_address": row.address}
        if fault == "gone":
            changes["present"] = False
        elif fault == "inferred":
            changes.update(guest_address="192.0.2.11", matched_by="dhcp_mac")
        elif fault == "missing":
            changes.pop("guest_address")
        elif fault == "invalid":
            changes["mac_address"] = "invalid"
        add_vm(db, vlan, row, **changes)
        if fault in ("other_vm", "other_nic", "conflicting_mac"):
            other = record(**changes)
            other.pop("address")
            if fault == "other_vm":
                other.update(vm_id="vm-2", hostname="OTHER-VM")
            elif fault == "other_nic":
                other.update(nic_key="4001")
            else:
                other.update(mac_address=MAC)
            service.observe(db, vlan, row.address, "vcenter", "conflicting-evidence", other)
        if fault == "old":
            db.scalar(select(m.IPObservation).where(m.IPObservation.source == "vcenter")).observed_at = (
                now() - timedelta(hours=25)
            )
        db.commit()
    assert read(network)["mac_address"] == (MAC if fault == "gateway_conflict" else "")


def test_direct_guest_ip_selects_its_card_in_multi_nic_vm(network):
    from sqlalchemy import delete

    sf, vlan_id, row_id, ids = network
    with sf() as db:
        db.execute(delete(m.Observation).where(m.Observation.device_id == ids[0]))
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        add_vm(db, vlan, row, hostname="VM-INVENTORY-NAME", guest_address=row.address)
        add_vm(
            db,
            vlan,
            row,
            hostname="VM-INVENTORY-NAME",
            nic_key="4001",
            guest_address="192.0.2.11",
            mac_address=MAC,
            dvport="90",
        )
        db.commit()
    item = read(network)
    assert item["mac_address"] == VM_MAC and item["connected_port"] == "89"


@pytest.mark.asyncio
@pytest.mark.parametrize("dns_name", ["dns.example", ""])
async def test_future_vmware_snapshot_supplies_mac_with_different_dns_name(network, monkeypatch, dns_name):
    from sqlalchemy import delete

    sf, _, _, ids = network
    with sf() as db:
        db.execute(delete(m.Observation).where(m.Observation.device_id == ids[0]))
        if not dns_name:
            db.execute(delete(m.IPObservation).where(m.IPObservation.source == "dns"))
        config = m.Integration(
            name="VC",
            kind="vcenter",
            host="vc.test",
            port=443,
            enabled=True,
            encrypted_secret=encrypt(json.dumps({"username": "fixture", "password": "fixture"})),
        )
        db.add(config)
        db.flush()
        job = m.Job(kind="integration", target_id=config.id)
        db.add(job)
        db.commit()
        job_id = job.id
    records = [record(hostname="VM-INVENTORY-NAME")]
    monkeypatch.setattr(adapters, "vcenter_records", lambda *_: records)
    await jobs.integration(job_id)
    item = read(network)
    assert item["hostname"] == (dns_name or "VM-INVENTORY-NAME") and item["mac_address"] == VM_MAC
    assert item["connected_device"] == "VM-DS" and item["connected_port"] == "89"
    records.clear()
    await jobs.integration(job_id)
    assert read(network)["mac_address"] == ""
    assert read(network)["hostname"] == dns_name


@pytest.mark.parametrize("dns_state", ["absent", "negative", "expired"])
def test_proven_vmware_name_fills_missing_dns_in_list_detail_search_and_filter(
    network, admin_client, dns_state
):
    from sqlalchemy import delete, select

    sf, vlan_id, row_id, ids = network
    with sf() as db:
        db.execute(delete(m.Observation).where(m.Observation.device_id == ids[0]))
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        dns = db.scalar(select(m.IPObservation).where(m.IPObservation.source == "dns"))
        if dns_state == "absent":
            db.delete(dns)
        elif dns_state == "negative":
            dns.data = {"hostname": "", "present": False}
        else:
            dns.observed_at = now() - timedelta(hours=25)
        add_vm(
            db,
            vlan,
            row,
            hostname="SV-CN-02-02.fbu.edu.tr",
            guest_address=row.address,
            operating_system="Windows Server 2025",
        )
        db.commit()
    detail = admin_client.get(f"/api/v1/ipam/addresses/{row_id}").json()
    expected = {
        "hostname": "SV-CN-02-02.fbu.edu.tr",
        "mac_address": VM_MAC,
        "operating_system": "Windows Server 2025",
    }
    assert all(detail[key] == value for key, value in expected.items())
    assert detail["field_sources"] == {key: "vcenter" for key in expected}
    assert detail["managed"]["hostname"] == ""
    for params in (
        {"q": expected["hostname"]},
        {"filters": json.dumps([{"field": "hostname", "op": "eq", "value": expected["hostname"]}])},
    ):
        listed = admin_client.get(f"/api/v1/ipam/vlans/{vlan_id}/addresses", params=params).json()
        assert len(listed["items"]) == 1
        assert all(listed["items"][0][key] == value for key, value in expected.items())
    with sf() as db:
        row = db.get(m.IPAddress, row_id)
        row.hostname = "manual.example"
        db.commit()
        item = service.enrich(db, [row])[0]
        assert item["hostname"] == "manual.example" and item["field_sources"]["hostname"] == "manual"
        row.hostname = ""
        service.observe(
            db, db.get(m.VLAN, vlan_id), row.address, "dns", "system", {"hostname": "restored.example"}
        )
        db.commit()
        item = service.enrich(db, [row])[0]
        assert item["hostname"] == "restored.example" and item["field_sources"]["hostname"] == "dns"


@pytest.mark.parametrize(
    "fault", ["inferred", "duplicate", "stale", "gone", "gateway_conflict", "name_conflict"]
)
def test_missing_dns_does_not_allow_unproven_or_conflicting_vmware_name(network, fault):
    from sqlalchemy import delete, select

    sf, vlan_id, row_id, ids = network
    with sf() as db:
        if fault != "gateway_conflict":
            db.execute(delete(m.Observation).where(m.Observation.device_id == ids[0]))
        db.execute(delete(m.IPObservation).where(m.IPObservation.source == "dns"))
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        data = record(hostname="VM-NAME", guest_address=row.address, integration_id="vc")
        data.pop("address")
        if fault == "inferred":
            data.update(guest_address="192.0.2.11", matched_by="dhcp_mac")
        elif fault == "gone":
            data["present"] = False
        service.observe(db, vlan, row.address, "vcenter", "vc:first", data)
        if fault in ("duplicate", "name_conflict"):
            second = {**data, "hostname": "OTHER-NAME"}
            if fault == "duplicate":
                second["vm_id"] = "vm-2"
            service.observe(db, vlan, row.address, "vcenter", "vc:second", second)
        if fault == "stale":
            db.scalar(select(m.IPObservation).where(m.IPObservation.source == "vcenter")).observed_at = (
                now() - timedelta(hours=25)
            )
        db.commit()
    assert read(network)["hostname"] == ""


def test_switch_fdb_is_resolved_using_selected_vm_mac(network):
    from netrix.ipam.connections import Evidence
    from sqlalchemy import select

    sf, vlan_id, row_id, device_ids = network
    with sf() as db:
        row, vlan = db.get(m.IPAddress, row_id), db.get(m.VLAN, vlan_id)
        switch = db.scalar(select(m.Observation).where(m.Observation.device_id == device_ids[1]))
        data = dict(switch.evidence)
        tables = dict(data["tables"])
        suffix = ".".join(str(int(octet, 16)) for octet in VM_MAC.split(":"))
        tables["vlan_fdb_port"] = {"700." + suffix: "9"}
        tables["vlan_fdb_status"] = {"700." + suffix: "3"}
        switch.evidence = {**data, "tables": tables}
        db.commit()
        evidence = Evidence(db, {row.vrf_id})
        assert evidence.resolve(row, vlan)["connected_port"] == ""
        item = evidence.resolve(row, vlan, identity_mac=VM_MAC, identity_source="vcenter")
        assert item["connected_device"] == "Access" and item["connected_port"] == "Gi1/0/1"
        assert item["connections"][0]["source"] == "vcenter+vlan_fdb"
        assert item["gateway_evidence"][0]["mac_address"] == MAC
