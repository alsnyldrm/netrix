"""Firmware safety, durable sequencing and real adapter I/O with fake devices."""

import hashlib
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import asyncssh
import pytest
from netrix import models as m
from netrix.core import now, settings
from netrix.firmware import adapters, runtime, transfers
from netrix.firmware.service import image_path
from netrix.identity.security import encrypt
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

CONTENT = b"vendor firmware fixture\x00\xff"
DIGEST = hashlib.sha256(CONTENT).hexdigest()


@pytest.mark.parametrize("code", [1020, 1205, 1213])
def test_competing_reservation_rolls_back_and_returns_conflict(code):
    from fastapi import HTTPException
    from netrix.firmware.service import start_plan

    rolled_back = []

    def conflicting_read(*args):
        raise OperationalError("redacted", {}, Exception(code, "fixture conflict"))

    db = SimpleNamespace(scalar=conflicting_read, rollback=lambda: rolled_back.append(True))
    with pytest.raises(HTTPException) as result:
        start_plan(db, SimpleNamespace(id="fixture"), None)
    assert result.value.status_code == 409
    assert rolled_back == [True]


@pytest.fixture
def fw(admin_client, inventory, env, tmp_path, monkeypatch):
    monkeypatch.setenv("NETRIX_FIRMWARE_DIRECTORY", str(tmp_path / "firmware"))
    monkeypatch.setenv("NETRIX_FIRMWARE_ADVERTISE_HOST", "192.0.2.100")
    settings.cache_clear()
    monkeypatch.setattr("netrix.firmware.api.shutil.disk_usage", lambda _: SimpleNamespace(free=2 * 1024**3))
    with env() as db:
        credential = m.Credential(
            name="Firmware SSH",
            protocol="ssh",
            encrypted_secret=encrypt('{"username":"fixture","password":"not-for-output"}'),
        )
        db.add(credential)
        db.flush()
        devices = [
            m.Device(
                name=f"Switch {i}",
                management_ip=f"192.0.2.{i + 1}",
                model="JL256A",
                vendor="Aruba",
                adapter="aruba_2900",
                vrf_id=inventory["vrf"]["id"],
                discovery_scope_id=inventory["scope"]["id"],
                config_credential_id=credential.id,
                software_version="WC.16.10.0025",
            )
            for i in range(3)
        ]
        db.add_all(devices)
        db.commit()
    c = admin_client
    response = c.post(
        "/api/v1/firmware/images",
        json={
            "name": "2930",
            "family": "aos_s",
            "version": "WC.16.11.0026",
            "models": ["JL256A"],
            "original_name": "WC_16_11_0026.swi",
            "expected_sha256": DIGEST,
        },
    )
    assert response.status_code == 201, response.text
    image = response.json()
    assert c.put(f"/api/v1/firmware/images/{image['id']}/content", content=CONTENT).status_code == 200
    groups = []
    for i, ids in enumerate(([d.id for d in devices[:2]], [devices[2].id])):
        response = c.post("/api/v1/firmware/groups", json={"name": f"Role {i}", "device_ids": ids})
        assert response.status_code == 201, response.text
        groups.append(response.json())
    return {"client": c, "sf": env, "devices": devices, "image": image, "groups": groups}


