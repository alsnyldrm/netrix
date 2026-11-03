"""CX SHA verification can outlive the native copy and must never replay the write."""

from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.core import now
from netrix.firmware import adapters, runtime, transfers
from sqlalchemy import select
from test_firmware import DIGEST, make_plan, start
from test_firmware import fw as firmware_fixture

fw = firmware_fixture


@pytest.mark.asyncio
async def test_cx_waits_past_sixty_seconds_for_device_digest_without_copying_again(monkeypatch, tmp_path):
    elapsed, deadlines, calls = 0, [], []
    digest = "a" * 64

    class Deadline:
        def __init__(self, seconds):
            self.seconds = seconds

        async def __aenter__(self):
            deadlines.append(elapsed + self.seconds)

        async def __aexit__(self, *args):
            deadlines.pop()

    class CLI:
        async def command(self, value, **kwargs):
            nonlocal elapsed
            calls.append(value)
            if value != "show images":
                return "Verifying and writing system firmware..."
            elapsed += 30
            if elapsed >= deadlines[-1]:
                raise TimeoutError()
            sha = "Verifying 50%" if elapsed < 120 else digest
            return f"AOS-CX Primary Image\nVersion : PL.10.18.1010\nSHA-256 : {sha}\nAOS-CX Secondary Image\nVersion : PL.10.17.1030\nSHA-256 : {'b' * 64}"

    async def sleep(_):
        pass

    monkeypatch.setattr(adapters.asyncio, "timeout", Deadline)
    monkeypatch.setattr(adapters.asyncio, "sleep", sleep)
    await adapters.stage(
        None,
        CLI(),
        SimpleNamespace(adapter="aruba_6100"),
        SimpleNamespace(version="PL.10.18.1010", sha256=digest),
        "primary",
        tmp_path / "unused",
        {"username": "fixture", "password": "fixture", "filename": "fixture.swi"},
    )
    assert elapsed == 120
    assert sum(command.startswith("copy ") for command in calls) == 1
    assert not any("boot" in command for command in calls)


@pytest.mark.parametrize("target,percent", [("primary", 50), ("secondary", None)])
def test_verification_progress_belongs_to_exact_area(target, percent):
    output = (
        "AOS-CX Primary Image\nVersion : PL.10.18.1010\nSHA-256 : Verifying 50%\nAOS-CX Secondary Image\nSHA-256 : "
        + "b" * 64
    )
    assert adapters.cx_image_progress(output, target) == percent


@pytest.mark.asyncio
async def test_pending_digest_timeout_is_not_reported_as_failed_transfer(monkeypatch):
    import asyncio

    timeout = asyncio.timeout
    monkeypatch.setattr(adapters.asyncio, "timeout", lambda _: timeout(0.01))

    class CLI:
        async def command(self, value):
            assert value == "show images"
            return "AOS-CX Primary Image\nVersion : PL.10.18.1010\nSHA-256 : Verifying 100%"

    with pytest.raises(adapters.FirmwareError) as result:
        await adapters.wait_cx_image(
            CLI(), "primary", SimpleNamespace(version="PL.10.18.1010", sha256="a" * 64)
        )
    assert result.value.code == "image_verification_timeout"


@pytest.mark.asyncio
async def test_completed_wrong_digest_fails_without_waiting_or_accepting_other_area():
    class CLI:
        async def command(self, value):
            return f"AOS-CX Primary Image\nVersion : PL.10.18.1010\nSHA-256 : {'b' * 64}\nAOS-CX Secondary Image\nVersion : PL.10.18.1010\nSHA-256 : {'a' * 64}"

    with pytest.raises(adapters.FirmwareError) as result:
        await adapters.wait_cx_image(
            CLI(), "primary", SimpleNamespace(version="PL.10.18.1010", sha256="a" * 64)
        )
    assert result.value.code == "image"


def cx_fixture(fw):
    with fw["sf"]() as db:
        for device in db.scalars(select(m.Device)):
            device.adapter, device.model, device.software_version = "aruba_6100", "JL675A", "PL.10.17.1030"
        image = db.get(m.FirmwareImage, fw["image"]["id"])
        image.family, image.models, image.version = "cx6100", ["JL675A"], "PL.10.18.1010"
        db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("reconciled", [False, True])
