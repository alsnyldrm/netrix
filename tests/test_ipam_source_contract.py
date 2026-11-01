"""The owner's fixed IPAM field-source contract and conservative port resolution."""

from datetime import timedelta

import pytest
from conftest import make_vlan
from netrix import models as m
from netrix.core import now
from netrix.ipam import service

MAC = "00:11:22:33:44:55"
SUFFIX = "0.17.34.51.68.85"


@pytest.fixture
def network(inventory, env):
    with env() as db:
        vlan = make_vlan(vid=20, cidr="192.0.2.0/24", vrf_id=inventory["vrf"]["id"])
        db.add(vlan)
        db.flush()
        row = service.observe(db, vlan, "192.0.2.10", "dns", "system", {"hostname": "dns.example"})
        devices = []
        for i, (name, kind) in enumerate((("Gateway", "firewall"), ("Access", "switch"), ("Core", "switch"))):
            d = m.Device(
                name=name,
                kind=kind,
                management_ip=f"198.51.100.{i + 1}",
                vrf_id=vlan.vrf_id,
                discovery_scope_id=inventory["scope"]["id"],
                snmp_credential_id=inventory["credential"]["id"],
            )
            db.add(d)
            db.flush()
            devices.append(d)
        job = m.Job(kind="ipam_discover", target_id=vlan.id, status="succeeded")
        db.add(job)
        db.flush()
        for device, tables in zip(
            devices,
            [
                {
                    "arp_mac": {"40.192.0.2.10": MAC},
                    "arp_type": {"40.192.0.2.10": "3"},
                    "ip_addr_ifindex": {"192.0.2.1": "40"},
                    "ip_addr_mask": {"192.0.2.1": "255.255.255.0"},
                },
                {
                    "vlan_fdb_id": {"0.20": "700"},
                    "vlan_fdb_port": {"700." + SUFFIX: "9"},
                    "vlan_fdb_status": {"700." + SUFFIX: "3"},
                    "bridge_ifindex": {"9": "101"},
                },
                {
                    "vlan_fdb_id": {"0.20": "900"},
                    "vlan_fdb_port": {"900." + SUFFIX: "3"},
                    "vlan_fdb_status": {"900." + SUFFIX: "3"},
                    "bridge_ifindex": {"3": "101"},
                },
            ],
        ):
            db.add(
                m.Observation(
                    job_id=job.id,
                    device_id=device.id,
                    address=device.management_ip,
                    source="ipam_network",
                    evidence={
                        "ip_forwarding": "1",
                        "tables": tables,
                        "unsupported": [],
                        "interfaces": [{"if_index": 101, "name": "Gi1/0/1", "oper_status": "up"}],
                        "neighbors": [],
                        "neighbor_protocols_complete": ["lldp", "cdp"],
                    },
                )
            )
        db.add(
            m.Link(
                device_id=devices[2].id,
                remote_device_id=devices[1].id,
                remote_name="Access",
                interface_name="Gi1/0/1",
                remote_port="uplink",
                source="lldp",
                last_seen_at=now(),
            )
        )
        db.commit()
        return env, vlan.id, row.id, [d.id for d in devices]


def read(network):
    sf, _, id, _ = network
    with sf() as db:
        return service.enrich(db, [db.get(m.IPAddress, id)])[0]


def test_dns_gateway_vmware_fields_and_terminal_switch_port(network):
    sf, vlan_id, row_id, _ = network
    with sf() as db:
        row = db.get(m.IPAddress, row_id)
        vlan = db.get(m.VLAN, vlan_id)
        row.hostname = "manual-name"
        row.operating_system = "manual-os"
        service.observe(
            db,
            vlan,
            row.address,
            "windows_dhcp",
            "dhcp",
            {"hostname": "dhcp-name", "mac_address": "00:11:22:33:44:99", "operating_system": "wrong"},
        )
        service.observe(
            db,
            vlan,
            row.address,
            "vcenter",
            "vc",
            {"hostname": "vm-name", "operating_system": "Ubuntu", "mac_address": MAC},
        )
        db.commit()
    result = read(network)
    assert result["hostname"] == "dns.example"
    assert result["mac_address"] == MAC and not result["mac_conflict"]
    assert result["operating_system"] == "Ubuntu"
    assert result["connected_device"] == "Access" and result["connected_port"] == "Gi1/0/1"
    assert result["field_sources"] == {
        "hostname": "dns",
        "mac_address": "gateway",
        "operating_system": "vcenter",
    }
    assert result["managed"]["hostname"] == "manual-name"


