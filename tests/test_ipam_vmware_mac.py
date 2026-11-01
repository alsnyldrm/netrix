"""Hostname-verified VMware MAC priority without mixing NIC or port identities."""

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
