"""Run only on isolated netrix_test: schema parity, constraints and competing plans."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException
from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.firmware.runtime import claim as firmware_claim
from netrix.firmware.service import PlanInput, new_plan, start_plan
from netrix.identity.security import encrypt
from netrix.worker import claim as normal_claim
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test", "Disposable test database required"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
with session_factory()() as db:
    user = m.User(
        email="firmware@example.test", display_name="Fixture", password_hash="unused-fixture", role="admin"
    )
    vrf = m.VRF(name="Firmware fixture")
    credential = m.Credential(
        name="Fixture SSH",
        protocol="ssh",
        encrypted_secret=encrypt('{"username":"fixture","password":"fixture"}'),
    )
    db.add_all([user, vrf, credential])
    db.flush()
    scope = m.Scope(
        name="Firmware scope", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=credential.id, vlan_vid=10
    )
    db.add(scope)
    db.flush()
    device = m.Device(
        name="Fixture",
        management_ip="192.0.2.1",
        vrf_id=vrf.id,
        discovery_scope_id=scope.id,
        adapter="aruba_2900",
        model="JL256A",
        config_credential_id=credential.id,
    )
    group = m.FirmwareGroup(name="User-defined role")
    image = m.FirmwareImage(
        name="Image",
        family="aos_s",
        version="WC.16.11.0026",
        models=["JL256A"],
        original_name="fixture.swi",
        sha256="a" * 64,
        expected_sha256="a" * 64,
        status="ready",
    )
    db.add_all([device, group, image])
    db.flush()
    db.add(m.FirmwareMember(group_id=group.id, device_id=device.id))
    db.commit()
    user_id, device_id, image_id = user.id, device.id, image.id
    payload = PlanInput(
        name="Concurrent rollout",
        mode="stage",
        steps=[{"group_id": group.id, "image_id": image.id}],
        acknowledge_upgrade_path=True,
    )
    plans = [new_plan(db, payload, user).id for _ in range(2)]
barrier = Barrier(2)


def compete(id):
    with session_factory()() as db:
        plan, user = db.get(m.FirmwarePlan, id), db.get(m.User, user_id)
        barrier.wait()
        try:
            return start_plan(db, plan, user).status
        except HTTPException as exc:
            db.rollback()
            assert exc.status_code == 409
            return "conflict"
        except OperationalError as exc:
            db.rollback()
            assert exc.orig.args[0] in (1213, 1205)
            return "conflict"


with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(compete, plans)) == ["conflict", "queued"]
with session_factory()() as db:
    target = db.scalar(select(m.FirmwareTarget).where(m.FirmwareTarget.active_device == device_id))
    assert target and target.created_at.tzinfo is not None
    target_id = target.id
    for statement in (
        text("UPDATE firmware_targets SET status='invented' WHERE id=:id"),
        text("UPDATE firmware_targets SET device_id='missing' WHERE id=:id"),
        text("UPDATE firmware_targets SET active_device=:device WHERE id<>:id"),
        text("DELETE FROM firmware_images WHERE id=:image"),
    ):
        try:
            db.execute(statement, {"id": target_id, "device": device_id, "image": image_id})
            db.commit()
            raise AssertionError("Database constraint did not reject invalid firmware data")
        except IntegrityError:
            db.rollback()
        except OperationalError as exc:
            db.rollback()
            assert exc.orig.args[0] == 4025, "Unexpected MariaDB error"

# Race both claimants without executing either job or opening a device connection.
with session_factory()() as db:
    job = m.Job(kind="backup", target_id=device_id, active_key="backup:" + device_id)
    db.add(job)
    db.commit()
    job_id = job.id

for _ in range(12):
    with session_factory()() as db:
        target, job = db.get(m.FirmwareTarget, target_id), db.get(m.Job, job_id)
        plan = db.get(m.FirmwarePlan, target.plan_id)
        target.status, target.phase, target.heartbeat_at = "queued", "queued", now()
        job.status, job.heartbeat_at, job.attempts = "queued", now(), 0
        plan.status = "queued"
        db.commit()
    barrier = Barrier(2)

    def take(fn):
        barrier.wait()
        try:
            return fn()
        except OperationalError as exc:
            assert exc.orig.args[0] in (1020, 1205, 1213)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(take, [normal_claim, firmware_claim]))
    with session_factory()() as db:
        running = int(db.get(m.Job, job_id).status == "running") + int(
            db.get(m.FirmwareTarget, target_id).status == "running"
        )
        assert running == 1, "Normal and firmware workers must never claim the same device together"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
result = subprocess.run(
    ["alembic", "-c", "backend/alembic.ini", "downgrade", "20261102_31"], capture_output=True, text=True
)
assert result.returncode != 0 and "Firmware records exist" in result.stderr
print(
    "PASS: MariaDB migration/schema parity, UTC, CHECK/FK/UNIQUE, simultaneous plan reservations and guarded downgrade"
)
