"""Bounded gateway-first resolution, one replaceable row per IP."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261104_49"
down_revision = "20261104_48"
branch_labels = None
depends_on = None


def upgrade():
    time = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")
    op.create_table(
        "ipam_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", time, nullable=False),
        sa.Column("updated_at", time, nullable=False),
        sa.Column(
            "address_id",
            sa.String(36),
            sa.ForeignKey("ip_addresses.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("address_scope", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("retained", sa.Boolean(), nullable=False),
        sa.Column("started_at", time, nullable=False),
        sa.Column("completed_at", time, nullable=False),
        sa.Column("last_success_at", time),
        sa.CheckConstraint("status in ('success','problem')", name="ck_ipam_result_status"),
    )

    op.create_table(
        "ipam_network_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", time, nullable=False),
        sa.Column("updated_at", time, nullable=False),
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("address", sa.String(45), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("observed_at", time, nullable=False),
    )

    op.execute(
        sa.text(
            "UPDATE jobs SET status='cancelled', cancel_requested=1, finished_at=CURRENT_TIMESTAMP, active_key=NULL, error='Kaynak okuması ortak VLAN/IP algoritmasına taşındı.' WHERE kind='integration' AND status IN ('queued','running')"
        )
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM ipam_results LIMIT 1")).first():
        raise RuntimeError("Current IP resolutions exist; refuse a lossy downgrade")
    if op.get_bind().execute(sa.text("SELECT 1 FROM ipam_network_states LIMIT 1")).first():
        raise RuntimeError("Current network sources exist; refuse a lossy downgrade")
    op.drop_table("ipam_results")
    op.drop_table("ipam_network_states")
