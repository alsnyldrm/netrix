"""Automatically adopt up interfaces while preserving explicit user exclusions."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_08"
down_revision = "20261030_07"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "interfaces", sa.Column("auto_add_excluded", sa.Boolean(), nullable=False, server_default="0")
    )
    # Old full-selection saves explicitly deselected all existing omitted ports.
    # Ports first discovered after that save remain eligible for automatic adoption.
    op.execute("""
        UPDATE interfaces SET auto_add_excluded = 1
        WHERE is_deleted = 1 OR (is_managed = 0 AND EXISTS (
            SELECT 1 FROM audit_events a
            WHERE a.action = 'select_interfaces' AND a.entity_type = 'devices'
              AND a.entity_id = interfaces.device_id AND a.created_at >= interfaces.created_at
        ))
    """)
    op.execute("""
        UPDATE interfaces SET is_managed = 1
        WHERE oper_status = 'up' AND is_deleted = 0 AND auto_add_excluded = 0
          AND EXISTS (SELECT 1 FROM devices d WHERE d.id = interfaces.device_id AND d.archived = 0)
    """)


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM interfaces WHERE auto_add_excluded = 1 AND is_deleted = 0")
    ):
        raise RuntimeError("Saved interface exclusions exist; downgrade would lose user preferences")
    op.drop_column("interfaces", "auto_add_excluded")
