from copy import deepcopy
from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.ipam.connections import Evidence
from netrix.ipam.fdb_path import routed_ports, terminal_ports
from netrix.ipam.inventory_sources import attachment, point_evidence
from sqlalchemy import select
from test_ipam_source_contract import MAC
from test_ipam_source_contract import network as network  # noqa: PLC0414


@pytest.mark.parametrize("unmapped_neighbor", [False, True])
def test_backbone_path_keeps_multi_mac_access_port(network, unmapped_neighbor):
    sf, vid, rid, ids = network
    with sf() as db:
        root = db.get(m.Device, ids[2])
        root.name = "HP-SW-BB-01"
        alternate_profile = m.Credential(
            name="Another SNMP profile", protocol="snmpv2c", encrypted_secret="x"
        )
        db.add(alternate_profile)
        db.flush()
        root.snmp_credential_id = alternate_profile.id
        access = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        access.mac_entries.append(
            m.SwitchMacEntry(
                vrf_id=access.mac_entries[0].vrf_id,
                vlan_vid=20,
                fdb_id=700,
                mac_address="00:11:22:33:44:66",
                port="Gi1/0/1",
                if_index=101,
                bridge_port=9,
            )
        )
        db.add(
            m.Link(
                device_id=ids[1],
                interface_name="Gi1/0/1",
                source="lldp",
                remote_name="Phone",
                remote_port="00:11:22:33:44:66",
                last_seen_at=now(),
            )
        )
        if unmapped_neighbor:
            db.add(
                m.Link(
                    device_id=ids[1],
                    interface_name="4c:ae:a3:06:c3:04",
                    source="lldp",
                    remote_name="Unmapped neighbor",
                    last_seen_at=now(),
                )
            )
        db.commit()
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        for evidence in (None, point_evidence(db, row, vlan, MAC)):
            result = attachment(db, row, vlan, MAC, evidence=evidence)
            assert [(c["device_id"], c["port"]) for c in result["connections"]] == [(ids[1], "Gi1/0/1")]

        # A missing backbone hop falls back to a unique, proven terminal port.
        link = db.scalar(select(m.Link).where(m.Link.device_id == ids[2]))
        link.remote_device_id = None
        link.evidence = {"spanning_tree": {"port": link.interface_name}}
        db.commit()
        phone = db.scalar(select(m.Link).where(m.Link.device_id == ids[1], m.Link.interface_name == "Gi1/0/1"))
        phone.evidence = {"lldp": {"port_subtype": 3, "port_id": "00:11:22:33:44:66"}}
        db.commit()
        for evidence in (None, point_evidence(db, row, vlan, MAC)):
            fallback = attachment(db, row, vlan, MAC, evidence=evidence)
            if unmapped_neighbor:
                assert not fallback["connections"]
            else:
                assert fallback["connected_device"] == "Access"
                assert fallback["connected_port"] == "Gi1/0/1"


@pytest.mark.parametrize("resolvable_hop", [True, False])
def test_backbone_does_not_report_an_unresolved_switch_hop_as_the_endpoint(network, resolvable_hop):
    sf, vid, rid, (gateway, access, intermediate) = network
    with sf() as db:
        middle = db.get(m.Device, intermediate)
        middle.name = "HP-SW-BB-02"
        access_device = db.get(m.Device, access)
        upstream = m.Device(
            name="HP-SW-BB-01",
            kind="switch",
            management_ip="198.51.100.4",
            vrf_id=middle.vrf_id,
            discovery_scope_id=middle.discovery_scope_id,
            snmp_credential_id=middle.snmp_credential_id,
        )
        db.add(upstream)
        db.flush()
        observation = db.scalar(select(m.Observation).where(m.Observation.device_id == intermediate))
        db.add(
            m.Observation(
                job_id=observation.job_id,
                device_id=upstream.id,
                address=upstream.management_ip,
                source="ipam_network",
                evidence=deepcopy(observation.evidence),
            )
        )
        db.add(
            m.Link(
                device_id=upstream.id,
                remote_device_id=middle.id,
                interface_name="Gi1/0/1",
                source="lldp",
                last_seen_at=now(),
            )
        )
        middle_link = db.scalar(select(m.Link).where(m.Link.device_id == intermediate))
        middle_link.remote_device_id = None
        middle_link.evidence = {
            "lldp": {
                "system_name": access_device.name,
                "management_address": access_device.management_ip,
                "port_id": "Gi1/0/48",
            },
        }
        if not resolvable_hop:
            middle_link.evidence = {
                **middle_link.evidence,
                "cdp": {"management_address": db.get(m.Device, gateway).management_ip},
            }
        db.add(
            m.Link(
                device_id=access,
                interface_name="Gi1/0/1",
                source="lldp",
                last_seen_at=now(),
                evidence={
                    "lldp": {
                        "system_name": "AVX334455",
                        "chassis_subtype": 5,
                        "chassis_id": "10:00:00:00:00:00",
                        "port_subtype": 3,
                        "port_id": "0x" + MAC.encode("ascii").hex(),
                    }
                },
            )
        )
        db.commit()
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        for evidence in (Evidence(db, {row.vrf_id}), point_evidence(db, row, vlan, MAC)):
            cutoff = evidence.at - timedelta(hours=1)
            static = evidence._static_links(row.vrf_id, cutoff)
            path = routed_ports({upstream.id, middle.id}, static, vlan.vid, MAC, cutoff)
            assert set(path) == ({(access, "Gi1/0/1")} if resolvable_hop else set())
            assert set(terminal_ports(static, static["blocked"], vlan.vid, MAC, cutoff)) == {
                (access, "Gi1/0/1")
            }
            result = attachment(db, row, vlan, MAC, evidence=evidence)
            assert [(c["device_id"], c["port"]) for c in result["connections"]] == [(access, "Gi1/0/1")]
            assert result["neighbor_hostname"][:2] == ("lldp", "AVX334455")
        assert middle_link.remote_device_id is None
