import asyncio

from netrix import models as m
from netrix import worker
from sqlalchemy import select


async def test_long_discoveries_do_not_block_short_jobs(env, monkeypatch):
    with env() as db:
        jobs = [m.Job(kind="discovery", target_id=f"scope-{i}") for i in range(4)]
        jobs += [m.Job(kind="ipam_ping", target_id="prefix")]
        db.add_all(jobs)
        db.commit()
        short_id = jobs[-1].id
    release, short_started = asyncio.Event(), asyncio.Event()
    active = peak = discovery_peak = 0
    discoveries = 0

    async def execute(id):
        nonlocal active, peak, discoveries, discovery_peak
        with env() as db:
            kind = db.get(m.Job, id).kind
        active += 1
        discoveries += int(kind == "discovery")
        peak = max(peak, active)
        discovery_peak = max(discovery_peak, discoveries)
        try:
            if id == short_id:
                short_started.set()
            await release.wait()
            with env() as db:
                db.get(m.Job, id).status = "succeeded"
                db.commit()
        finally:
            active -= 1
            discoveries -= int(kind == "discovery")

    monkeypatch.setattr(worker, "execute", execute)
    monkeypatch.setattr(worker, "stop", False)
    task = asyncio.create_task(worker.worker_loop())
    try:
        await asyncio.wait_for(short_started.wait(), timeout=1.5)
        assert peak <= 4 and discovery_peak <= 2
    finally:
        monkeypatch.setattr(worker, "stop", True)
        release.set()
        await asyncio.wait_for(task, timeout=3)


def test_claim_can_reserve_capacity_and_avoid_same_target(env):
    with env() as db:
        db.add_all(
            [
                m.Job(kind="discovery", target_id="scope"),
                m.Job(kind="backup", target_id="busy"),
                m.Job(kind="identify", target_id="free"),
            ]
        )
        db.commit()
    id = worker.claim(interactive=False, exclude_kinds=("discovery",), exclude_targets=("busy",))
    with env() as db:
        assert db.get(m.Job, id).target_id == "free"
        assert db.get(m.Job, id).result["started_at"]
        assert len(list(db.scalars(select(m.Job).where(m.Job.status == "queued")))) == 2


async def test_worker_restart_requeues_background_work_but_user_cancel_does_not(env, monkeypatch):
    async def blocked(*args):
        await asyncio.Future()

    monkeypatch.setattr(worker, "discover", blocked)
    monkeypatch.setattr(worker, "stop", True)
    for cancel in (False, True):
        with env() as db:
            row = m.Job(
                kind="discovery",
                target_id="scope",
                status="running",
                active_key="discovery:scope",
                attempts=1,
                cancel_requested=cancel,
            )
            db.add(row)
            db.commit()
            id = row.id
        await worker.execute(id)
        with env() as db:
            row = db.get(m.Job, id)
            assert row.status == ("cancelled" if cancel else "queued")
            assert row.active_key == (None if cancel else "discovery:scope")
            db.delete(row)
            db.commit()
