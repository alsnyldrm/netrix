"""Prove queue isolation on a disposable MariaDB without touching real devices."""

import asyncio
import time
from uuid import uuid4

from netrix import models as m
from netrix import worker
from netrix.core import engine, session_factory

assert engine().url.database == "netrix_test"
sf = session_factory()
with sf() as db:
    jobs = [m.Job(kind="discovery", target_id=str(uuid4())) for _ in range(4)]
    jobs.append(m.Job(kind="ipam_ping", target_id=str(uuid4())))
    db.add_all(jobs)
    db.commit()
    short_id = jobs[-1].id


async def check():
    release, started = asyncio.Event(), asyncio.Event()
    active = {}

    async def fake_execute(id):
        with sf() as db:
            kind = db.get(m.Job, id).kind
        active[id] = kind
        if id == short_id:
            started.set()
        await release.wait()
        with sf() as db:
            db.get(m.Job, id).status = "succeeded"
            db.commit()
        active.pop(id)

    worker.execute = fake_execute
    worker.publish = lambda: None
    worker.heartbeat = lambda role: None
    worker.stop = False
    began = time.monotonic()
    pool = asyncio.create_task(worker.worker_loop())
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        elapsed = time.monotonic() - began
        assert len(active) <= 4 and list(active.values()).count("discovery") == 2
        print(
            f"MariaDB dispatch PASS: short task started in {elapsed:.3f}s while two long scans stayed blocked; capacity and reserved slots verified"
        )
    finally:
        worker.stop = True
        release.set()
        await asyncio.wait_for(pool, timeout=3)


asyncio.run(check())
