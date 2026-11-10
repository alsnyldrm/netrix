"""Regression coverage for repeated fallback work and head-of-line SQL reconciliation."""

import asyncio
from copy import deepcopy
from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.ipam import mac_cache, pipeline, sql_sources
from netrix.ipam.connections import Evidence
from sqlalchemy import select
from test_ipam_source_contract import MAC
from test_ipam_source_contract import network as network
from test_ipam_sql_manual import blocked as blocked


def test_fallback_prepares_each_source_set_once_but_invalidates_new_source(network, monkeypatch):
    sf, vid, rid, ids = network
    with sf() as db:
        for state in db.scalars(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id.in_(ids[1:]))):
            device = db.get(m.Device, state.device_id)
            state.read_context = mac_cache.context(device, db.get(m.Credential, device.snmp_credential_id))
            state.observed_at = now() - timedelta(hours=20)
        db.commit()
        row, vlan = db.get(m.IPAddress, rid), db.get(m.VLAN, vid)
        primary = Evidence(db, {vlan.vrf_id})
    calls = []
    original = mac_cache.projections

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(mac_cache, "projections", counted)
    item = {
        "connections": [],
        "connection_ambiguous": False,
        "gateway_evidence": [{"mac_address": MAC}],
        "sources": [],
    }
    with sf() as db:
        first = mac_cache.fallback(db, [row], [deepcopy(item)], {vid: vlan}, primary)
    with sf() as db:
        second = mac_cache.fallback(db, [row], [deepcopy(item)], {vid: vlan}, primary)
    assert first == second
    assert len(calls) == 1, "The same typed source set was rebuilt for every IP"
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == ids[1]))
        state.updated_at = now() + timedelta(seconds=1)
        db.commit()
    with sf() as db:
        mac_cache.fallback(db, [row], [deepcopy(item)], {vid: vlan}, primary)
    assert len(calls) == 2, "Changed canonical facts must invalidate transient reuse"


@pytest.mark.parametrize(
    "cidr,addresses",
    [
        (
            "192.0.2.0/24",
            ["192.0.2." + n for n in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "22", "100", "254")],
        ),
        (
            "2001:db8::/64",
            [
                "2001:db8::" + n
                for n in ("1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "22", "100", "fe")
            ],
        ),
    ],
)
async def test_manual_vlan_uses_four_numeric_targets_and_publishes_before_batch_finishes(
    network, blocked, monkeypatch, cidr, addresses
):
    import ipaddress

    sf, vid, rid, _ = network
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        vlan.cidr = cidr
        db.get(m.IPAddress, rid).address = addresses[3]
        db.add_all(
            [
                m.IPAddress(address=a, vrf_id=vlan.vrf_id, vlan_id=vid)
                for a in reversed(addresses)
                if a != addresses[3]
            ]
        )
        job = m.Job(kind="ipam_discover", target_id=vid, status="running", result={"ipam_origin": "manual"})
        db.add(job)
        db.commit()
        job_id = job.id
    expected = sorted(addresses, key=lambda a: int(ipaddress.ip_address(a)))
    calls, published = [], []
    first_started, fast_saved, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    active = peak = 0

    async def resolve(self, *args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls.append(self.row.address)
        try:
            if len(calls) == 4:
                first_started.set()
            if self.row.address in expected[:4]:
                await first_started.wait()
            if self.row.address == expected[0]:
                await release.wait()
            return dict(status="success", issues=[], steps=[], values={"connections": []})
        finally:
            active -= 1

    def notify(**kwargs):
        assert kwargs == {"ipam_vlan": vid}
        with sf() as db:
            # Read in a fresh transaction: notifications must follow durable writes.
            rows = list(
                db.execute(
                    select(m.IPAddress.address, m.IPAMResult.completed_at).join(
                        m.IPAMResult, m.IPAMResult.address_id == m.IPAddress.id
                    )
                )
            )
            published.append(sorted([a for a, _ in rows], key=lambda a: int(ipaddress.ip_address(a))))
            assert db.get(m.Job, job_id).progress >= len(rows)
            if len(rows) == 3 and not release.is_set():
                fast_saved.set()

    monkeypatch.setattr(sql_sources.SQLSources, "resolve", resolve)
    monkeypatch.setattr(sql_sources, "publish", notify)
    task = asyncio.create_task(sql_sources.scan_vlan(job_id))
    try:
        await asyncio.wait_for(first_started.wait(), 3)
        await asyncio.wait_for(fast_saved.wait(), 3)
        assert not task.done(), "Ready IPs must be published before the batch and VLAN finish"
        assert calls == expected[:4], "The fifth IP must wait for all four current IPs"
        assert published[-1] == expected[1:4]
        assert peak == 4
        with sf() as db:
            assert db.get(m.Job, job_id).progress == 3
            assert (
                db.scalar(select(m.IPAMResult).join(m.IPAddress).where(m.IPAddress.address == expected[0]))
                is None
            )
            assert (
                db.scalar(
                    select(m.IPAMResult).join(m.IPAddress).where(m.IPAddress.address == expected[1])
                ).status
                == "success"
            )
    finally:
        release.set()
        await asyncio.wait_for(task, 5)
    assert calls == expected
    assert published[-1] == expected
    assert len(published) == len(expected)
    assert peak == 4


async def test_restart_skips_committed_results_and_fresh_job_reprocesses(network, blocked, monkeypatch):
    sf, vid, rid, _ = network
    with sf() as db:
        job = m.Job(kind="ipam_discover", target_id=vid, status="running", result={"ipam_origin": "manual"})
        db.add(job)
        db.commit()
        job_id = job.id
    calls = []
    original = sql_sources.SQLSources.resolve

    async def counted(self, *args, **kwargs):
        calls.append(self.row.id)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(sql_sources.SQLSources, "resolve", counted)
    first = await sql_sources.scan_vlan(job_id)
    with sf() as db:
        saved = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid)).completed_at
    second = await sql_sources.scan_vlan(job_id)
    assert first["resolved"] == second["resolved"] == 1
    assert calls == [rid], "Restart reprocessed a result that was already committed"
    with sf() as db:
        assert db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid)).completed_at == saved
        fresh = m.Job(kind="ipam_discover", target_id=vid, status="running", result={"ipam_origin": "manual"})
        db.add(fresh)
        db.commit()
        fresh_id = fresh.id
    await sql_sources.scan_vlan(fresh_id)
    assert calls == [rid, rid], "A new explicit request must still reconcile the IP"


