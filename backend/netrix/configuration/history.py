"""Select configuration baselines without treating legacy CLI errors as configs."""

from sqlalchemy import and_, or_, select

from .. import models as m
from ..identity.security import audit, decrypt
from .validation import BackupError, validate_cli_output


def previous_valid_snapshot(db, device_id, before=None):
    # Keyset order also resolves snapshots which share the same UTC timestamp.
    # Read one encrypted config at a time; invalid legacy rows remain in history.
    while True:
        stmt = select(m.Snapshot).where(m.Snapshot.device_id == device_id)
        if before is not None:
            stmt = stmt.where(
                or_(
                    m.Snapshot.created_at < before.created_at,
                    and_(m.Snapshot.created_at == before.created_at, m.Snapshot.id < before.id),
                )
            )
        row = db.scalar(stmt.order_by(m.Snapshot.created_at.desc(), m.Snapshot.id.desc()).limit(1))
        if row is None:
            return None, None
        content = decrypt(row.encrypted_content)
        try:
            validate_cli_output(content)
        except BackupError:
            before = row
            continue
        return row, content


def repair_change_flags(db, device_id, *, apply=False):
    """Repair retained history; leave the first valid row's unknown older baseline alone."""
    db.scalar(select(m.Device).where(m.Device.id == device_id).with_for_update())
    previous_content, saw_invalid, changes = None, False, []
    rows = db.scalars(
        select(m.Snapshot)
        .where(m.Snapshot.device_id == device_id)
        .order_by(m.Snapshot.created_at, m.Snapshot.id)
    )
    for row in rows:
        content = decrypt(row.encrypted_content)
        try:
            validate_cli_output(content)
        except BackupError:
            expected, saw_invalid = False, True
        else:
            expected = (
                previous_content != content
                if previous_content is not None
                else False
                if saw_invalid
                else row.changed
            )
            previous_content = content
        if row.changed == expected:
            continue
        changes.append({"snapshot_id": row.id, "previous_changed": row.changed, "changed": expected})
        if apply:
            row.changed = expected
            audit(
                db,
                None,
                "repair_change_flag",
                "snapshots",
                row.id,
                "Değişiklik işareti geçerli konfigürasyon geçmişine göre düzeltildi.",
            )
    return changes