def make_plan(fw, mode="check", **extra):
    payload = {
        "name": "Ordered rollout",
        "mode": mode,
        "steps": [{"group_id": g["id"], "image_id": fw["image"]["id"]} for g in fw["groups"]],
        "acknowledge_upgrade_path": True,
        "acknowledge_outage": True,
        **extra,
    }
    response = fw["client"].post("/api/v1/firmware/plans", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def start(fw, plan):
    response = fw["client"].post(f"/api/v1/firmware/plans/{plan['id']}/start")
    assert response.status_code == 200, response.text


def test_upload_is_streamed_immutable_hash_checked_and_not_overwritten(fw):
    c = fw["client"]
    id = fw["image"]["id"]
    assert c.put(f"/api/v1/firmware/images/{id}/content", content=b"corrupt").status_code == 409
    new = c.post(
        "/api/v1/firmware/images",
        json={
            **{
                k: v
                for k, v in fw["image"].items()
                if k in ("name", "family", "version", "models", "original_name", "expected_sha256")
            },
            "name": "Bad hash",
        },
    ).json()
    assert c.put(f"/api/v1/firmware/images/{new['id']}/content", content=b"wrong").status_code == 422
    with fw["sf"]() as db:
        assert not image_path(db.get(m.FirmwareImage, new["id"])).exists()
    assert c.get(f"/api/v1/firmware/images/{id}/content").content == CONTENT


def test_upload_rejects_filename_traversal_and_wrong_extension(fw):
    payload = {
        k: v
        for k, v in fw["image"].items()
        if k in ("name", "family", "version", "models", "original_name", "expected_sha256")
    }
    for name in ("../image.swi", "image;reboot.swi", "image.ipe"):
        assert (
            fw["client"].post("/api/v1/firmware/images", json={**payload, "original_name": name}).status_code
            == 422
        )


def test_plan_is_draft_snapshot_not_a_network_trigger(fw):
    plan = make_plan(fw)
    assert plan["status"] == "draft"
    assert runtime.claim() is None
    group = fw["groups"][0]
    fw["client"].put("/api/v1/firmware/groups/" + group["id"], json={"name": "Renamed", "device_ids": []})
    detail = fw["client"].get("/api/v1/firmware/plans/" + plan["id"]).json()
    assert len(detail["targets"]) == 3 and detail["steps"][0]["group_name"] == "Role 0"


def test_same_device_cannot_be_in_two_groups_in_a_plan(fw):
    c = fw["client"]
    group = c.post(
        "/api/v1/firmware/groups", json={"name": "Duplicate role", "device_ids": [fw["devices"][0].id]}
    ).json()
    response = c.post(
        "/api/v1/firmware/plans",
        json={
            "name": "Duplicate",
            "steps": [{"group_id": g["id"], "image_id": fw["image"]["id"]} for g in (fw["groups"][0], group)],
        },
    )
    assert response.status_code == 422


def test_start_is_idempotent_and_reservations_prevent_conflicting_plans(fw):
    first, second = make_plan(fw, "stage"), make_plan(fw, "upgrade")
    start(fw, first)
    start(fw, first)
    assert fw["client"].post("/api/v1/firmware/plans/" + second["id"] + "/start").status_code == 409
    with fw["sf"]() as db:
        assert (
            len(list(db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.active_device.is_not(None)))))
            == 3
        )


def test_ordered_stages_and_bounded_concurrency(fw):
    plan = make_plan(fw, "upgrade", concurrency=2)
    start(fw, plan)
    first, second = runtime.claim(), runtime.claim()
    assert first and second and first != second and runtime.claim() is None
    with fw["sf"]() as db:
        assert db.get(m.FirmwareTarget, first).stage == db.get(m.FirmwareTarget, second).stage == 0
    runtime.finish(first, "succeeded", verified_version="WC.16.11.0026")
    assert runtime.claim() is None
    runtime.finish(second, "succeeded", verified_version="WC.16.11.0026")
    third = runtime.claim()
    with fw["sf"]() as db:
        assert db.get(m.FirmwareTarget, third).stage == 1


def test_failure_pauses_later_groups_without_retrying_mutations(fw):
    plan = make_plan(fw, "upgrade")
    start(fw, plan)
    first = runtime.claim()
    runtime.finish(first, "attention", error_code="interrupted")
    assert runtime.claim() is None
    detail = fw["client"].get("/api/v1/firmware/plans/" + plan["id"]).json()
    assert detail["status"] == "paused" and sum(t["status"] == "queued" for t in detail["targets"]) == 2
    assert fw["client"].post("/api/v1/firmware/plans/" + plan["id"] + "/retry").status_code == 409
    assert "transfer_secret_hash" not in str(detail)


def test_cancel_does_not_interrupt_running_flash_or_reboot(fw):
    plan = make_plan(fw, "upgrade")
    start(fw, plan)
    id = runtime.claim()
    runtime.set_phase(id, "transferring")
    response = fw["client"].post("/api/v1/firmware/plans/" + plan["id"] + "/cancel")
    assert response.status_code == 200
    with fw["sf"]() as db:
        assert db.get(m.FirmwareTarget, id).status == "running"
    runtime.finish(id, "staged")
    runtime.claim()
    with fw["sf"]() as db:
        assert db.get(m.FirmwarePlan, plan["id"]).status == "cancelled"
        assert not list(
            db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.active_device.is_not(None)))
        )


