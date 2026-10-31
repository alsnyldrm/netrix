"""A global pause blocks every producer without rewriting device preferences."""

from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now, settings
from netrix.scheduler import tick
from netrix.worker import claim, execute
from sqlalchemy import select


def pause(monkeypatch):
    monkeypatch.setenv("NETRIX_MONITOR_JOBS_ENABLED", "false")
    settings.cache_clear()


def device(env, inventory):
    with env() as db:
        row = m.Device(
            name="Fixture",
            management_ip="192.0.2.1",
            vrf_id=inventory["vrf"]["id"],
            snmp_credential_id=inventory["credential"]["id"],
            monitoring_enabled=True,
        )
        db.add(row)
        db.commit()
        return row.id


def test_pause_blocks_api_and_scheduler_preserves_device_and_other_jobs(
    admin_client, inventory, env, monkeypatch
):
    id = device(env, inventory)
    pause(monkeypatch)
    response = admin_client.post("/api/v1/jobs", json={"kind": "monitor", "target_id": id})
    assert response.status_code == 409 and "geçici olarak kapalı" in response.text
    from netrix import scheduler

    evaluations = []
    monkeypatch.setattr(scheduler, "evaluate", lambda *args: evaluations.append(args))
    tick()
    tick()
    assert not evaluations  # Deliberately paused sampling must not cause no-data alerts.
    with env() as db:
        assert db.get(m.Device, id).monitoring_enabled is True
        assert db.scalar(select(m.Job.id).where(m.Job.kind == "monitor")) is None
    assert (
        admin_client.post(
            "/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]}
        ).status_code
        == 202
    )
    monkeypatch.setenv("NETRIX_MONITOR_JOBS_ENABLED", "true")
    settings.cache_clear()
    assert admin_client.post("/api/v1/jobs", json={"kind": "monitor", "target_id": id}).status_code == 202


@pytest.mark.parametrize("cancel_via", ["claim", "scheduler"])
def test_pending_jobs_cancelled_running_requested_and_history_preserved(
    admin_client, inventory, env, monkeypatch, cancel_via
):
    id = device(env, inventory)
    with env() as db:
        rows = [
            m.Job(
                kind="monitor",
                target_id=id,
                status=status,
                active_key=f"fixture:{status}" if status in ("queued", "running") else None,
                heartbeat_at=now(),
            )
            for status in ("queued", "running", "succeeded")
        ]
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
    pause(monkeypatch)
    if cancel_via == "claim":
        assert claim() is None
    else:
        tick()
    with env() as db:
        queued, running, history = [db.get(m.Job, id) for id in ids]
        assert queued.status == "cancelled" and queued.active_key is None and queued.finished_at
        assert running.status == "running" and running.cancel_requested
        assert history.status == "succeeded" and not history.cancel_requested
        running.heartbeat_at = now() - timedelta(seconds=100)
        db.commit()
    assert claim() is None
    with env() as db:
        assert db.get(m.Job, ids[1]).status == "cancelled"


async def test_already_claimed_job_does_not_query_a_device_when_paused(
    admin_client, inventory, env, monkeypatch
):
    id = device(env, inventory)
    job = admin_client.post("/api/v1/jobs", json={"kind": "monitor", "target_id": id}).json()
    assert claim() == job["id"]
    pause(monkeypatch)

    class Collector:
        calls = 0

        async def collect(self, *args):
            self.calls += 1
            raise AssertionError("Paused monitor must never query a device")

    collector = Collector()
    await execute(job["id"], collector)
    assert collector.calls == 0
    assert admin_client.get("/api/v1/jobs/" + job["id"]).json()["status"] == "cancelled"


async def test_ipam_discovery_does_not_spawn_monitor_jobs_during_pause(
    admin_client, inventory, env, monkeypatch
):
    device(env, inventory)
    p = admin_client.post(
        "/api/v1/prefixes", json={"cidr": "192.0.2.0/30", "vrf_id": inventory["vrf"]["id"]}
    ).json()
    response = admin_client.put(
        f"/api/v1/ipam/prefixes/{p['id']}/settings", json={"scope_id": inventory["scope"]["id"]}
    )
    assert response.status_code == 200, response.text
    from netrix.ipam import adapters

    async def ping(address):
        return False

    monkeypatch.setattr(adapters, "ping", ping)
    pause(monkeypatch)
    response = admin_client.post(f"/api/v1/ipam/prefixes/{p['id']}/discover")
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    cached_job = claim()
    with env() as db:
        assert db.get(m.Job, cached_job).kind == "ipam_inventory"
    await execute(cached_job)  # Cached data replay remains allowed while monitoring is paused.
    assert claim() == job_id
    await execute(job_id)
    result = admin_client.get("/api/v1/jobs/" + job_id).json()
    assert result["status"] == "succeeded", result
    assert result["result"]["source_jobs"] == []
    with env() as db:
        assert db.scalar(select(m.Job.id).where(m.Job.kind == "monitor")) is None
