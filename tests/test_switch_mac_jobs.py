"""Six-hour singleton scheduling, bounded switch-only collection and live source isolation."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix import worker
from netrix.ipam import adapters, mac_cache
from sqlalchemy import delete, func, select
from test_ipam_source_contract import network as network


def test_four_local_slots_and_no_catchup_burst(network):
    sf, *_ = network
    expected = [
        "2026-11-03T21:00:00+00:00",
        "2026-11-04T03:00:00+00:00",
        "2026-11-04T09:00:00+00:00",
        "2026-11-04T15:00:00+00:00",
    ]
    start = datetime(2026, 11, 3, 21, tzinfo=timezone.utc)
    for i, value in enumerate(expected):
        at = start + timedelta(hours=i * 6)
        assert mac_cache.slot(at).isoformat() == value
        with sf() as db:
            job = mac_cache.enqueue(db, scheduled_at=at)
            assert job and job.result["slot"] == value
            assert mac_cache.enqueue(db, scheduled_at=at + timedelta(seconds=1)) is None
            job.status, job.active_key = "succeeded", None
            db.commit()
    with sf() as db:
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == mac_cache.KIND)) == 4
        job = mac_cache.enqueue(db, scheduled_at=start + timedelta(days=10))
        assert job
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == mac_cache.KIND)) == 5


def test_manual_and_scheduler_share_active_work_and_reads_are_passive(admin_client, network):
    sf, *_ = network
    response = admin_client.post("/api/v1/ipam/switch-mac-cache/scan")
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["kind"] == mac_cache.KIND and job["requested_by"]
    assert admin_client.post("/api/v1/ipam/switch-mac-cache/scan").json()["id"] == job["id"]
    with sf() as db:
        assert mac_cache.enqueue(db, scheduled_at=datetime(2026, 11, 3, tzinfo=timezone.utc)).id == job["id"]
    for _ in range(3):
        status = admin_client.get("/api/v1/ipam/switch-mac-cache").json()
        assert status["switches"] == 2 and status["entries"] == 0 and status["healthy"] == 0
    with sf() as db:
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == mac_cache.KIND)) == 1
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    assert admin_client.post("/api/v1/ipam/switch-mac-cache/scan").status_code == 403


async def test_worker_reads_only_switches_and_never_other_ipam_sources(admin_client, network, monkeypatch):
    sf, *_ = network
    with sf() as db:
        payloads = {o.address: deepcopy(o.evidence) for o in db.scalars(select(m.Observation))}
    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError("MAC cache scan accessed an unrelated source")

    for name in ("ping", "reverse_dns", "vcenter_records", "windows_dhcp"):
        monkeypatch.setattr(adapters, name, forbidden)

    async def read(host, *_):
        calls.append(host)
        return payloads[host]

    job = admin_client.post("/api/v1/ipam/switch-mac-cache/scan").json()
    assert worker.claim(interactive=False, include_kinds=(mac_cache.KIND,)) == job["id"]
    await worker.execute(job["id"], SimpleNamespace(switch_macs=read))
    assert set(calls) == {"198.51.100.2", "198.51.100.3"}
    with sf() as db:
        stored = db.get(m.Job, job["id"])
        assert stored.status == "succeeded" and stored.progress == stored.total == 2
        assert db.scalar(select(func.count()).select_from(m.SwitchMacSnapshot)) == 2
        assert db.scalar(select(func.count()).select_from(m.SwitchMacEntry)) == 2
        assert db.scalar(select(func.count()).select_from(m.Device)) == 3
        assert not db.scalar(select(m.IPObservation.id).where(m.IPObservation.source == "switch_mac_cache"))


async def test_device_deleted_during_source_read_is_not_published(admin_client, network):
    sf, *_ = network
    with sf() as db:
        payloads = {o.address: deepcopy(o.evidence) for o in db.scalars(select(m.Observation))}

    async def read(host, *_):
        if host.endswith(".3"):
            with sf() as db:
                device = db.scalar(select(m.Device).where(m.Device.management_ip == host))
                db.execute(delete(m.Link).where(m.Link.device_id == device.id))
                db.execute(delete(m.Observation).where(m.Observation.device_id == device.id))
                db.delete(device)
                db.commit()
        return payloads[host]

    job = admin_client.post("/api/v1/ipam/switch-mac-cache/scan").json()
    assert worker.claim(interactive=False, include_kinds=(mac_cache.KIND,)) == job["id"]
    await worker.execute(job["id"], SimpleNamespace(switch_macs=read))
    with sf() as db:
        stored = db.get(m.Job, job["id"])
        assert stored.status == "partial" and stored.progress == stored.total == 2
        assert stored.result["failed_devices"][0]["error_class"] == "SourceChanged"
        assert db.scalar(select(func.count()).select_from(m.SwitchMacSnapshot)) == 1


async def test_partial_read_invalidates_failed_cache_without_deleting_last_rows(admin_client, network):
    sf, *_ = network
    with sf() as db:
        payloads = {o.address: deepcopy(o.evidence) for o in db.scalars(select(m.Observation))}
    fail = False

    async def read(host, *_):
        if fail and host.endswith(".3"):
            return {"tables": {}, "unsupported": ["vlan_fdb_port"]}
        return payloads[host]

    for iteration in range(2):
        job = admin_client.post("/api/v1/ipam/switch-mac-cache/scan").json()
        assert worker.claim(interactive=False, include_kinds=(mac_cache.KIND,)) == job["id"]
        await worker.execute(job["id"], SimpleNamespace(switch_macs=read))
        fail = True
    with sf() as db:
        assert db.get(m.Job, job["id"]).status == "partial"
        assert db.scalar(select(func.count()).select_from(m.SwitchMacEntry)) == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(m.SwitchMacSnapshot)
                .where(m.SwitchMacSnapshot.healthy.is_(True))
            )
            == 1
        )


async def test_cache_scan_concurrency_and_cancel_clean_up_pending_reads(admin_client, network):
    sf, _, _, ids = network
    with sf() as db:
        base = db.get(m.Device, ids[1])
        for i in range(4, 10):
            db.add(
                m.Device(
                    name=f"Switch {i}",
                    management_ip=f"198.51.100.{i}",
                    kind="switch",
                    vrf_id=base.vrf_id,
                    discovery_scope_id=base.discovery_scope_id,
                    snmp_credential_id=base.snmp_credential_id,
                )
            )
        db.commit()
    active = peak = 0
    started = asyncio.Event()

    async def read(*_):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 4:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    job = admin_client.post("/api/v1/ipam/switch-mac-cache/scan").json()
    worker.claim(interactive=False, include_kinds=(mac_cache.KIND,))
    task = asyncio.create_task(worker.execute(job["id"], SimpleNamespace(switch_macs=read)))
    await asyncio.wait_for(started.wait(), 3)
    with sf() as db:
        db.get(m.Job, job["id"]).cancel_requested = True
        db.commit()
    await asyncio.wait_for(task, 4)
    assert peak == 4 and active == 0
    with sf() as db:
        assert db.get(m.Job, job["id"]).status == "cancelled"


def test_no_configured_switch_does_not_create_fictional_success(admin_client, env):
    from fastapi import HTTPException

    with env() as db:
        assert mac_cache.enqueue(db, scheduled_at=datetime(2026, 11, 3, tzinfo=timezone.utc)) is None
        assert not db.scalar(select(m.Job.id))
        with pytest.raises(HTTPException):
            mac_cache.enqueue(db)


async def test_mac_protocol_reads_fdb_and_neighbors_without_arp_or_traffic(monkeypatch):
    from netrix.discovery import protocols as p
    from test_protocols import Engine, Transport

    monkeypatch.setattr(p, "SnmpEngine", Engine)
    monkeypatch.setattr(p, "UdpTransportTarget", Transport)
    monkeypatch.setattr(p, "ObjectType", lambda x: x)
    monkeypatch.setattr(p, "ObjectIdentity", lambda x: x)

    async def get(*args, **kwargs):
        return None, 0, 0, [(oid, v) for oid, v in zip(args[4:], ["switch", "1.3.6.1.4.1", 1000, "switch"])]

    walked = set()

    async def bulk(engine, auth, target, context, nonrepeat, repeats, oid, **kwargs):
        assert kwargs["maxRows"] == 65536
        walked.add(oid)
        if oid == p.IPAM_TABLES["vlan_fdb_id"]:
            yield None, 0, 0, [(oid + ".0.20", 700)]

    monkeypatch.setattr(p, "get_cmd", get)
    monkeypatch.setattr(p, "bulk_walk_cmd", bulk)
    result = await p.SNMPCollector().switch_macs(
        "192.0.2.1", 161, {"protocol": "snmpv2c", "community": "fixture"}
    )
    assert result["tables"]["vlan_fdb_id"] == {"0.20": "700"}
    assert not {p.IPAM_TABLES[k] for k in p.IPAM_TABLES if k.startswith(("arp_", "ndp_", "ip_"))} & walked
    assert not {"1.3.6.1.2.1.31.1.1.1.6", "1.3.6.1.2.1.31.1.1.1.10"} & walked