def test_worker_restart_keeps_uncertain_target_reserved(fw):
    plan = make_plan(fw, "stage")
    start(fw, plan)
    id = runtime.claim()
    with fw["sf"]() as db:
        target = db.get(m.FirmwareTarget, id)
        target.phase, target.heartbeat_at = "transferring", now() - timedelta(minutes=5)
        db.commit()
    assert runtime.claim() is None
    with fw["sf"]() as db:
        assert db.get(m.FirmwareTarget, id).status == "attention"
        assert db.get(m.FirmwareTarget, id).active_device


def test_transfer_grant_is_peer_bound_expiring_read_only_and_not_in_api(fw):
    plan = make_plan(fw, "stage")
    start(fw, plan)
    id = runtime.claim()
    runtime.set_phase(id, "transferring")
    username, password, name = transfers.grant(id, "sftp")
    with fw["sf"]() as db:
        peer = db.get(m.Device, db.get(m.FirmwareTarget, id).device_id).management_ip
    access = transfers.lookup(peer, username=username)
    assert access and access["hash"] != password
    assert transfers.lookup("198.51.100.5", username=username) is None
    assert transfers.lookup(peer, filename="../" + name) is None
    detail = fw["client"].get("/api/v1/firmware/plans/" + plan["id"]).text
    assert password not in detail and username not in detail and name not in detail
    sftp = object.__new__(transfers.TransferSFTP)
    sftp.access = access
    with pytest.raises(asyncssh.SFTPPermissionDenied):
        sftp.open(name.encode(), asyncssh.FXF_WRITE, None)
    with pytest.raises(asyncssh.SFTPPermissionDenied):
        sftp.remove(name.encode())
    with pytest.raises(asyncssh.SFTPPermissionDenied):
        sftp.stat(b"/etc/passwd")
    stream = sftp.open(name.encode(), asyncssh.FXF_READ, None)
    assert sftp.read(stream, 0, 1024) == CONTENT
    sftp.close(stream)
    transfers.revoke(id)
    assert transfers.lookup(peer, username=username) is None


def test_tftp_rejects_writes_paths_nonbinary_and_negotiates_bounded_blocks():
    name = b"netrix-fw-" + b"a" * 48 + b".ipe"
    assert transfers.rrq(b"\x00\x01" + name + b"\x00octet\x00blksize\x0065464\x00")[1] == {"blksize": 1468}
    for packet in (
        b"\x00\x02" + name + b"\x00octet\x00",
        b"\x00\x01../file\x00octet\x00",
        b"\x00\x01" + name + b"\x00netascii\x00",
    ):
        with pytest.raises(ValueError):
            transfers.rrq(packet)


def test_running_bank_and_exact_version_checks():
    assert adapters.active_bank("Default Image : primary\nActive Image : secondary\n") == "secondary"
    assert adapters.active_bank("Boot Image: Primary\n") == "primary"
    with pytest.raises(adapters.FirmwareError):
        adapters.active_bank("Default Image : primary")
    assert adapters.bank_contains(
        "Secondary Image : 123456 bytes WC.16.11.0026", "secondary", "WC.16.11.0026"
    )
    assert not adapters.bank_contains(
        "Primary Image : 123456 bytes WC.16.11.0026", "secondary", "WC.16.11.0026"
    )
    assert not adapters.matches_version("WC.16.1.1", "WC.16.10.1")
    assert adapters.matches_version("R3507P10", "7.1.070 Release 3507P10")


@pytest.mark.asyncio
async def test_full_worker_stage_takes_backup_and_never_reboots(fw, monkeypatch):
    plan = make_plan(fw, "stage")
    start(fw, plan)
    id = runtime.claim()
    staged = []

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield None, None

    async def probe(*args):
        return None

    monkeypatch.setattr(adapters, "probe_sftp", probe)

    async def inspect(*args):
        return {"version": "WC.16.10.0025", "bank": "primary", "banks": ""}

    async def backup(*args):
        return '; JL256A Configuration Editor; Created on release #WC.16.10.0025\nhostname "fixture"\n'

    async def stage(*args):
        staged.append(args[4])

    async def no_reboot(*args):
        raise AssertionError("Stage must not reboot")

    monkeypatch.setattr(adapters, "connect", connection)
    monkeypatch.setattr(adapters, "inspect", inspect)
    monkeypatch.setattr(adapters, "stage", stage)
    monkeypatch.setattr(adapters, "activate", no_reboot)
    monkeypatch.setattr(runtime, "fetch_config", backup)
    await runtime.execute(id)
    with fw["sf"]() as db:
        target = db.get(m.FirmwareTarget, id)
        assert target.status == "staged", target.error
        assert target.bank == "secondary" and target.snapshot_id and staged == ["secondary"]
        assert target.evidence["staged"] is True
        snapshot = db.get(m.Snapshot, target.snapshot_id)
        assert "hostname" not in snapshot.encrypted_content


