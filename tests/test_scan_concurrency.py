"""Ten devices share one worker-wide read limit; SQL never stalls protocol timers."""

import asyncio
import threading
import time
from types import SimpleNamespace

from netrix import models as m
from netrix import runtime_limits, worker
from netrix.discovery import table_reads
from netrix.discovery.table_reads import read_table
from netrix.ipam import mac_cache
from netrix.sources import network as source_network
from sqlalchemy import select
from test_ipam_source_contract import network as network

OID = "1.3.6.1.2.1.17.7.1.2.2.1.2"


def walker(delay, pages, *, stall=False):
    async def walk(*args, **kwargs):
        for page in range(pages):
            await asyncio.sleep(delay)
            yield None, 0, 0, [(f"{OID}.{page}", str(page))]
        if stall:
            await asyncio.sleep(30)

    return walk


async def test_slow_table_that_keeps_answering_completes(monkeypatch):
    monkeypatch.setattr(table_reads, "walk_table", walker(0.03, 10))
    rows, outcome = await read_table(None, None, None, None, OID, timeout=0.1)
    assert outcome["status"] == "complete" and len(rows) == 10


async def test_silent_table_times_out_and_keeps_answered_rows(monkeypatch):
    monkeypatch.setattr(table_reads, "walk_table", walker(0.01, 3, stall=True))
    rows, outcome = await read_table(None, None, None, None, OID, timeout=0.1)
    assert outcome == dict(status="timeout", row_count=3, error_code="table_timeout")


async def test_table_deadline_bounds_a_table_that_never_ends(monkeypatch):
    monkeypatch.setattr(table_reads, "walk_table", walker(0.02, 10_000))
    started = asyncio.get_running_loop().time()
    _, outcome = await read_table(None, None, None, None, OID, timeout=5, deadline=started + 0.15)
    assert outcome["status"] == "timeout"
    assert asyncio.get_running_loop().time() - started < 1


async def test_blocking_sql_does_not_stall_the_event_loop():
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    await runtime_limits.sql_write(time.sleep, 0.3)
    task.cancel()
    assert ticks >= 10


async def test_sql_writes_are_serialized_on_one_thread():
    names, active, peak = set(), 0, 0
    guard = threading.Lock()

    def write():
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
            names.add(threading.current_thread().name)
        time.sleep(0.01)
        with guard:
            active -= 1

    await asyncio.gather(*(runtime_limits.sql_write(write) for _ in range(8)))
    assert peak == 1 and len(names) == 1


async def test_device_slot_is_shared_between_jobs():
    assert runtime_limits.DEVICE_READ_CONCURRENCY == 10
    active = peak = 0

    async def read():
        nonlocal active, peak
        async with runtime_limits.device_slot():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.005)
            active -= 1

    await asyncio.gather(*(read() for _ in range(35)))
    assert peak == 10


def test_column_projection_matches_orm_relationship(network):
    sf, *_ = network
    with sf() as db:
        state = db.scalar(select(m.IPAMNetworkState).join(m.SwitchMacEntry))
        columns = source_network.mac_rows(db, state)
        assert columns
        _ = state.mac_entries
        assert sorted(map(tuple, columns), key=str) == sorted(
            map(tuple, source_network.mac_rows(db, state)), key=str
        )


async def test_mac_scan_reads_ten_at_once_and_saves_every_switch(admin_client, network, monkeypatch):
    sf, *_ = network
    with sf() as db:
        template = db.scalar(select(m.Device).where(m.Device.kind == "switch"))
        for index in range(30):
            db.add(
                m.Device(
                    name=f"bulk-{index}",
                    management_ip=f"10.77.0.{index + 1}",
                    vrf_id=template.vrf_id,
                    kind="switch",
                    snmp_credential_id=template.snmp_credential_id,
                    discovery_scope_id=template.discovery_scope_id,
                )
            )
        db.commit()
        expected = len(mac_cache.devices(db))
    active = peak = reads = 0

    async def read(*args):
        nonlocal active, peak, reads
        active += 1
        reads += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"failed": False, "tables": {}, "interfaces": [], "unsupported": []}

    job = admin_client.post("/api/v1/ipam/switch-mac-cache/scan").json()
    worker.claim(interactive=False, include_kinds=(mac_cache.KIND,))
    await asyncio.wait_for(worker.execute(job["id"], SimpleNamespace(switch_macs=read)), 60)
    assert peak == runtime_limits.DEVICE_READ_CONCURRENCY and reads == expected
    with sf() as db:
        saved = db.get(m.Job, job["id"])
        assert saved.progress == expected
        assert sum(saved.result["totals"][k] for k in ("read", "failed")) == expected
        assert sum(s.attempted_at is not None for s in db.scalars(select(m.IPAMNetworkState))) >= expected


def test_modules_keep_no_private_read_limit():
    import inspect

    from netrix.ipam import bulk_sources
    from netrix.ipam import network as ipam_network

    for module in (mac_cache, bulk_sources, ipam_network):
        assert "Semaphore(" not in inspect.getsource(module)
