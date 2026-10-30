import asyncio
from datetime import timedelta

import pytest
from netrix import models as m
from netrix import worker
from netrix.core import now
from netrix.discovery import interactive_tests
from netrix.services import enqueue
from sqlalchemy import select
from test_connection_tests import device_with_profiles


def submit(client, device):
    return client.post(f"/api/v1/devices/{device['id']}/connection-tests", json={"protocol": "snmpv3"})


def test_interactive_claim_ignores_bulk_and_background_and_is_idempotent(admin_client, inventory, env):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])
    with env() as db:
        backup = m.Job(kind="backup", target_id=device["id"])
        db.add(backup)
        db.commit()
        backup_id = backup.id
    response = submit(admin_client, device)
    assert response.status_code == 202, response.text
    assert response.json()["result"]["interactive"] is True
    assert submit(admin_client, device).json()["id"] == response.json()["id"]
    assert worker.claim(interactive=False) == backup_id
    assert worker.claim(interactive=False) is None
    assert worker.claim(interactive=True) == response.json()["id"]
    assert worker.claim(interactive=True) is None


def test_pending_bulk_probe_is_promoted_instead_of_waiting(admin_client, inventory, env):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])
    with env() as db:
        job = enqueue(db, "test_snmp", device["id"])
        job.available_at = now() + timedelta(minutes=5)
        db.commit()
        id = job.id
    response = submit(admin_client, device)
    assert response.status_code == 202 and response.json()["id"] == id
    assert worker.claim(interactive=False) is None
    assert worker.claim(interactive=True) == id


@pytest.mark.parametrize("state", ["queued", "running"])
def test_full_capacity_rejects_without_leaving_a_job(admin_client, inventory, env, state):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])
    with env() as db:
        db.add_all(
            [
                m.Job(
                    kind="test_ssh",
                    target_id=device["id"],
                    status=state,
                    result={"interactive": True},
                    heartbeat_at=now(),
                )
                for _ in range(4)
            ]
        )
        db.commit()
    response = submit(admin_client, device)
    assert response.status_code == 429
    assert "sıraya alınmadı" in response.json()["detail"]
    with env() as db:
        assert not db.scalar(select(m.Job).where(m.Job.active_key == f"test_snmp:{device['id']}"))


@pytest.mark.parametrize("value", [None, "invalid", (now() - timedelta(minutes=1)).isoformat()])
def test_worker_unavailable_rejects_without_queue(admin_client, inventory, env, value):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])
    interactive_tests.redis_client().set("netrix:tests:heartbeat", value)
    assert submit(admin_client, device).status_code == 503
    with env() as db:
        assert not db.scalar(select(m.Job).where(m.Job.active_key == f"test_snmp:{device['id']}"))


async def test_test_starts_while_background_work_is_blocked(admin_client, inventory, env, monkeypatch):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])
    with env() as db:
        blocked = m.Job(kind="backup", target_id=device["id"], status="running", heartbeat_at=now())
        db.add(blocked)
        db.commit()
        blocked_id = blocked.id
    job = submit(admin_client, device).json()
    started, release = asyncio.Event(), asyncio.Event()

    async def probe(*args):
        started.set()
        await release.wait()
        return "fixture probe completed"

    monkeypatch.setattr(worker, "probe_connection", probe)
    monkeypatch.setattr(worker, "stop", False)
    pool = asyncio.create_task(worker.interactive_test_loop())
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        with env() as db:
            assert db.get(m.Job, job["id"]).status == "running"
            assert db.get(m.Job, blocked_id).status == "running"
        release.set()
        for _ in range(100):
            with env() as db:
                if db.get(m.Job, job["id"]).status == "succeeded":
                    break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("Interactive probe did not finish")
    finally:
        release.set()
        monkeypatch.setattr(worker, "stop", True)
        await asyncio.wait_for(pool, timeout=2)


async def test_interactive_internal_failure_does_not_backoff_into_queue(
    admin_client, inventory, env, monkeypatch
):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])
    job = submit(admin_client, device).json()
    worker.claim(interactive=True)

    async def broken(*args):
        raise OSError("private transport data")

    monkeypatch.setattr(worker, "test_device_connection", broken)
    await worker.execute(job["id"], heartbeat_role="tests")
    with env() as db:
        row = db.get(m.Job, job["id"])
        assert row.status == "failed" and row.active_key is None
        assert "private transport data" not in row.error


def test_dead_interactive_probe_is_failed_not_requeued(admin_client, inventory, env):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])
    job = submit(admin_client, device).json()
    worker.claim(interactive=True)
    with env() as db:
        db.get(m.Job, job["id"]).heartbeat_at = now() - timedelta(minutes=2)
        db.commit()
    assert worker.claim(interactive=True) is None
    with env() as db:
        row = db.get(m.Job, job["id"])
        assert row.status == "failed" and row.active_key is None
