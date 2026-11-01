"""Independent network reads: no inventory writes, bounded concurrency and cancellation."""

import asyncio
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.discovery.protocols import NetworkError
from netrix.ipam.network import refresh
from sqlalchemy import func, select
from test_ipam_source_contract import network as network


async def test_network_read_is_bounded_and_keeps_inventory_topology_unchanged(network):
    sf, vlan_id, _, ids = network
    with sf() as db:
        template = db.get(m.Device, ids[0])
        for i in range(4, 7):
            db.add(
                m.Device(
                    name=f"Switch {i}",
                    kind="switch",
                    management_ip=f"198.51.100.{i}",
                    vrf_id=template.vrf_id,
                    discovery_scope_id=template.discovery_scope_id,
                    snmp_credential_id=template.snmp_credential_id,
                )
            )
        db.flush()
        devices_before = [
            (d.id, d.name, d.kind, d.discovery_scope_id)
            for d in db.scalars(select(m.Device).order_by(m.Device.id))
        ]
        links_before = db.scalar(select(func.count()).select_from(m.Link))
        job = m.Job(kind="ipam_discover", target_id=vlan_id)
        db.add(job)
        db.commit()
        job_id = job.id
    active = 0
    maximum = 0

    async def collect(host, port, secret):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        if host.endswith(".3"):
            raise NetworkError("secret-must-not-be-stored")
        return {"tables": {}, "interfaces": [], "neighbors": [], "hostname": "not-an-inventory-rename"}

    result = await refresh(job_id, SimpleNamespace(ipam=collect))
    assert result == {"devices": 6, "read": 5, "failed": 1}
    assert maximum <= 4
    with sf() as db:
        assert devices_before == [
            (d.id, d.name, d.kind, d.discovery_scope_id)
            for d in db.scalars(select(m.Device).order_by(m.Device.id))
        ]
        assert db.scalar(select(func.count()).select_from(m.Link)) == links_before
        observations = list(db.scalars(select(m.Observation).where(m.Observation.job_id == job_id)))
        assert len(observations) == 6 and all(o.source == "ipam_network" for o in observations)
        assert "secret-must-not-be-stored" not in str([o.evidence for o in observations])
    await refresh(job_id, SimpleNamespace(ipam=collect))
    with sf() as db:
        assert (
            db.scalar(select(func.count()).select_from(m.Observation).where(m.Observation.job_id == job_id))
            == 6
        )


async def test_cancelled_network_read_does_not_touch_a_device(network):
    from netrix.worker import Cancelled

    sf, vlan_id, _, _ = network
    with sf() as db:
        job = m.Job(kind="ipam_discover", target_id=vlan_id, cancel_requested=True)
        db.add(job)
        db.commit()
        job_id = job.id

    async def collect(*_):
        pytest.fail("cancelled scan contacted a device")

    with pytest.raises(Cancelled):
        await refresh(job_id, SimpleNamespace(ipam=collect))


async def test_snmp_ipam_reads_bulk_gateway_and_vlan_tables_only(monkeypatch):
    from netrix.discovery import protocols as p
    from pysnmp.proto.rfc1902 import OctetString
    from test_protocols import Engine, Transport

    monkeypatch.setattr(p, "SnmpEngine", Engine)
    monkeypatch.setattr(p, "UdpTransportTarget", Transport)
    monkeypatch.setattr(p, "ObjectType", lambda x: x)
    monkeypatch.setattr(p, "ObjectIdentity", lambda x: x)

    async def get(*args, **kwargs):
        return (
            None,
            0,
            0,
            [(oid, v) for oid, v in zip(args[4:], ["gateway", "1.3.6.1.4.1", 1000, "router", 1])],
        )

    walked = []

    async def bulk(engine, auth, target, context, nonrepeat, repeats, oid, **kwargs):
        assert nonrepeat == 0 and repeats == 25 and kwargs["maxRows"] == 16384
        walked.append(oid)
        data = {
            p.IPAM_TABLES["arp_mac"]: {"4.192.0.2.10": OctetString(bytes.fromhex("001122334455"))},
            p.IPAM_TABLES["vlan_fdb_id"]: {"0.20": 700},
            p.IPAM_TABLES["vlan_fdb_status"]: {"700.0.17.34.51.68.85": 3},
        }
        for index, value in data.get(oid, {}).items():
            yield None, 0, 0, [(oid + "." + index, value)]

    monkeypatch.setattr(p, "get_cmd", get)
    monkeypatch.setattr(p, "bulk_walk_cmd", bulk)
    result = await p.SNMPCollector().ipam("192.0.2.1", 161, {"protocol": "snmpv2c", "community": "fixture"})
    assert result["ip_forwarding"] == "1"
    assert result["tables"]["arp_mac"]["4.192.0.2.10"] == "00:11:22:33:44:55"
    assert result["tables"]["vlan_fdb_id"] == {"0.20": "700"}
    assert all("entity" not in key for key in p.IPAM_TABLES)
    assert not {"1.3.6.1.2.1.31.1.1.1.6", "1.3.6.1.2.1.31.1.1.1.10"} & set(walked)


async def test_restart_reuses_only_fresh_success_from_same_job_and_connection(network):
    from datetime import timedelta

    from netrix.core import now

    sf, vlan_id, _, ids = network
    with sf() as db:
        job = m.Job(kind="ipam_discover", target_id=vlan_id)
        db.add(job)
        db.commit()
        id = job.id
    calls = []

    async def collect(host, *_):
        calls.append(host)
        return {"tables": {}, "interfaces": []}

    collector = SimpleNamespace(ipam=collect)
    await refresh(id, collector)
    assert len(calls) == 3
    await refresh(id, collector)
    assert len(calls) == 3
    with sf() as db:
        device = db.get(m.Device, ids[1])
        device.snmp_port = 1161
        db.commit()
    await refresh(id, collector)
    assert calls.count("198.51.100.2") == 2 and len(calls) == 4
    with sf() as db:
        db.scalar(
            select(m.Observation).where(m.Observation.job_id == id, m.Observation.device_id == ids[0])
        ).created_at = now() - timedelta(days=2)
        db.commit()
    await refresh(id, collector)
    assert calls.count("198.51.100.1") == 2 and len(calls) == 5
    with sf() as db:
        other = m.Job(kind="ipam_discover", target_id=vlan_id)
        db.add(other)
        db.commit()
        other_id = other.id
    await refresh(other_id, collector)
    assert len(calls) == 8
