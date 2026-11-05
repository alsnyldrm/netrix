"""Ten devices share one worker-wide read limit; SQL never stalls protocol timers."""

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix import runtime_limits
from netrix.discovery import table_reads
from netrix.discovery.table_reads import read_table
from netrix.ipam import mac_cache
from netrix.ipam.network import refresh
from netrix.sources import network as source_network
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
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


@pytest.mark.parametrize("runner", [runtime_limits.sql_write, runtime_limits.sql_read])
async def test_sql_steps_retry_snapshot_conflicts(runner):
    attempts = 0

    def write():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OperationalError("UPDATE jobs", {}, Exception(1020, "Record has changed"))
        return "saved"

    assert await runner(write) == "saved" and attempts == 3


async def test_other_database_errors_are_not_retried():
    attempts = 0

    def write():
        nonlocal attempts
        attempts += 1
        raise OperationalError("SELECT", {}, Exception(2013, "Lost connection"))

    with pytest.raises(OperationalError):
        await runtime_limits.sql_write(write)
    assert attempts == 1


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


async def test_group_read_uses_ten_slots_and_saves_every_device(network):
    sf, vlan_id, *_ = network
    with sf() as db:
        template = db.scalar(select(m.Device).where(m.Device.kind == "switch"))
        for index in range(30):
            db.add(
                m.Device(
                    name=f"bulk-{index}",
                    management_ip=f"198.51.100.{index + 100}",
                    vrf_id=template.vrf_id,
                    kind="switch",
                    snmp_credential_id=template.snmp_credential_id,
                    discovery_scope_id=template.discovery_scope_id,
                )
            )
        job = m.Job(kind="ipam_discover", target_id=vlan_id)
        db.add(job)
        db.commit()
        job_id = job.id
    active = peak = 0

    async def collect(*args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"tables": {}, "interfaces": [], "neighbors": []}

    result = await refresh(job_id, SimpleNamespace(ipam=collect))
    assert peak == runtime_limits.DEVICE_READ_CONCURRENCY
    assert result["read"] == result["devices"] >= 30


def test_modules_keep_no_private_read_limit():
    import inspect

    from netrix.ipam import bulk_sources
    from netrix.ipam import network as ipam_network

    for module in (mac_cache, bulk_sources, ipam_network):
        assert "Semaphore(" not in inspect.getsource(module)
