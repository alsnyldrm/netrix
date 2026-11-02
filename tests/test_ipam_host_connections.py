"""Fresh IPAM neighbors and VMware-owned physical NICs, never name guesses."""

from copy import deepcopy
from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.ipam import service
from sqlalchemy import delete, select
from test_ipam_source_contract import MAC, read
from test_ipam_source_contract import network as network

NIC1 = "00:11:22:aa:00:01"
NIC2 = "00:11:22:aa:00:02"
HOST_UUID = "0461e729-cc05-4eaa-a3a3-e56b01347891"


@pytest.fixture(autouse=True)
def no_unrelated_fdb(network):
    sf, _, _, ids = network
    with sf() as db:
        for id in ids[1:]:
            obs = db.scalar(select(m.Observation).where(m.Observation.device_id == id))
            obs.evidence = {**obs.evidence, "tables": {}}
        db.execute(delete(m.Link))
        db.commit()


def neighbor(port, nic_mac, nic="vmnic0", **changes):
    return {
        "interface_name": port,
        "remote_name": "esxi.example.test",
        "remote_port": nic,
        "source": "lldp",
        "evidence": {"lldp": {"port_subtype": 3, "port_id": nic_mac}},
        **changes,
    }


def host_data(**changes):
    return {
        "record_type": "host",
        "host_id": "host-1",
        "host_uuid": HOST_UUID,
        "hostname": "esxi.example.test",
        "host_address": "192.0.2.10",
        "mac_address": MAC,
        "vmkernel_device": "vmk0",
        "physical_nics": [
            {"device": "vmnic0", "mac_address": NIC1, "link_up": True},
            {"device": "vmnic1", "mac_address": NIC2, "link_up": True},
        ],
        "operating_system": "VMware ESXi 8.0",
        **changes,
    }


def snapshot(db, device_id, neighbors, interfaces=None):
    obs = db.scalar(select(m.Observation).where(m.Observation.device_id == device_id))
    data = deepcopy(obs.evidence)
    data["neighbors"] = neighbors
    data["interfaces"] = interfaces or [
        {"if_index": 101, "name": "A1", "oper_status": "up"},
        {"if_index": 102, "name": "B2", "oper_status": "up"},
    ]
    obs.evidence = data
    return obs


def add_host(db, vlan_id, row_id, **changes):
    row = db.get(m.IPAddress, row_id)
    service.observe(
        db, db.get(m.VLAN, vlan_id), row.address, "vcenter", "vc:host:host-1:vmk0", host_data(**changes)
    )


def test_fresh_raw_neighbor_resolves_ip_even_when_directory_is_stale(network):
    sf, _, _, ids = network
    with sf() as db:
        db.execute(delete(m.Link))
        n = neighbor("A1", MAC)
        n["evidence"]["lldp"]["management_address"] = "192.0.2.10"
        snapshot(db, ids[1], [n])
        db.add(
            m.Link(
                device_id=ids[1],
                interface_name="A1",
                remote_name="old label",
                remote_port="eth0",
                source="lldp",
                last_seen_at=now() - timedelta(days=2),
            )
        )
        db.commit()
    item = read(network)
    assert item["connected_device"] == "Access" and item["connected_port"] == "A1"


@pytest.mark.parametrize("two_switches", [False, True])
def test_vmware_host_multiple_mac_nics_preserve_all_switch_port_pairs(network, two_switches):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        db.execute(delete(m.Link))
        add_host(db, vlan_id, row_id)
        snapshot(db, ids[1], [neighbor("A1", NIC1)])
        other = ids[2] if two_switches else ids[1]
        if two_switches:
            snapshot(db, other, [neighbor("B2", NIC2, "vmnic1")])
        else:
            snapshot(db, other, [neighbor("A1", NIC1), neighbor("B2", NIC2, "vmnic1")])
        db.commit()
    item = read(network)
    assert not item["connection_ambiguous"]
    expected = [("Access", "A1"), ("Core", "B2")] if two_switches else [("Access", "A1 - B2")]
    assert [(g["device_name"], g["port_label"]) for g in item["connection_groups"]] == expected
    assert item["mac_address"] == MAC and item["cabinet"] != "Sanal"
    assert item["operating_system"] == "VMware ESXi 8.0"


