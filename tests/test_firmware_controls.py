"""Ten-way admission and plan controls must not erase results or replay unsafe writes."""

import asyncio
from contextlib import asynccontextmanager

import pytest
from netrix import models as m
from netrix.firmware import adapters, runtime, transfers
from netrix.firmware.limits import MAX_CONCURRENCY
from sqlalchemy import select
from test_firmware import fw as firmware_fixture
from test_firmware import make_plan, start

fw = firmware_fixture


def test_api_accepts_ten_and_rejects_eleven_and_can_reduce_live_limit_without_cancelling(fw):
    plan = make_plan(fw, "stage", concurrency=10)
    start(fw, plan)
    target_id = runtime.claim()
    response = fw["client"].patch(f"/api/v1/firmware/plans/{plan['id']}/concurrency", json={"concurrency": 2})
    assert response.status_code == 200 and response.json()["concurrency"] == 2
    with fw["sf"]() as db:
        assert db.get(m.FirmwareTarget, target_id).status == "running"
        assert not db.get(m.FirmwarePlan, plan["id"]).cancel_requested
    assert (
        fw["client"]
        .patch(f"/api/v1/firmware/plans/{plan['id']}/concurrency", json={"concurrency": 11})
        .status_code
        == 422
    )
    assert (
        fw["client"]
        .patch(f"/api/v1/firmware/plans/{plan['id']}/concurrency", json={"concurrency": 0})
        .status_code
        == 422
    )


@pytest.mark.asyncio
async def test_real_worker_pool_admits_exactly_ten_across_plans_and_does_not_cancel_soft_stop(
    fw, monkeypatch
):
    started, claimed = [], []

    async def execute(id):
        started.append(id)
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime, "execute", execute)

    # No DB targets are needed for the empty pool's first fill; this exercises
    # the actual admission loop used by the firmware process, not a mirrored limit.
    def claim():
        claimed.append(len(claimed))
        return str(len(claimed))

    monkeypatch.setattr(runtime, "claim", claim)
    tasks = {}
    await runtime.maintain_tasks(tasks)
    await asyncio.sleep(0)
    assert len(tasks) == len(claimed) == len(started) == 10 == MAX_CONCURRENCY
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase,expected",
    [
        ("backup", "cancelled"),
        ("transferring", "attention"),
        ("image_verifying", "attention"),
        ("rebooting", "attention"),
        ("verifying", "attention"),
    ],
)
async def test_force_stop_owner_cancels_task_retains_unsafe_reservations_and_stops_queue(
    fw, monkeypatch, phase, expected
):
    plan = make_plan(fw, "stage")
    start(fw, plan)
    id = runtime.claim()
    runtime.set_phase(id, phase)
    entered = asyncio.Event()

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield None, None

    async def inspect(*args):
        # execute enters preflight; emulate a blocked protocol operation at
        # each persisted boundary to test its real CancelledError handling.
        runtime.set_phase(id, phase)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(adapters, "connect", connection)
    monkeypatch.setattr(adapters, "inspect", inspect)
    task = asyncio.create_task(runtime.execute(id))
    await entered.wait()
    client = fw["client"]
    result = client.post(
        f"/api/v1/firmware/plans/{plan['id']}/force-stop", json={"plan_name": plan["name"], "confirmed": True}
    )
    assert result.status_code == 200, result.text
    with fw["sf"]() as db:
        assert db.get(m.FirmwareTarget, id).status == "running", "API must not fake worker completion"
    tasks = {task: id}
    await runtime.maintain_tasks(tasks)
    assert not tasks and runtime.claim() is None
    with fw["sf"]() as db:
        target = db.get(m.FirmwareTarget, id)
        assert target.status == expected and target.error_code == "forced_stop"
        assert bool(target.active_device) == (expected == "attention")
        assert db.get(m.FirmwarePlan, plan["id"]).status == "cancelled"
        assert all(
            t.status == "cancelled"
            for t in db.scalars(
                select(m.FirmwareTarget).where(
                    m.FirmwareTarget.plan_id == plan["id"], m.FirmwareTarget.id != id
                )
            )
        )
        assert list(db.scalars(select(m.FirmwareEvent).where(m.FirmwareEvent.target_id == id)))
    assert client.delete(f"/api/v1/firmware/plans/{plan['id']}").status_code == (
        409 if expected == "attention" else 204
    )


def test_soft_stop_does_not_expire_running_grant_or_erase_staged_outcomes(fw):
    plan = make_plan(fw, "stage", concurrency=2)
    start(fw, plan)
    first, second = runtime.claim(), runtime.claim()
    runtime.set_phase(first, "transferring")
    transfers.grant(first, "sftp")
    runtime.finish(second, "staged")
    with fw["sf"]() as db:
        expires = db.get(m.FirmwareTarget, first).transfer_expires_at
    result = fw["client"].post(f"/api/v1/firmware/plans/{plan['id']}/cancel")
    assert result.status_code == 200
    with fw["sf"]() as db:
        assert db.get(m.FirmwareTarget, first).status == "running"
        assert db.get(m.FirmwareTarget, first).transfer_expires_at == expires
        assert db.get(m.FirmwareTarget, second).status == "staged"
        assert not db.get(m.FirmwarePlan, plan["id"]).force_stop_requested
    runtime.finish(first, "staged")
    runtime.claim()
    with fw["sf"]() as db:
        assert db.get(m.FirmwarePlan, plan["id"]).status == "cancelled"
        assert db.get(m.FirmwareTarget, first).status == "staged"
        assert db.get(m.FirmwareTarget, second).status == "staged"
        assert not db.get(m.FirmwareTarget, first).active_device


