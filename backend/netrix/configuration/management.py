"""Backup policies, retention and asynchronous live comparisons."""

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from .. import services as svc
from ..core import now, session_factory
from ..discovery.protocols import fetch_config
from ..identity.security import audit, decrypt
from .diff import config_diff


def policy(db, device):
    group = db.get(m.BackupGroup, device.backup_group_id) if device.backup_group_id else None
    return (
        (group.interval_seconds, group.retention_count)
        if group
        else (device.backup_interval, device.backup_retention)
    )


def pinned_snapshots(db, device_id):
    return {
        j.result.get("base_snapshot_id")
        for j in db.scalars(
            select(m.Job).where(
                m.Job.target_id == device_id, m.Job.kind == "compare", m.Job.status.in_(("queued", "running"))
            )
        )
    }


def prune(db, device):
    _, count = policy(db, device)
    if not count:
        return
    pinned = pinned_snapshots(db, device.id)
    rows = db.scalars(
        select(m.Snapshot)
        .where(m.Snapshot.device_id == device.id)
        .order_by(m.Snapshot.created_at.desc(), m.Snapshot.id.desc())
    ).all()
    for row in rows[count:]:
        if row.id not in pinned:
            db.delete(row)


def start_comparison(db, snapshot_id, user):
    snapshot = svc.get(db, m.Snapshot, snapshot_id)
    # enqueue holds the device lock, also used by retention/deletion.
    job = svc.enqueue(db, "compare", snapshot.device_id, user, commit=False)
    if job.result and job.result.get("base_snapshot_id") != snapshot_id:
        raise HTTPException(409, "Bu cihaz için başka bir karşılaştırma sürüyor")
    if not db.scalar(select(m.Snapshot.id).where(m.Snapshot.id == snapshot_id)):
        raise HTTPException(404, "Yedek artık mevcut değil")
    if not job.result:
        job.result = {"base_snapshot_id": snapshot_id}
    db.commit()
    svc.publish()
    return svc.serialize(job)


async def compare_live(job_id):
    with session_factory()() as db:
        job = svc.get(db, m.Job, job_id)
        if "diff" in job.result:
            return job.result
        snapshot = svc.get(db, m.Snapshot, job.result["base_snapshot_id"])
        device = svc.get(db, m.Device, job.target_id)
        svc.authorized_device(db, device)
        profile = svc.get(db, m.Credential, device.config_credential_id)
        import json

        secret = json.loads(decrypt(profile.encrypted_secret))
        baseline = decrypt(snapshot.encrypted_content)
        signature = tuple(getattr(device, k) for k in svc.IDENTITY_CONNECTION_FIELDS) + (
            device.config_path,
            profile.updated_at,
        )
        base_id = snapshot.id
    content = await fetch_config(device, secret)
    if not content.strip():
        raise ValueError("Boş konfigürasyon")
    with session_factory()() as db:
        current = svc.get(db, m.Device, device.id)
        svc.authorized_device(db, current)
        profile = svc.get(db, m.Credential, current.config_credential_id)
        if signature != tuple(getattr(current, k) for k in svc.IDENTITY_CONNECTION_FIELDS) + (
            current.config_path,
            profile.updated_at,
        ):
            raise ValueError("Bağlantı ayarı değişti")
        job = svc.get(db, m.Job, job_id)
        if job.cancel_requested:
            from ..worker import Cancelled

            raise Cancelled()
        result = {
            "base_snapshot_id": base_id,
            "diff": config_diff(baseline, content),
            "changed": baseline != content,
            "checked_at": now().isoformat(),
        }
        job.result = result
        db.commit()
        return result


def delete_snapshot(db, id, user):
    row = svc.get(db, m.Snapshot, id)
    db.scalar(select(m.Device).where(m.Device.id == row.device_id).with_for_update())
    if id in pinned_snapshots(db, row.device_id):
        raise HTTPException(409, "Bu yedek çalışan karşılaştırmada kullanılıyor")
    db.delete(row)
    audit(db, user, "delete", "snapshots", id, "Konfigürasyon yedeği silindi")
    db.commit()
    svc.publish()