@pytest.mark.parametrize(
    "fault", ["wrong_vlan", "missing_fid_mapping", "truncated", "down", "stale", "failed", "discovery_only"]
)
def test_unproven_switch_port_is_never_selected(network, fault):
    from sqlalchemy import select

    sf, _, _, ids = network
    with sf() as db:
        observation = db.scalar(select(m.Observation).where(m.Observation.device_id == ids[1]))
        data = dict(observation.evidence)
        tables = dict(data["tables"])
        if fault == "wrong_vlan":
            tables["vlan_fdb_id"] = {"0.99": "700"}
        if fault == "missing_fid_mapping":
            tables.pop("vlan_fdb_id")
        if fault == "truncated":
            data["unsupported"] = ["vlan_fdb_port"]
        if fault == "down":
            data["interfaces"] = [{"if_index": 101, "name": "Gi1/0/1", "oper_status": "down"}]
        if fault == "stale":
            observation.created_at = now() - timedelta(days=2)
        if fault == "failed":
            data = {"failed": True}
        if fault == "discovery_only":
            observation.source = "snmpv3"
        if fault != "failed":
            data["tables"] = tables
        observation.evidence = data
        db.commit()
    assert read(network)["connected_port"] == ""


def test_gateway_conflict_does_not_pick_a_mac_or_port(network):
    from sqlalchemy import select

    sf, _, _, ids = network
    with sf() as db:
        observation = db.scalar(select(m.Observation).where(m.Observation.device_id == ids[0]))
        data = dict(observation.evidence)
        tables = dict(data["tables"])
        tables["ndp_mac"] = {"40.1.4.192.0.2.10": "00:11:22:33:44:99"}
        data["tables"] = tables
        observation.evidence = data
        db.commit()
    row = read(network)
    assert row["mac_conflict"] and row["mac_address"] == "" and row["connected_port"] == ""


def test_current_neighbor_management_ip_resolves_without_mac_or_hostname_guess(network):
    from sqlalchemy import delete

    sf, _, _, ids = network
    with sf() as db:
        db.execute(delete(m.Observation))
        db.add(
            m.Link(
                device_id=ids[1],
                remote_name="unrelated-name",
                remote_port="eth0",
                interface_name="A2",
                source="lldp",
                last_seen_at=now(),
                evidence={"lldp": {"management_address": "192.0.2.10"}},
            )
        )
        db.commit()
    row = read(network)
    assert row["mac_address"] == "" and row["connected_device"] == "Access" and row["connected_port"] == "A2"


def test_no_dns_no_gateway_no_vmware_means_empty_automatic_fields(network):
    from sqlalchemy import delete

    sf, vlan_id, row_id, _ = network
    with sf() as db:
        db.execute(delete(m.Observation))
        db.execute(delete(m.IPObservation))
        row = db.get(m.IPAddress, row_id)
        service.observe(
            db,
            db.get(m.VLAN, vlan_id),
            row.address,
            "windows_dhcp",
            "dhcp",
            {"hostname": "not-dns", "mac_address": MAC, "operating_system": "not-vmware"},
        )
        db.commit()
    row = read(network)
    assert row["hostname"] == row["mac_address"] == row["operating_system"] == ""


def test_multiple_independent_switch_candidates_are_visible_but_never_selected(network):
    from sqlalchemy import delete

    sf, _, _, _ = network
    with sf() as db:
        db.execute(delete(m.Link))
        db.commit()
    row = read(network)
    assert row["connection_ambiguous"]
    assert row["connected_device"] == row["connected_port"] == ""
    assert {c["device_name"] for c in row["connections"]} == {"Access", "Core"}


