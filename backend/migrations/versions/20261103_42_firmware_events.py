"""Device execution transcript, redacted and paginated independently of plans."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261103_42"
down_revision = "20261103_41"
branch_labels = None
depends_on = None


def upgrade():
    utc = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")
    op.create_table(
        "firmware_events",
        sa.Column(
            "id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True
        ),
        sa.Column("created_at", utc, nullable=False),
        sa.Column("updated_at", utc, nullable=False),
        sa.Column(
            "target_id",
            sa.String(36),
            sa.ForeignKey("firmware_targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("phase", sa.String(30), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("finished_at", utc, nullable=True),
        sa.CheckConstraint(
            "status in ('info','started','succeeded','failed','sent')", name="ck_fw_event_status"
        ),
    )
    op.create_index("ix_fw_event_target_order", "firmware_events", ["target_id", "id"])
    op.create_index("ix_fw_plan_history_order", "firmware_plans", ["created_at", "id"])


def downgrade():
    op.drop_index("ix_fw_plan_history_order", table_name="firmware_plans")
    op.drop_table("firmware_events")
