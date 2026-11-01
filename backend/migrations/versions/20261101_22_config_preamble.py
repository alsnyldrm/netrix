"""Recalculate config state without command echoes; preserve existing approvals."""

from alembic import op
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

revision = "20261101_22"
down_revision = "20261101_21"
branch_labels = None
depends_on = None


def upgrade():
    from netrix import models as m
    from netrix.configuration.baselines import fingerprint, rebuild
    from netrix.identity.security import decrypt

    with Session(bind=op.get_bind()) as db:
        for device in db.scalars(
            select(m.Device).options(
                load_only(m.Device.id, m.Device.base_snapshot_id, m.Device.approved_config_hash)
            )
        ):
            approved = (
                db.scalar(
                    select(m.Snapshot)
                    .where(
                        m.Snapshot.device_id == device.id,
                        m.Snapshot.fingerprint == device.approved_config_hash,
                    )
                    .limit(1)
                )
                if device.approved_config_hash
                else None
            )
            approved_hash = fingerprint(decrypt(approved.encrypted_content)) if approved else None
            rebuild(db, device)
            if approved_hash:
                device.approved_config_hash = approved_hash
        db.commit()


def downgrade():
    # Data correction is intentionally retained; raw configuration files are untouched.
    pass
