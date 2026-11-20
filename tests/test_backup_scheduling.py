from datetime import timedelta

import pytest
from netrix import models as m
from netrix import scheduler
from netrix.core import now
from netrix.identity.security import encrypt
from sqlalchemy import select


@pytest.fixture
def scheduled_device(admin_client, env, monkeypatch):
    from netrix.ipam import scan_schedules

    monkeypatch.setattr(scan_schedules, "dispatch_due", lambda: None)
    monkeypatch.setattr(scheduler, "publish", lambda: None)
    at = now()
    monkeypatch.setattr(scheduler, "now", lambda: at)
    vrf_id = admin_client.get("/api/v1/vrfs").json()["items"][0]["id"]
    with env() as db:
        user = db.scalar(select(m.User))
        credential = m.Credential(
            name="Scheduled SSH",
            protocol="ssh",
            encrypted_secret=encrypt('{"username":"fixture","password":"fixture"}'),
        )
        group = m.BackupGroup(name="Twelve-hour backups", interval_seconds=43200, retention_count=0)
        db.add_all([credential, group])
        db.flush()
        device = m.Device(
            name="Scheduled switch",
            management_ip="192.0.2.1",
            vrf_id=vrf_id,
            config_credential_id=credential.id,
            backup_group_id=group.id,
            backup_interval=0,
            last_backup_at=at,
        )
        db.add(device)
        db.commit()
        return device.id, user.id, at


def add_attempt(db, device_id, at, *, user_id=None, age=13, status="succeeded"):
    row = m.Job(
        kind="backup",
        target_id=device_id,
        requested_by=user_id,
        status=status,
        created_at=at - timedelta(hours=age),
        finished_at=at - timedelta(hours=age) + timedelta(seconds=10),
    )
    db.add(row)
    return row


@pytest.mark.parametrize("prior_automatic", [True, False])
def test_manual_backup_does_not_postpone_due_group_backup(env, scheduled_device, prior_automatic):
    device_id, user_id, at = scheduled_device
    with env() as db:
        add_attempt(db, device_id, at, user_id=None if prior_automatic else user_id)
        add_attempt(db, device_id, at, user_id=user_id, age=0)
        db.commit()
    scheduler.tick(include_ping=False)
    scheduler.tick(include_ping=False)
    with env() as db:
        pending = list(db.scalars(select(m.Job).where(m.Job.kind == "backup", m.Job.status == "queued")))
        assert len(pending) == 1 and pending[0].target_id == device_id
        assert pending[0].requested_by is None


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_recent_automatic_attempt_preserves_interval(env, scheduled_device, status):
    device_id, user_id, at = scheduled_device
    with env() as db:
        add_attempt(db, device_id, at, age=1, status=status)
        add_attempt(db, device_id, at, user_id=user_id, age=0)
        db.commit()
    scheduler.tick(include_ping=False)
    with env() as db:
        assert not list(db.scalars(select(m.Job).where(m.Job.status == "queued")))


def test_initial_manual_backup_starts_group_interval(env, scheduled_device):
    device_id, user_id, at = scheduled_device
    with env() as db:
        add_attempt(db, device_id, at, user_id=user_id, age=1)
        db.commit()
    scheduler.tick(include_ping=False)
    with env() as db:
        assert not list(db.scalars(select(m.Job).where(m.Job.status == "queued")))


def test_manual_backups_do_not_replace_archived_automatic_schedule_anchor(env, scheduled_device):
    device_id, user_id, at = scheduled_device
    with env() as db:
        automatic = add_attempt(db, device_id, at)
        automatic.archived_at = at
        add_attempt(db, device_id, at, user_id=user_id, age=0)
        db.commit()
    scheduler.tick(include_ping=False)
    with env() as db:
        assert db.scalar(select(m.Job.id).where(m.Job.status == "queued"))
