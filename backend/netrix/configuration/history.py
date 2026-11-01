"""Repair retained configuration flags against each device's persistent baseline."""

from sqlalchemy import select

from .. import models as m
from ..identity.security import audit, decrypt
from .baselines import base, fingerprint
from .validation import BackupError, validate_cli_output


def repair_change_flags(db, device_id, *, apply=False):
    device = db.scalar(select(m.Device).where(m.Device.id == device_id).with_for_update())
    previous_base = device.base_snapshot_id
    reference = base(db, device)
    baseline = fingerprint(decrypt(reference.encrypted_content)) if reference else None
    changes = []
    for row in db.scalars(
        select(m.Snapshot)
        .where(m.Snapshot.device_id == device_id)
        .order_by(m.Snapshot.created_at, m.Snapshot.id)
    ):
        content = decrypt(row.encrypted_content)
        try:
            validate_cli_output(content)
            expected = bool(baseline and fingerprint(content) != baseline)
        except BackupError:
            expected = False
        if row.changed != expected:
            changes.append({"snapshot_id": row.id, "previous_changed": row.changed, "changed": expected})
            if apply:
                row.changed = expected
                audit(
                    db,
                    None,
                    "repair_change_flag",
                    "snapshots",
                    row.id,
                    "Değişiklik işareti base config ile yeniden hesaplandı",
                )
        if apply:
            row.fingerprint = fingerprint(content)
    if not apply:
        device.base_snapshot_id = previous_base
    return changes
