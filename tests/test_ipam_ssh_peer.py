"""Current authenticated LLDP/CDP can join a host's distinct physical NIC MACs."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.core import now
from netrix.identity.security import encrypt
from netrix.ipam.network import refresh
from sqlalchemy import select
from test_ipam_host_connections import network as network
from test_ipam_host_connections import no_unrelated_fdb as no_unrelated_fdb
from test_ipam_host_connections import snapshot
from test_ipam_source_contract import MAC, read

CHASSIS = "00:11:22:99:99:00"


def test_ssh_local_chassis_preserves_vmware_host_nic_identity():
    from netrix.discovery.neighbor_detail import parse_detail

    n = parse_detail(
        "Local Port : B7\n ChassisType : local\n ChassisId : esxi.example.test\n SysName : VMware ESXi\n PortType : local\n PortId : vmnic1\n PortDescr : vmnic1\n",
        "lldp",
    )[0]
    assert n["evidence"]["lldp"]["chassis_subtype"] == 7
    assert n["evidence"]["lldp"]["port_subtype"] == 7


def peer(port, suffix):
    return dict(
        interface_name=port,
        remote_name="physical-host",
        remote_port=f"eth{suffix}",
        source="lldp+cdp",
        evidence={
            "lldp": {
                "chassis_subtype": 4,
                "chassis_id": CHASSIS,
                "port_subtype": 3,
                "port_id": f"00 11 22 aa 00 {suffix:02x}",
                "transport": "ssh_detail",
            },
            "cdp": {
                "device_id": CHASSIS,
                "management_address": "192.0.2.10",
                "port_id": f"eth{suffix}",
                "transport": "ssh_detail",
            },
        },
    )


def test_fresh_ssh_peer_links_distinct_nics_without_changing_ip_mac_or_directory(network):
    sf, _, _, ids = network
    with sf() as db:
        ns = [peer("A1", 1), peer("B2", 2)]
        snapshot(db, ids[1], ns)
        link = m.Link(
            device_id=ids[1],
            interface_name="A1",
            remote_name=ns[0]["remote_name"],
            remote_port="eth1",
            source="lldp+cdp",
            evidence=ns[0]["evidence"],
            auto_add_excluded=True,
            is_current=False,
        )
        db.add(link)
        db.commit()
        link_id = link.id
    item = read(network)
    assert item["connected_device"] == "Access" and item["connected_port"] == "A1 / B2"
    assert item["mac_address"] == MAC and not item["connection_ambiguous"]
    assert {n["mac_address"] for n in item["physical_nics"]} == {"00:11:22:aa:00:01", "00:11:22:aa:00:02"}
    with sf() as db:
        assert db.get(m.Link, link_id).auto_add_excluded and not db.get(m.Link, link_id).is_current


@pytest.mark.parametrize(
    "fault", ["wrong_ip", "wrong_chassis", "untyped_chassis", "no_authenticated_detail", "stale"]
)
def test_ssh_peer_requires_current_consistent_dual_protocol_identity(network, fault):
    sf, _, _, ids = network
    with sf() as db:
        n = peer("A1", 1)
        if fault == "wrong_ip":
            n["evidence"]["cdp"]["management_address"] = "192.0.2.99"
        if fault == "wrong_chassis":
            n["evidence"]["cdp"]["device_id"] = "00:11:22:cc:cc:cc"
        if fault == "untyped_chassis":
            n["evidence"]["lldp"]["chassis_subtype"] = 7
        if fault == "no_authenticated_detail":
            n["evidence"]["cdp"].pop("transport")
        obs = snapshot(db, ids[1], [n])
        if fault == "stale":
            obs.created_at = now() - timedelta(days=2)
        db.commit()
    assert not read(network)["connected_port"]


async def test_ipam_legacy_reader_never_collects_switch_ssh_detail(network):
    sf, vlan_id, _, ids = network
    with sf() as db:
        credential = m.Credential(
            name="SSH",
            protocol="ssh",
            encrypted_secret=encrypt('{"username":"fixture","password":"fixture-secret"}'),
        )
        db.add(credential)
        db.flush()
        device = db.get(m.Device, ids[1])
        device.adapter = "aruba_5400"
        device.config_credential_id = credential.id
        job = m.Job(kind="ipam_discover", target_id=vlan_id)
        db.add(job)
        db.commit()
        job_id = job.id
        before = [(d.id, d.updated_at) for d in db.scalars(select(m.Device))]

    async def collect(*_):
        return {
            "tables": {},
            "interfaces": [{"if_index": 101, "name": "A1", "oper_status": "up"}],
            "neighbors": [],
        }

    calls = []

    async def detail(device, secret):
        calls.append(device.id)
        assert secret["password"] == "fixture-secret"
        return {"neighbors": [peer("A1", 1)], "neighbor_protocols_complete": ["lldp", "cdp"]}

    result = await refresh(job_id, SimpleNamespace(ipam=collect), detail_reader=detail)
    assert calls == [] and result["failed"] == 0
    with sf() as db:
        assert not db.scalar(
            select(m.Observation).where(m.Observation.job_id == job_id, m.Observation.device_id == ids[1])
        )
        assert before == [(d.id, d.updated_at) for d in db.scalars(select(m.Device))]