@pytest.mark.parametrize("fault", ["stale_host", "removed_host", "wrong_ip", "wrong_mac", "down_nic"])
def test_unverified_host_cannot_join_independent_nic_macs(network, fault):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        db.execute(delete(m.Link))
        changes = {}
        if fault == "removed_host":
            changes["present"] = False
        if fault == "wrong_ip":
            changes["host_address"] = "192.0.2.99"
        if fault == "wrong_mac":
            changes["mac_address"] = "00:11:22:cc:cc:cc"
        if fault == "down_nic":
            changes["physical_nics"] = [{"device": "vmnic0", "mac_address": NIC1, "link_up": False}]
        add_host(db, vlan_id, row_id, **changes)
        if fault == "stale_host":
            db.scalar(select(m.IPObservation).where(m.IPObservation.source == "vcenter")).observed_at = (
                now() - timedelta(days=2)
            )
        snapshot(db, ids[1], [neighbor("A1", NIC1)])
        snapshot(db, ids[2], [neighbor("B2", NIC2, "vmnic1")])
        db.commit()
    assert read(network)["connected_port"] == ""


def test_raw_management_ip_neighbor_conflict_is_not_treated_as_a_second_nic(network):
    sf, _, _, ids = network
    with sf() as db:
        db.execute(delete(m.Link))
        n = neighbor("A1", NIC1)
        n["evidence"]["lldp"]["management_address"] = "192.0.2.10"
        snapshot(db, ids[1], [n])
        db.commit()
    item = read(network)
    assert item["connection_ambiguous"] and not item["connected_port"]


@pytest.mark.parametrize("fault", ["down", "stale", "failed", "excluded", "newer_empty"])
def test_raw_neighbor_is_current_and_respects_user_exclusions(network, fault):
    sf, _, _, ids = network
    with sf() as db:
        n = neighbor("A1", MAC)
        n["evidence"]["lldp"]["management_address"] = "192.0.2.10"
        obs = snapshot(db, ids[1], [n])
        if fault == "down":
            obs.evidence = {
                **obs.evidence,
                "interfaces": [{"if_index": 101, "name": "A1", "oper_status": "down"}],
            }
        if fault == "stale":
            obs.created_at = now() - timedelta(days=2)
        if fault in {"failed", "newer_empty"}:
            job = m.Job(kind="ipam_discover", target_id=network[1])
            db.add(job)
            db.flush()
            db.add(
                m.Observation(
                    device_id=ids[1],
                    address=db.get(m.Device, ids[1]).management_ip,
                    job_id=job.id,
                    source="ipam_network",
                    evidence={"failed": True}
                    if fault == "failed"
                    else {"neighbors": [], "neighbor_protocols_complete": ["lldp", "cdp"]},
                    created_at=now() + timedelta(seconds=1),
                )
            )
        if fault == "excluded":
            db.add(
                m.Link(
                    device_id=ids[1],
                    interface_name="A1",
                    remote_name=n["remote_name"],
                    remote_port=n["remote_port"],
                    source="lldp",
                    evidence=n["evidence"],
                    auto_add_excluded=True,
                    is_current=False,
                    last_seen_at=now(),
                )
            )
        db.commit()
    assert not read(network)["connected_port"]


def test_duplicate_location_for_one_physical_nic_is_not_a_dual_connection(network):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        add_host(db, vlan_id, row_id)
        snapshot(db, ids[1], [neighbor("A1", NIC1)])
        snapshot(db, ids[2], [neighbor("B2", NIC1)])
        db.commit()
    item = read(network)
    assert item["connection_ambiguous"] and not item["connected_port"]


def test_typed_host_chassis_and_second_nic_name_can_complete_pair(network):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        add_host(db, vlan_id, row_id)
        n = neighbor("B2", NIC2, "vmnic1")
        n["evidence"] = {
            "lldp": {
                "chassis_subtype": 7,
                "chassis_id": "esxi.example.test",
                "port_subtype": 7,
                "port_id": "vmnic1",
            }
        }
        snapshot(db, ids[1], [neighbor("A1", NIC1), n])
        db.commit()
    assert read(network)["connected_port"] == "A1 - B2"


def test_host_hint_uses_inventory_ip_and_resolves_numeric_port_id(network):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        data = host_data()
        data["physical_nics"][0]["hints"] = [
            {"protocol": "lldp", "addresses": ["198.51.100.2"], "port_id": "101", "port_description": "A1"}
        ]
        add_host(db, vlan_id, row_id, **data)
        snapshot(db, ids[1], [])
        db.commit()
    item = read(network)
    assert item["connected_device"] == "Access" and item["connected_port"] == "A1"


@pytest.mark.parametrize("chassis", ["mac", "uuid"])
def test_non_vmware_multinic_uses_common_protocol_identity(network, chassis):
    sf, _, _, ids = network
    with sf() as db:
        one = neighbor("A1", MAC)
        two = neighbor("B2", NIC2, "eth1")
        for n in (one, two):
            ll = n["evidence"]["lldp"]
            ll.update(
                chassis_subtype=4 if chassis == "mac" else 7,
                chassis_id=MAC if chassis == "mac" else HOST_UUID,
                management_address="192.0.2.10",
            )
        snapshot(db, ids[1], [one])
        snapshot(db, ids[2], [two])
        db.commit()
    item = read(network)
    assert not item["connection_ambiguous"]
    assert [(g["device_name"], g["port_label"]) for g in item["connection_groups"]] == [
        ("Access", "A1"),
        ("Core", "B2"),
    ]