async def test_staged_plan_activation_starts_new_phase_after_read_only_recovery(fw, monkeypatch, reconciled):
    cx_fixture(fw)
    plan = make_plan(fw, "stage")
    start(fw, plan)
    running, booted, staged = {}, [], []

    class CLI:
        def __init__(self, device):
            self.device = device

        async def command(self, command, **kwargs):
            if command == "show version":
                return (
                    "Version : PL.10.18.1010\nActive Image : primary"
                    if self.device.id in running
                    else "Version : PL.10.17.1030\nActive Image : secondary"
                )
            assert command == "show images"
            return f"AOS-CX Primary Image\nVersion : PL.10.18.1010\nSHA-256 : {DIGEST}\nAOS-CX Secondary Image\nVersion : PL.10.17.1030\nSHA-256 : {'c' * 64}"

    @asynccontextmanager
    async def connection(device, *args, **kwargs):
        yield None, CLI(device)

    async def fetch(*args):
        return "!Version AOS-CX PL.10.17.1030\nhostname fixture\n"

    async def activate(cli, device, bank):
        assert bank == "primary" and device.id not in running
        running[device.id] = True
        booted.append(device.id)

    async def sleep(_):
        pass

    def prohibit(*args, **kwargs):
        raise AssertionError("Prepared activation must never copy firmware or create another backup")

    monkeypatch.setattr(adapters, "connect", connection)
    monkeypatch.setattr(adapters, "activate", activate)
    monkeypatch.setattr(adapters, "stage", prohibit)
    monkeypatch.setattr(transfers, "grant", prohibit)
    monkeypatch.setattr(runtime, "fetch_config", fetch)
    monkeypatch.setattr(runtime.asyncio, "sleep", sleep)
    while target_id := runtime.claim():
        await runtime.execute(target_id)
        staged.append(target_id)
    assert len(staged) == 3 and not booted

    first = staged[0]
    if reconciled:
        # This image was successfully repaired read-only after a historic copy error.
        runtime.set_phase(first, "transferring")
        runtime.finish(first, "attention", error_code="image")
        assert fw["client"].post(f"/api/v1/firmware/targets/{first}/verify").status_code == 200
        assert runtime.claim() == first
        await runtime.execute(first)
        assert runtime.claim() is None
        with fw["sf"]() as db:
            assert db.get(m.FirmwareTarget, first).phase == "reconcile"
            assert db.get(m.FirmwarePlan, plan["id"]).status == "paused"
        assert fw["client"].post(f"/api/v1/firmware/plans/{plan['id']}/retry").status_code == 200
        assert runtime.claim() is None

    with fw["sf"]() as db:
        snapshots = {t.id: t.snapshot_id for t in db.scalars(select(m.FirmwareTarget))}
        old_events = db.scalar(select(m.FirmwareEvent.id).order_by(m.FirmwareEvent.id.desc()).limit(1))
    monkeypatch.setattr(runtime, "fetch_config", prohibit)
    response = fw["client"].post(f"/api/v1/firmware/plans/{plan['id']}/activate")
    assert response.status_code == 200, response.text
    assert fw["client"].post(f"/api/v1/firmware/plans/{plan['id']}/activate").status_code == 409
    with fw["sf"]() as db:
        for row in db.scalars(select(m.FirmwareTarget)):
            assert row.phase == "waiting" and row.finished_at is None
            assert row.error_code == row.error == row.verified_version == ""
    while target_id := runtime.claim():
        await runtime.execute(target_id)
    assert len(booted) == len(set(booted)) == 3
    with fw["sf"]() as db:
        assert db.get(m.FirmwarePlan, plan["id"]).status == "succeeded"
        for row in db.scalars(select(m.FirmwareTarget)):
            assert row.status == "succeeded" and row.verified_version == "PL.10.18.1010"
            assert row.snapshot_id == snapshots[row.id]
            assert db.get(m.Device, row.device_id).software_version == "PL.10.18.1010"
        assert db.get(m.FirmwareEvent, old_events)
        if reconciled:
            assert db.get(m.FirmwareTarget, first).evidence["operation_error"]["code"] == "image"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["good", "wrong_hash", "changed_running", "missing_backup"])