@pytest.mark.asyncio
async def test_failed_transfer_is_uncertain_and_never_auto_replayed(fw, monkeypatch):
    plan = make_plan(fw, "upgrade")
    start(fw, plan)
    id = runtime.claim()

    @asynccontextmanager
    async def connection(*args, **kwargs):
        yield None, None

    async def probe(*args):
        return None

    monkeypatch.setattr(adapters, "probe_sftp", probe)

    async def inspect(*args):
        return {"version": "WC.16.10.0025", "bank": "primary", "banks": ""}

    async def backup(*args):
        return '; JL256A Configuration Editor; Created on release #WC.16.10.0025\nhostname "fixture"\n'

    async def stage(*args):
        raise RuntimeError("device secret must never leak")

    monkeypatch.setattr(adapters, "connect", connection)
    monkeypatch.setattr(adapters, "inspect", inspect)
    monkeypatch.setattr(adapters, "stage", stage)
    monkeypatch.setattr(runtime, "fetch_config", backup)
    await runtime.execute(id)
    with fw["sf"]() as db:
        target = db.get(m.FirmwareTarget, id)
        assert target.status == "attention" and "secret" not in target.error
    assert runtime.claim() is None


def test_reconciliation_does_not_resume_later_writes(fw):
    plan = make_plan(fw, "upgrade")
    start(fw, plan)
    target = runtime.claim()
    runtime.finish(target, "attention", error_code="interrupted")
    assert runtime.claim() is None
    response = fw["client"].post("/api/v1/firmware/targets/" + target + "/verify")
    assert response.status_code == 200
    assert runtime.claim() == target
    runtime.finish(target, "succeeded", verified_version="WC.16.11.0026")
    assert runtime.claim() is None
    with fw["sf"]() as db:
        assert db.get(m.FirmwarePlan, plan["id"]).status == "paused"


def test_viewer_cannot_upload_create_groups_or_start_firmware(fw):
    c = fw["client"]
    with fw["sf"]() as db:
        user = db.scalar(select(m.User))
        user.role = "viewer"
        db.commit()
    assert c.get("/api/v1/firmware/devices").status_code == 200
    assert c.post("/api/v1/firmware/groups", json={"name": "Denied"}).status_code == 403
    assert (
        c.post(
            "/api/v1/firmware/plans",
            json={
                "name": "Denied",
                "steps": [{"group_id": fw["groups"][0]["id"], "image_id": fw["image"]["id"]}],
            },
        ).status_code
        == 403
    )
    assert (
        c.put("/api/v1/firmware/images/" + fw["image"]["id"] + "/content", content=CONTENT).status_code == 403
    )


def test_manual_recovery_requires_exact_name_and_does_not_claim_success(fw):
    plan = make_plan(fw, "upgrade")
    start(fw, plan)
    id = runtime.claim()
    runtime.finish(id, "attention", error_code="interrupted")
    with fw["sf"]() as db:
        name = db.get(m.Device, db.get(m.FirmwareTarget, id).device_id).name
    endpoint = "/api/v1/firmware/targets/" + id + "/release"
    assert (
        fw["client"].post(endpoint, json={"device_name": "wrong", "confirmed_recovery": True}).status_code
        == 422
    )
    response = fw["client"].post(endpoint, json={"device_name": name, "confirmed_recovery": True})
    assert response.status_code == 200 and response.json()["status"] == "failed"
    with fw["sf"]() as db:
        assert db.get(m.FirmwareTarget, id).active_device is None


def test_image_model_and_software_families_cannot_be_mixed(fw):
    payload = {
        "name": "Wrong model",
        "family": "hp1950",
        "version": "R3507P10",
        "models": ["JH295A"],
        "original_name": "wrong.ipe",
        "expected_sha256": DIGEST,
    }
    assert fw["client"].post("/api/v1/firmware/images", json=payload).status_code == 422
    assert (
        fw["client"].post("/api/v1/firmware/images", json={**payload, "version": "R5106P06"}).status_code
        == 201
    )
    assert (
        fw["client"]
        .post(
            "/api/v1/firmware/images",
            json={**payload, "version": "R5106P06", "models": ["JH295A", "JG960A"]},
        )
        .status_code
        == 422
    )
