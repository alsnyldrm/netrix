import asyncio
from collections import deque

from netrix import worker


async def test_blacklist_has_five_independent_slots_and_admits_sixth_after_completion(monkeypatch):
    pending = deque(range(6))
    release = [asyncio.Event() for _ in range(6)]
    started = []
    full = asyncio.Event()
    sixth = asyncio.Event()
    beats = []
    claims = []
    active = 0
    peak = 0

    def claim(**kwargs):
        claims.append(kwargs)
        return str(pending.popleft()) if pending else None

    async def execute(job_id, *, heartbeat_role):
        nonlocal active, peak
        assert heartbeat_role == "blacklist"
        index = int(job_id)
        started.append(index)
        active += 1
        peak = max(peak, active)
        if len(started) == 5:
            full.set()
        if index == 5:
            sixth.set()
        try:
            await release[index].wait()
        finally:
            active -= 1

    monkeypatch.setattr(worker, "stop", False)
    monkeypatch.setattr(worker, "claim", claim)
    monkeypatch.setattr(worker, "execute", execute)
    monkeypatch.setattr(worker, "heartbeat", beats.append)
    loop = asyncio.create_task(worker.blacklist_loop())
    try:
        await asyncio.wait_for(full.wait(), 3)
        assert started == list(range(5))
        assert list(pending) == [5]
        release[0].set()
        await asyncio.wait_for(sixth.wait(), 3)
        assert peak == 5
        assert all(c == {"interactive": False, "include_kinds": ("blacklist_send",)} for c in claims)
        assert beats and set(beats) == {"blacklist"}
    finally:
        worker.stop = True
        for event in release:
            event.set()
        await asyncio.wait_for(loop, 3)


async def test_background_worker_excludes_blacklist_when_other_slots_are_available(monkeypatch):
    calls = []

    def claim(**kwargs):
        calls.append(kwargs)
        if "exclude_kinds" in kwargs:
            worker.stop = True
        return None

    monkeypatch.setattr(worker, "stop", False)
    monkeypatch.setattr(worker, "claim", claim)
    monkeypatch.setattr(worker, "heartbeat", lambda *_: None)
    await asyncio.wait_for(worker.worker_loop(), 3)
    assert "blacklist_send" in calls[-1]["exclude_kinds"]
