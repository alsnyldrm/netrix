"""Finished IP results are durable/readable while slower probes and sources still run."""

import asyncio

from conftest import make_vlan
from netrix import models as m
from netrix import services
from netrix.core import now
from netrix.ipam import adapters, jobs, read_cache
from sqlalchemy import select


def running_scan(env):
    with env() as db:
        vlan = make_vlan(vrf_id=db.scalar(select(m.VRF.id)), cidr="192.0.2.0/29")
        db.add(vlan)
        db.flush()
        row = jobs.observe(db, vlan, "192.0.2.2", "icmp", vlan.id, {"reachability": "no_reply"})
        job = m.Job(kind="ipam_discover", target_id=vlan.id, status="running")
        db.add(job)
        db.commit()
        return vlan.id, job.id, row.id


async def test_fast_results_are_readable_before_slow_ip_and_later_sources(admin_client, env, monkeypatch):
    from netrix.ipam import network

    vlan_id, job_id, row_id = running_scan(env)
    monkeypatch.setattr(read_cache, "client", lambda _: services.redis_client())
    monkeypatch.setattr(read_cache, "_retry_after", 0)
    url = f"/api/v1/ipam/vlans/{vlan_id}/addresses?active_only=true"
    assert admin_client.get(url).json()["items"] == []  # Prime cached empty view.
    slow, source, notified, source_started = (asyncio.Event() for _ in range(4))
    publish = jobs.publish

    def report(**kwargs):
        publish(**kwargs)
        if kwargs.get("ipam_vlan") == vlan_id:
            notified.set()

    async def ping(address):
        if address.endswith(".3"):
            await slow.wait()
        return address.endswith((".1", ".2"))

    async def dns(address, _):
        return "host-" + address.rsplit(".", 1)[1] + ".example.test"

    async def read_sources(*args):
        source_started.set()
        await source.wait()
        return {"read": 0, "failed": 0}

    monkeypatch.setattr(jobs, "publish", report)
    monkeypatch.setattr(adapters, "ping", ping)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    monkeypatch.setattr(network, "refresh", read_sources)
    task = asyncio.create_task(jobs.scan(job_id))
    try:
        await asyncio.wait_for(notified.wait(), 2)
        assert not task.done() and not source_started.is_set()
        rows = admin_client.get(url).json()["items"]
        assert {r["address"] for r in rows} == {"192.0.2.1", "192.0.2.2"}
        assert {r["hostname"] for r in rows} == {"host-1.example.test", "host-2.example.test"}
        assert admin_client.get(f"/api/v1/ipam/addresses/{row_id}").json()["availability"] == "active"
        with env() as db:
            job = db.get(m.Job, job_id)
            assert job.status == "running" and 0 < job.progress < job.total
        slow.set()
        await asyncio.wait_for(source_started.wait(), 2)
        assert not task.done() and len(admin_client.get(url).json()["items"]) == 2
        source.set()
        await asyncio.wait_for(task, 2)
    finally:
        slow.set()
        source.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_dns_completion_publishes_fast_name_before_slow_name(admin_client, env, monkeypatch):
    vlan_id, job_id, _ = running_scan(env)
    with env() as db:
        vlan = db.get(m.VLAN, vlan_id)
        jobs.observe(db, vlan, "192.0.2.1", "icmp", vlan.id, {"reachability": "reachable"})
        db.commit()
    slow, notified = asyncio.Event(), asyncio.Event()
    publish = jobs.publish

    def report(**kwargs):
        publish(**kwargs)
        if kwargs.get("ipam_vlan") == vlan_id:
            notified.set()

    async def dns(address, _):
        if address.endswith(".2"):
            await slow.wait()
        return "host-" + address.rsplit(".", 1)[1] + ".example.test"

    monkeypatch.setattr(jobs, "publish", report)
    monkeypatch.setattr(adapters, "reverse_dns", dns)
    task = asyncio.create_task(jobs.complete_dns(job_id, now()))
    try:
        await asyncio.wait_for(notified.wait(), 2)
        assert not task.done()
        with env() as db:
            record = db.scalar(select(m.IPObservation).where(m.IPObservation.source == "dns"))
            assert record.data["hostname"] == "host-1.example.test"
        slow.set()
        await asyncio.wait_for(task, 2)
    finally:
        slow.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_cancelling_incremental_scan_cleans_up_pending_probes(admin_client, env, monkeypatch):
    _, job_id, _ = running_scan(env)
    started, stopped = asyncio.Event(), asyncio.Event()
    active = 0

    async def ping(address):
        nonlocal active
        active += 1
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1
            if active == 0:
                stopped.set()

    monkeypatch.setattr(adapters, "ping", ping)
    task = asyncio.create_task(jobs.scan(job_id))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert stopped.is_set() and active == 0
