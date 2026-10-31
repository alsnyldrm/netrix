import asyncio
import hashlib

import pytest
from netrix import models as m
from netrix import worker
from netrix.configuration import management
from netrix.core import now
from netrix.discovery import interactive_tests
from netrix.identity.security import encrypt
from sqlalchemy import select
from test_fortios_backups import NATIVE, make_device


@pytest.fixture
def snapshot(admin_client, inventory, env):
    device, _ = make_device(admin_client, inventory)
    with env() as db:
        job = m.Job(kind="backup", target_id=device["id"], status="succeeded")
        db.add(job)
        db.flush()
        row = m.Snapshot(
            device_id=device["id"],
            job_id=job.id,
            encrypted_content=encrypt(NATIVE),
            fingerprint=hashlib.sha256(NATIVE.encode()).hexdigest(),
            size_bytes=len(NATIVE),
        )
        db.add(row)
        db.commit()
        return row.id, device["id"]


def submit(client, snapshot):
    return client.post(f"/api/v1/snapshots/{snapshot[0]}/compare-live")


async def test_comparison_starts_during_long_discovery(admin_client, env, snapshot, monkeypatch):
    with env() as db:
        blocked = m.Job(kind="discovery", target_id=snapshot[1], status="running", heartbeat_at=now())
        db.add(blocked)
        db.commit()
        blocked_id = blocked.id
    response = submit(admin_client, snapshot)
    assert response.status_code == 202
    job = response.json()
    assert job["result"]["interactive"] is True
    assert submit(admin_client, snapshot).json()["id"] == job["id"]
    started = asyncio.Event()

    async def fetch(*args):
        started.set()
        return NATIVE

    monkeypatch.setattr(management, "fetch_config", fetch)
    monkeypatch.setattr(worker, "stop", False)
    pool = asyncio.create_task(worker.interactive_test_loop())
    try:
        await asyncio.wait_for(started.wait(), 1)
        for _ in range(100):
            with env() as db:
                current = db.get(m.Job, job["id"])
                assert db.get(m.Job, blocked_id).status == "running"
                if current.status == "succeeded":
                    assert current.result["changed"] is False
                    break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("Comparison did not finish independently of discovery")
    finally:
        monkeypatch.setattr(worker, "stop", True)
        await asyncio.wait_for(pool, 2)


@pytest.mark.parametrize("unavailable", ["full", "offline"])
def test_unavailable_comparison_rejected_without_queue(admin_client, env, snapshot, unavailable):
    if unavailable == "offline":
        interactive_tests.redis_client().set("netrix:tests:heartbeat", None)
    else:
        with env() as db:
            db.add_all(
                [
                    m.Job(
                        kind="test_ssh",
                        target_id=snapshot[1],
                        status="running",
                        heartbeat_at=now(),
                        result={"interactive": True},
                    )
                    for _ in range(4)
                ]
            )
            db.commit()
    response = submit(admin_client, snapshot)
    assert response.status_code == (503 if unavailable == "offline" else 429)
    with env() as db:
        assert db.scalar(select(m.Job).where(m.Job.kind == "compare")) is None


async def test_comparison_timeout_is_terminal_without_retries(admin_client, env, snapshot, monkeypatch):
    job = submit(admin_client, snapshot).json()
    assert worker.claim(interactive=True) == job["id"]

    async def fetch(*args):
        raise TimeoutError()

    monkeypatch.setattr(management, "fetch_config", fetch)
    await worker.execute(job["id"], heartbeat_role="tests")
    with env() as db:
        row = db.get(m.Job, job["id"])
        assert row.status == "failed" and row.active_key is None and row.attempts == 1
        assert row.result["error_code"] == "ssh_timeout"


def test_active_comparison_rejects_different_baseline(admin_client, env, snapshot):
    first = submit(admin_client, snapshot).json()
    with env() as db:
        old = db.get(m.Snapshot, snapshot[0])
        backup = m.Job(kind="backup", target_id=old.device_id, status="succeeded")
        db.add(backup)
        db.flush()
        other = m.Snapshot(
            device_id=old.device_id,
            job_id=backup.id,
            encrypted_content=old.encrypted_content,
            fingerprint=old.fingerprint,
            size_bytes=old.size_bytes,
        )
        db.add(other)
        db.commit()
        other_id = other.id
    response = submit(admin_client, (other_id, snapshot[1]))
    assert response.status_code == 409
    with env() as db:
        assert db.get(m.Job, first["id"]).result["base_snapshot_id"] == snapshot[0]


async def test_running_comparison_cancels_promptly(admin_client, env, snapshot, monkeypatch):
    job = submit(admin_client, snapshot).json()
    assert worker.claim(interactive=True) == job["id"]
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def fetch(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(management, "fetch_config", fetch)
    task = asyncio.create_task(worker.execute(job["id"], heartbeat_role="tests"))
    await asyncio.wait_for(started.wait(), 1)
    response = admin_client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert response.status_code == 200
    await asyncio.wait_for(task, 2)
    assert cancelled.is_set()
    with env() as db:
        row = db.get(m.Job, job["id"])
        assert row.status == "cancelled" and row.active_key is None