@pytest.mark.parametrize(
    "fault",
    [
        "multiple_macs",
        "no_neighbor_tables",
        "shared_fid",
        "raw_neighbor_uplink",
        "unknown_uplink",
        "shared_fid_transit",
    ],
)
def test_transit_or_incomplete_switch_evidence_cannot_prove_endpoint(network, fault):
    from copy import deepcopy

    from sqlalchemy import select

    sf, _, _, ids = network
    with sf() as db:
        obs = db.scalar(select(m.Observation).where(m.Observation.device_id == ids[1]))
        data = deepcopy(obs.evidence)
        if fault == "multiple_macs":
            key = "700.0.17.34.51.68.86"
            data["tables"]["vlan_fdb_port"][key] = "9"
            data["tables"]["vlan_fdb_status"][key] = "3"
        if fault == "no_neighbor_tables":
            data["neighbor_protocols_complete"] = []
        if fault == "shared_fid":
            data["tables"]["vlan_fdb_id"]["0.21"] = "700"
        if fault == "raw_neighbor_uplink":
            data["neighbors"] = [{"interface_name": "Gi1/0/1", "remote_name": "bridge"}]
        if fault == "unknown_uplink":
            data["neighbors"] = [{"interface_name": "unresolved-LLDP-port", "remote_name": "bridge"}]
        if fault == "shared_fid_transit":
            data["tables"]["vlan_fdb_id"].update({"0.30": "900", "0.31": "900"})
            data["tables"]["vlan_fdb_port"]["900.0.17.34.51.68.86"] = "9"
            data["tables"]["vlan_fdb_status"]["900.0.17.34.51.68.86"] = "3"
        obs.evidence = data
        db.commit()
    assert read(network)["connected_port"] == ""


@pytest.mark.parametrize(
    "fault", ["wrong_vrf", "archived", "not_inventory", "newer_empty", "changed_management"]
)
def test_gateway_identity_is_scoped_current_and_never_reuses_old_positive(network, fault):
    from sqlalchemy import select

    sf, _, _, ids = network
    with sf() as db:
        device = db.get(m.Device, ids[0])
        if fault == "wrong_vrf":
            vrf = m.VRF(name="Other VRF")
            db.add(vrf)
            db.flush()
            device.vrf_id = vrf.id
        if fault == "archived":
            device.archived = True
        if fault == "not_inventory":
            device.discovery_scope_id = None
        if fault == "changed_management":
            device.management_ip = "198.51.100.99"
        if fault == "newer_empty":
            job = m.Job(kind="ipam_discover", target_id=network[1])
            db.add(job)
            db.flush()
            old = db.scalar(select(m.Observation).where(m.Observation.device_id == device.id))
            db.add(
                m.Observation(
                    job_id=job.id,
                    device_id=device.id,
                    address=device.management_ip,
                    source="ipam_network",
                    evidence={"failed": True},
                    created_at=old.created_at + timedelta(seconds=1),
                )
            )
        db.commit()
    row = read(network)
    assert row["mac_address"] == row["connected_port"] == ""


def test_bonded_nics_require_common_typed_uuid_and_preserve_switch_port_pairs(network):
    from sqlalchemy import delete

    sf, _, _, ids = network
    with sf() as db:
        db.execute(delete(m.Observation))
        db.execute(delete(m.Link))
        for id, port, nic, address in ((ids[1], "A1", "eth0", "192.0.2.10"), (ids[2], "B2", "eth1", "")):
            db.add(
                m.Link(
                    device_id=id,
                    remote_name="server",
                    interface_name=port,
                    remote_port=nic,
                    source="lldp",
                    last_seen_at=now(),
                    evidence={
                        "lldp": {
                            "chassis_subtype": 7,
                            "chassis_id": "0461e729-cc05-4eaa-a3a3-e56b01347891",
                            "management_address": address,
                        }
                    },
                )
            )
        db.commit()
    row = read(network)
    assert not row["connection_ambiguous"]
    assert [(g["device_name"], g["port_label"]) for g in row["connection_groups"]] == [
        ("Access", "A1"),
        ("Core", "B2"),
    ]


