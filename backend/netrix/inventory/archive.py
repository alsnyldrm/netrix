"""Explicit permanent deletion of archived inventory, with shared data preserved."""

from fastapi import HTTPException
from sqlalchemy import delete, or_, select, update

from .. import models as m
from ..core import now
from ..identity.security import audit


def purge_devices(db, rows, user):
    if any(not row.archived for row in rows):
        raise HTTPException(409, "Yalnızca arşivlenmiş cihazlar kalıcı silinebilir")
    ids = [row.id for row in rows]
    jobs = list(db.scalars(select(m.Job).where(m.Job.target_id.in_(ids)).with_for_update()))
    if any(job.status == "running" for job in jobs):
        raise HTTPException(
            409,
            "Seçilen cihazda çalışan işlem var. İşlem tamamlandıktan veya iptal edildikten sonra tekrar deneyin.",
        )
    for job in jobs:
        if job.status == "queued":
            job.status, job.cancel_requested, job.active_key = "cancelled", True, None
            job.finished_at = now()
    interfaces = select(m.Interface.id).where(m.Interface.device_id.in_(ids))
    # IPAM belongs to VLANs. Remove only the inventory associations.
    db.execute(update(m.IPAddress).where(m.IPAddress.interface_id.in_(interfaces)).values(interface_id=None))
    db.execute(update(m.IPAddress).where(m.IPAddress.device_id.in_(ids)).values(device_id=None))
    db.execute(delete(m.RackPlacement).where(m.RackPlacement.device_id.in_(ids)))
    db.execute(
        delete(m.Link).where(
            or_(
                m.Link.device_id.in_(ids),
                m.Link.remote_device_id.in_(ids),
                m.Link.manual_remote_device_id.in_(ids),
            )
        )
    )
    db.execute(delete(m.Interface).where(m.Interface.device_id.in_(ids)))
    db.execute(delete(m.Observation).where(m.Observation.device_id.in_(ids)))
    db.execute(delete(m.Alert).where(m.Alert.device_id.in_(ids)))
    # Release the cyclic base-config FK before removing the snapshots.
    for row in rows:
        row.base_snapshot_id = None
    db.flush()
    db.execute(delete(m.Snapshot).where(m.Snapshot.device_id.in_(ids)))
    for row in rows:
        # Preserve event and audit history, with enough identity to read it later.
        events = db.scalars(select(m.Event).where(m.Event.device_id == row.id))
        for event in events:
            event.details = {
                **event.details,
                "deleted_device": {"id": row.id, "name": row.name, "management_ip": row.management_ip},
            }
            event.device_id = None
        audit(db, user, "bulk_purge", "devices", row.id, f"Kalıcı silindi: {row.name} ({row.management_ip})")
    db.flush()
    for row in rows:
        db.delete(row)
    db.flush()