async def test_stage_reconciliation_checks_stored_image_without_running_it(fw, monkeypatch, case):
    cx_fixture(fw)
    plan = make_plan(fw, "stage")
    start(fw, plan)
    target_id = runtime.claim()
    prepared, reads, forbidden = False, [], []

    class CLI:
        async def command(self, command, **kwargs):
            reads.append(command)
            if command == "show version":
                version = "PL.10.13.1005" if prepared and case == "changed_running" else "PL.10.17.1030"
                return f"Version : {version}\nActive Image : secondary"
            assert command == "show images"
            version = "PL.10.18.1010" if prepared else "PL.10.13.1005"
            digest = "b" * 64 if case == "wrong_hash" else DIGEST
            return f"AOS-CX Primary Image\nVersion : {version}\nSHA-256 : {digest}\nAOS-CX Secondary Image\nVersion : PL.10.17.1030\nSHA-256 : {'c' * 64}"

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield None, CLI()

    async def fetch(*args):
        return "!Version AOS-CX PL.10.17.1030\nhostname fixture\n"

    async def legacy_copy_timeout(*args):
        nonlocal prepared
        prepared = True
        raise adapters.FirmwareError("image")

    monkeypatch.setattr(adapters, "connect", connection)
    monkeypatch.setattr(adapters, "stage", legacy_copy_timeout)
    monkeypatch.setattr(runtime, "fetch_config", fetch)
    await runtime.execute(target_id)
    with fw["sf"]() as db:
        row = db.get(m.FirmwareTarget, target_id)
        assert row.status == "attention" and row.snapshot_id and row.previous_bank == "secondary"
        if case == "missing_backup":
            row.snapshot_id = None
            db.commit()

    def prohibit(*args, **kwargs):
        forbidden.append(True)
        raise AssertionError("Read-only reconciliation must never copy, back up, or reboot")

    monkeypatch.setattr(adapters, "stage", prohibit)
    monkeypatch.setattr(adapters, "activate", prohibit)
    monkeypatch.setattr(transfers, "grant", prohibit)
    monkeypatch.setattr(runtime, "fetch_config", prohibit)
    assert fw["client"].post(f"/api/v1/firmware/targets/{target_id}/verify").status_code == 200
    assert runtime.claim() == target_id
    await runtime.execute(target_id)
    assert runtime.claim() is None
    assert not forbidden
    with fw["sf"]() as db:
        row = db.get(m.FirmwareTarget, target_id)
        assert db.get(m.FirmwarePlan, plan["id"]).status == "paused"
        assert (
            sum(
                t.status == "queued"
                for t in db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == plan["id"]))
            )
            == 2
        )
        assert row.active_device and row.verified_version == ""
        if case == "good":
            assert row.status == "staged", row.error
            assert row.error_code == "" and row.evidence["staged"]
            assert row.evidence["staged_sha256"] == DIGEST
        else:
            assert row.status == "attention"
            assert (
                row.evidence["verification_error"]["code"]
                == {
                    "wrong_hash": "image",
                    "changed_running": "connection_changed",
                    "missing_backup": "not_staged",
                }[case]
            )


def test_interrupted_image_verification_keeps_device_reserved(fw):
    plan = make_plan(fw, "stage")
    start(fw, plan)
    target = runtime.claim()
    runtime.set_phase(target, "image_verifying")
    with fw["sf"]() as db:
        db.get(m.FirmwareTarget, target).heartbeat_at = now() - timedelta(minutes=5)
        db.commit()
    assert runtime.claim() is None
    with fw["sf"]() as db:
        row = db.get(m.FirmwareTarget, target)
        assert row.status == "attention" and row.active_device


@pytest.mark.asyncio
async def test_pending_existing_image_finishes_verification_without_reupload(fw, monkeypatch):
    cx_fixture(fw)
    plan = make_plan(fw, "stage")
    start(fw, plan)
    target = runtime.claim()
    forbidden = []

    class CLI:
        async def command(self, command, **kwargs):
            if command == "show version":
                return "Version : PL.10.17.1030\nActive Image : secondary"
            return f"AOS-CX Primary Image\nVersion : PL.10.18.1010\nSHA-256 : {DIGEST}"

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield None, CLI()

    async def inspect(*args):
        return {
            "version": "PL.10.17.1030",
            "bank": "secondary",
            "banks": "AOS-CX Primary Image\nVersion : PL.10.18.1010\nSHA-256 : Verifying 50%",
        }

    async def fetch(*args):
        return "!Version AOS-CX PL.10.17.1030\nhostname fixture\n"

    def prohibit(*args, **kwargs):
        forbidden.append(True)
        raise AssertionError("Pending image must not be copied again")

    monkeypatch.setattr(adapters, "connect", connection)
    monkeypatch.setattr(adapters, "inspect", inspect)
    monkeypatch.setattr(runtime, "fetch_config", fetch)
    monkeypatch.setattr(adapters, "stage", prohibit)
    monkeypatch.setattr(adapters, "activate", prohibit)
    monkeypatch.setattr(transfers, "grant", prohibit)
    await runtime.execute(target)
    assert not forbidden
    with fw["sf"]() as db:
        row = db.get(m.FirmwareTarget, target)
        assert row.status == "staged", row.error
        assert row.evidence["transfer_reused"] and row.transfer_bytes == 0
        assert row.snapshot_id and row.evidence["image_verification_percent"] == 100