@pytest.mark.parametrize("fault", ["deleted", "excluded", "stale", "down"])
def test_neighbor_record_must_still_be_current(network, fault):
    from sqlalchemy import delete, select

    sf, _, _, ids = network
    with sf() as db:
        db.execute(delete(m.Link))
        db.execute(delete(m.Observation).where(m.Observation.device_id != ids[1]))
        link = m.Link(
            device_id=ids[1],
            remote_name="server",
            remote_port="eth0",
            interface_name="Gi1/0/1",
            source="lldp",
            last_seen_at=now(),
            evidence={"lldp": {"management_address": "192.0.2.10"}},
        )
        if fault == "deleted":
            link.is_current = False
        if fault == "excluded":
            link.auto_add_excluded = True
        if fault == "stale":
            link.last_seen_at = now() - timedelta(days=2)
        if fault == "down":
            obs = db.scalar(select(m.Observation).where(m.Observation.device_id == ids[1]))
            obs.evidence = {"interfaces": [{"if_index": 101, "name": "Gi1/0/1", "oper_status": "down"}]}
            obs.created_at = now() + timedelta(seconds=1)
        db.add(link)
        db.commit()
    assert read(network)["connected_port"] == ""


def test_gateway_and_advertised_neighbor_mac_conflict_is_not_hidden(network):
    sf, _, _, ids = network
    with sf() as db:
        db.add(
            m.Link(
                device_id=ids[1],
                remote_name="server",
                interface_name="A1",
                remote_port="eth0",
                source="lldp",
                last_seen_at=now(),
                evidence={
                    "lldp": {
                        "management_address": "192.0.2.10",
                        "port_subtype": 3,
                        "port_id": "00:11:22:33:44:99",
                    }
                },
            )
        )
        db.commit()
    row = read(network)
    assert row["mac_address"] == MAC and row["connection_ambiguous"] and not row["connected_port"]


def test_dns_selection_and_negative_result_never_fall_back_to_other_names(network):
    sf, vlan_id, row_id, _ = network
    with sf() as db:
        vlan, row = db.get(m.VLAN, vlan_id), db.get(m.IPAddress, row_id)
        dns = m.DNSServer(name="Selected DNS", address="192.0.2.53")
        db.add(dns)
        db.flush()
        vlan.dns_server_id = dns.id
        service.observe(db, vlan, row.address, "dns", dns.id, {"hostname": "", "present": False})
        db.commit()
    assert read(network)["hostname"] == ""


def test_ipv6_gateway_requires_exact_prefix_interface_and_valid_neighbor_state():
    import ipaddress

    from netrix.ipam.connections import bindings, gateway_interfaces

    address = ipaddress.IPv6Address("2001:db8::10")
    prefix = ipaddress.IPv6Address("2001:db8::")
    index = "40.2.16." + ".".join(str(b) for b in address.packed)
    key = "2.16." + ".".join(str(b) for b in address.packed)
    pointer = "1.3.6.1.2.1.4.32.1.5.40.2.16." + ".".join(str(b) for b in prefix.packed) + ".64"
    tables = {
        "ndp_mac": {index: MAC},
        "ndp_state": {index: "1"},
        "ip_address_ifindex": {key: "40"},
        "ip_address_prefix": {key: pointer},
    }
    assert bindings(tables, set()) == [(str(address), MAC, 40)]
    assert gateway_interfaces(tables, ipaddress.ip_network("2001:db8::/64")) == {40}
    assert gateway_interfaces(tables, ipaddress.ip_network("2001:db8:1::/64")) == set()
    tables["ndp_state"][index] = "7"
    assert bindings(tables, set()) == []