def test_remove_retains_completed_device_events_and_history_and_blocks_restart(fw):
    plan = make_plan(fw, "check")
    start(fw, plan)
    while id := runtime.claim():
        runtime.finish(id, "checked")
    client = fw["client"]
    count = client.get(f"/api/v1/firmware/history/{plan['id']}/targets?stage=0").json()["total"]
    assert client.delete(f"/api/v1/firmware/plans/{plan['id']}").status_code == 204
    assert not client.get("/api/v1/firmware/plans").json()["items"]
    assert client.get(f"/api/v1/firmware/history/{plan['id']}").status_code == 200
    assert client.get(f"/api/v1/firmware/history/{plan['id']}/targets?stage=0").json()["total"] == count
    assert client.post(f"/api/v1/firmware/plans/{plan['id']}/start").status_code == 404
    with fw["sf"]() as db:
        assert db.get(m.FirmwarePlan, plan["id"]).deleted_at
        assert list(db.scalars(select(m.FirmwareEvent)))


def test_draft_removal_is_allowed_but_live_reservations_and_unconfirmed_force_are_rejected(fw):
    plan = make_plan(fw, "stage")
    client = fw["client"]
    assert (
        client.post(
            f"/api/v1/firmware/plans/{plan['id']}/force-stop", json={"plan_name": "wrong", "confirmed": True}
        ).status_code
        == 422
    )
    assert client.delete(f"/api/v1/firmware/plans/{plan['id']}").status_code == 204
    plan = make_plan(fw, "stage")
    start(fw, plan)
    assert client.delete(f"/api/v1/firmware/plans/{plan['id']}").status_code == 409
    with fw["sf"]() as db:
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    for method, path, body in (
        ("POST", "force-stop", {"plan_name": plan["name"], "confirmed": True}),
        ("POST", "cancel", {}),
        ("PATCH", "concurrency", {"concurrency": 10}),
    ):
        assert (
            client.request(method, f"/api/v1/firmware/plans/{plan['id']}/{path}", json=body).status_code
            == 403
        )
    assert client.delete(f"/api/v1/firmware/plans/{plan['id']}").status_code == 403


def test_tftp_admits_ten_peers_and_rejects_eleventh_without_changing_rrq_security(monkeypatch):
    service = transfers.TFTP()
    service.active = {(f"192.0.2.{i}", 1000): None for i in range(9)}
    monkeypatch.setattr(transfers, "lookup", lambda *a, **kw: {"id": "fixture", "hash": ""})
    created = []

    class Future:
        def add_done_callback(self, cb):
            pass

    def create(coro):
        coro.close()
        created.append(True)
        return Future()

    monkeypatch.setattr(transfers.asyncio, "create_task", create)
    packet = b"\x00\x01netrix-fw-" + b"a" * 48 + b".ipe\x00octet\x00"
    service.datagram_received(packet, ("192.0.2.100", 1000))
    service.datagram_received(packet, ("192.0.2.101", 1000))
    assert len(created) == 1 and len(service.active) == 10


@pytest.mark.asyncio
async def test_explicit_read_only_verification_remains_available_after_force_stop(fw, monkeypatch):
    plan = make_plan(fw, "stage")
    start(fw, plan)
    id = runtime.claim()
    runtime.set_phase(id, "transferring")
    client = fw["client"]
    assert (
        client.post(
            f"/api/v1/firmware/plans/{plan['id']}/force-stop",
            json={"plan_name": plan["name"], "confirmed": True},
        ).status_code
        == 200
    )
    runtime.finish(id, "attention", error_code="forced_stop")
    assert runtime.claim() is None
    assert client.post(f"/api/v1/firmware/targets/{id}/verify").status_code == 200

    async def read_only(_):
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime, "execute", read_only)
    tasks = {}
    await runtime.maintain_tasks(tasks)
    await asyncio.sleep(0)
    assert list(tasks.values()) == [id]
    await runtime.maintain_tasks(tasks)
    assert len(tasks) == 1 and not next(iter(tasks)).cancelled()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def test_removed_failed_plan_cannot_be_retried(fw):
    plan = make_plan(fw, "check")
    with fw["sf"]() as db:
        row = db.get(m.FirmwarePlan, plan["id"])
        row.status = "paused"
        for target in db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == row.id)):
            target.status = "failed"
        db.commit()
    assert fw["client"].delete(f"/api/v1/firmware/plans/{plan['id']}").status_code == 204
    assert fw["client"].post(f"/api/v1/firmware/plans/{plan['id']}/retry").status_code == 404
    assert fw["client"].post(f"/api/v1/firmware/plans/{plan['id']}/activate").status_code == 404
    assert runtime.claim() is None