async def test_partial_restart_preserves_completed_timestamp_and_progress(network, blocked, monkeypatch):
    sf, vid, rid, _ = network
    with sf() as db:
        vlan = db.get(m.VLAN, vid)
        row = m.IPAddress(address="192.0.2.11", vrf_id=vlan.vrf_id, vlan_id=vid)
        job = m.Job(kind="ipam_discover", target_id=vid, status="running", result={"ipam_origin": "manual"})
        db.add_all([row, job])
        db.commit()
        job_id, other_id = job.id, row.id
    called = []
    original = sql_sources.SQLSources.resolve
    release = asyncio.Event()

    async def resolve(self, *args, **kwargs):
        called.append(self.row.id)
        if self.row.id == other_id:
            await release.wait()
        return await original(self, *args, **kwargs)

    first_saved = asyncio.Event()
    monkeypatch.setattr(sql_sources.SQLSources, "resolve", resolve)
    monkeypatch.setattr(sql_sources, "publish", lambda **kwargs: first_saved.set())
    task = asyncio.create_task(sql_sources.scan_vlan(job_id))
    await asyncio.wait_for(first_saved.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with sf() as db:
        before = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid)).completed_at
        assert db.get(m.Job, job_id).progress == 1
    called.clear()
    release.set()
    result = await sql_sources.scan_vlan(job_id)
    assert called == [other_id]
    assert result["resolved"] == 2
    with sf() as db:
        assert db.get(m.Job, job_id).progress == 2
        assert db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid)).completed_at == before


@pytest.mark.parametrize("change", ["vlan", "teaming", "profile"])
async def test_resume_rechecks_changed_inputs(network, blocked, monkeypatch, change):
    sf, vid, rid, ids = network
    with sf() as db:
        job = m.Job(kind="ipam_discover", target_id=vid, status="running", result={"ipam_origin": "manual"})
        db.add(job)
        db.commit()
        job_id = job.id
    await sql_sources.scan_vlan(job_id)
    with sf() as db:
        if change == "vlan":
            db.get(m.VLAN, vid).vid += 1
        elif change == "teaming":
            db.get(m.IPAddress, rid).nic_teaming = True
        else:
            credential = db.get(m.Credential, db.get(m.Device, ids[1]).snmp_credential_id)
            credential.updated_at = now() + timedelta(seconds=1)
        db.commit()
    called = []
    original = sql_sources.SQLSources.resolve

    async def counted(self, *args, **kwargs):
        called.append(self.row.id)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(sql_sources.SQLSources, "resolve", counted)
    await sql_sources.scan_vlan(job_id)
    assert called == [rid]


async def test_newer_point_result_is_not_overwritten_by_parallel_vlan_work(network, blocked, monkeypatch):
    sf, vid, rid, _ = network
    with sf() as db:
        job = m.Job(kind="ipam_discover", target_id=vid, status="running", result={"ipam_origin": "manual"})
        db.add(job)
        db.commit()
        job_id = job.id
    original = sql_sources.SQLSources.resolve
    stamp = None

    async def newer(self, *args, **kwargs):
        nonlocal stamp
        result = await original(self, *args, **kwargs)
        result["status"] = "problem"
        with sf() as db:
            dns = db.scalar(select(m.DNSRecord).where(m.DNSRecord.address_id == rid))
            dns.hostname = "newer.example"
            db.commit()

        async def latest_dns(*args):
            return "newer.example"

        monkeypatch.setattr("netrix.ipam.adapters.reverse_dns", latest_dns)
        latest = await original(self.context.for_row(self.row))
        latest["status"], latest["issues"] = "success", []
        with sf() as db:
            pipeline.save_result(db, db.get(m.IPAddress, rid), now(), latest)
            db.commit()
            stamp = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid)).completed_at
        return result

    monkeypatch.setattr(sql_sources.SQLSources, "resolve", newer)
    final = await sql_sources.scan_vlan(job_id)
    assert final["problems"] == 0
    with sf() as db:
        row = db.scalar(select(m.IPAMResult).where(m.IPAMResult.address_id == rid))
        assert row.values["hostname"] == "newer.example"
        assert row.completed_at == stamp