async def test_gateway_mac_matches_vm_without_guest_ip_and_overrides_stale_dhcp(network, monkeypatch):
    from netrix.identity.security import encrypt
    from netrix.ipam import adapters, jobs

    sf, vlan_id, row_id, _ = network
    with sf() as db:
        vlan, row = db.get(m.VLAN, vlan_id), db.get(m.IPAddress, row_id)
        service.observe(db, vlan, row.address, "windows_dhcp", "dhcp", {"mac_address": "00:11:22:33:44:99"})
        config = m.Integration(
            name="VMware",
            kind="vcenter",
            enabled=True,
            host="vc.example.test",
            port=443,
            encrypted_secret=encrypt('{"username":"fixture","password":"fixture"}'),
        )
        db.add(config)
        db.flush()
        job = m.Job(kind="integration", target_id=config.id)
        db.add(job)
        db.commit()
        id = job.id
    monkeypatch.setattr(
        adapters,
        "vcenter_records",
        lambda *_: [
            {
                "address": "",
                "mac_address": MAC,
                "vm_id": "vm-1",
                "nic_key": "4000",
                "operating_system": "Ubuntu",
                "dvswitch_name": "DS-1",
                "dvport": "89",
            }
        ],
    )
    await jobs.integration(id)
    row = read(network)
    assert row["mac_address"] == MAC and row["operating_system"] == "Ubuntu"
    assert row["connected_device"] == "DS-1" and row["connected_port"] == "89"
    assert [o["data"]["matched_by"] for o in row["observations"] if o["source"] == "vcenter"] == [
        "gateway_mac"
    ]


def test_ipam_network_read_never_replaces_inventory_identity_view(network, admin_client):
    sf, _, _, ids = network
    with sf() as db:
        device = db.get(m.Device, ids[1])
        job = m.Job(kind="identify", target_id=device.id)
        db.add(job)
        db.flush()
        obs = m.Observation(
            job_id=job.id,
            device_id=device.id,
            address=device.management_ip,
            source="identity",
            evidence={"identity": {"model": "Original model"}},
            created_at=now() - timedelta(days=1),
        )
        db.add(obs)
        db.commit()
        observation_id = obs.id
    result = admin_client.get("/api/v1/observations", params={"device_id": ids[1], "limit": 5}).json()
    assert result["total"] == 1 and result["items"][0]["id"] == observation_id


def test_fortigate_prefix_pointer_and_subdivision_prove_gateway_attachment():
    import ipaddress

    from netrix.discovery.protocols import ipv4_value
    from netrix.ipam.connections import gateway_interfaces
    from pysnmp.proto.rfc1902 import OctetString

    # Recorded shape from FortiOS: VDOM suffix on address index; omitted length
    # in the prefix RowPointer. The IPAM VLAN is a subdivision of the /23.
    tables = {
        "ip_addr_ifindex": {"10.5.0.1.1": "44"},
        "ip_addr_address": {"10.5.0.1.1": "10.5.0.1"},
        "ip_addr_mask": {"10.5.0.1.1": ipv4_value(OctetString(b"\xff\xff\xfe\x00"))},
    }
    assert gateway_interfaces(tables, ipaddress.ip_network("10.5.0.0/24")) == {44}
    assert gateway_interfaces(tables, ipaddress.ip_network("10.6.0.0/24")) == set()
    assert gateway_interfaces(tables, ipaddress.ip_network("10.5.0.0/22", strict=False)) == set()
    pointer = {
        "ip_address_ifindex": {"1.4.10.5.0.1.44": "44"},
        "ip_address_prefix": {"1.4.10.5.0.1.44": "1.3.6.1.2.1.4.32.1.5.44.1.10.5.0.0.23"},
    }
    assert gateway_interfaces(pointer, ipaddress.ip_network("10.5.0.0/24")) == {44}
    pointer["ip_address_ifindex"]["1.4.10.5.0.1.44"] = "45"
    assert gateway_interfaces(pointer, ipaddress.ip_network("10.5.0.0/24")) == set()
    assert ipv4_value(OctetString(b"\x0a\x05\x00\x01")) == "10.5.0.1"
    assert ipv4_value(OctetString(b"bad")) == ""