@pytest.mark.parametrize("fault", ["duplicate_host", "wrong_vrf", "newer_failed_switch", "untyped_name"])
def test_host_hints_and_nic_ownership_fail_closed(network, fault):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        data = host_data()
        data["physical_nics"][0]["hints"] = [
            {"protocol": "lldp", "addresses": ["198.51.100.2"], "port_id": "101", "port_description": "A1"}
        ]
        if fault == "untyped_name":
            data["physical_nics"][0]["hints"] = []
        add_host(db, vlan_id, row_id, **data)
        if fault == "duplicate_host":
            service.observe(
                db,
                db.get(m.VLAN, vlan_id),
                "192.0.2.10",
                "vcenter",
                "other:host-2",
                host_data(host_id="host-2"),
            )
        n = neighbor("A1", NIC1)
        if fault == "untyped_name":
            n["evidence"] = {
                "lldp": {"system_name": "esxi.example.test", "port_subtype": 7, "port_id": "vmnic0"}
            }
        obs = snapshot(db, ids[1], [n])
        if fault == "newer_failed_switch":
            obs.evidence = {"failed": True}
        if fault == "wrong_vrf":
            vrf = m.VRF(name="Other")
            db.add(vrf)
            db.flush()
            db.get(m.Device, ids[1]).vrf_id = vrf.id
        db.commit()
    assert not read(network)["connected_port"]


def test_independent_vmware_hint_does_not_restore_deleted_directory_links(network):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        data = host_data()
        data["physical_nics"][0]["hints"] = [
            {"protocol": "lldp", "addresses": ["198.51.100.2"], "port_id": "101", "port_description": "A1"}
        ]
        add_host(db, vlan_id, row_id, **data)
        n = neighbor("A1", NIC1)
        snapshot(db, ids[1], [n])
        link = m.Link(
            device_id=ids[1],
            interface_name="A1",
            remote_name=n["remote_name"],
            remote_port=n["remote_port"],
            source="lldp",
            evidence=n["evidence"],
            auto_add_excluded=True,
            is_current=False,
        )
        db.add(link)
        db.commit()
        link_id = link.id
    item = read(network)
    assert item["connected_port"] == "A1" and item["connections"][0]["source"] == "vcenter_host+lldp"
    with sf() as db:
        link = db.get(m.Link, link_id)
        assert link.auto_add_excluded and not link.is_current


def test_host_keeps_both_physical_nics_and_marks_its_ip_network_separately(network):
    sf, vlan_id, row_id, ids = network
    with sf() as db:
        add_host(db, vlan_id, row_id, uplink_nics=["vmnic1"])
        snapshot(db, ids[1], [neighbor("A1", NIC1), neighbor("B2", NIC2, "vmnic1")])
        db.commit()
    assert read(network)["connected_port"] == "A1 - B2"


async def test_host_sync_is_separate_from_vms_and_retires_removed_hosts(network, monkeypatch):
    from netrix.identity.security import encrypt
    from netrix.ipam import adapters, jobs

    sf, vlan_id, row_id, ids = network
    with sf() as db:
        config = m.Integration(
            name="VC",
            kind="vcenter",
            host="vc.test",
            port=443,
            enabled=True,
            encrypted_secret=encrypt('{"username":"fixture","password":"fixture"}'),
        )
        db.add(config)
        db.flush()
        job = m.Job(kind="integration", target_id=config.id)
        db.add(job)
        db.commit()
        job_id = job.id
        before = [(d.id, d.name) for d in db.scalars(select(m.Device))]
    records = [{**host_data(), "address": "192.0.2.10"}]
    monkeypatch.setattr(adapters, "vcenter_records", lambda *_: records)
    await jobs.integration(job_id)
    with sf() as db:
        obs = db.scalar(select(m.IPObservation).where(m.IPObservation.source == "vcenter"))
        assert obs.data["host_id"] == "host-1" and ":host:host-1:vmk0" in obs.source_key
        assert before == [(d.id, d.name) for d in db.scalars(select(m.Device))]
        assert service.virtual_connections([obs]) == []
    records.clear()
    await jobs.integration(job_id)
    with sf() as db:
        assert (
            db.scalar(select(m.IPObservation).where(m.IPObservation.source == "vcenter")).data["present"]
            is False
        )
