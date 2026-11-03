"""Independent, indexed switch MAC snapshots; primary IPAM evidence keeps priority."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261103_44"
down_revision = "20261103_43"
branch_labels = None
depends_on = None


def entity_columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb"), nullable=False
        ),
    ]


def upgrade():
    op.create_table(
        "switch_mac_snapshots",
        *entity_columns(),
        sa.Column(
            "device_id",
            sa.String(36),
            sa.ForeignKey("devices.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("observed_at", sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")),
        sa.Column(
            "attempted_at", sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb"), nullable=False
        ),
        sa.Column("healthy", sa.Boolean(), nullable=False),
        sa.Column("error_class", sa.String(80), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("read_context", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.CheckConstraint("entry_count >= 0", name="ck_switch_mac_count"),
    )
    op.create_table(
        "switch_mac_entries",
        *entity_columns(),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("switch_mac_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vrf_id", sa.String(36), sa.ForeignKey("vrfs.id"), nullable=False),
        sa.Column("vlan_vid", sa.Integer(), nullable=False),
        sa.Column("mac_address", sa.String(17), nullable=False),
        sa.Column("port", sa.String(190), nullable=False),
        sa.Column("if_index", sa.Integer(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "vlan_vid", "mac_address", "port", name="uq_switch_mac_binding"),
        sa.CheckConstraint("vlan_vid >= 1 AND vlan_vid <= 4094", name="ck_switch_mac_vlan"),
        sa.CheckConstraint("if_index > 0", name="ck_switch_mac_ifindex"),
    )
    op.create_index("ix_switch_mac_lookup", "switch_mac_entries", ["vrf_id", "vlan_vid", "mac_address"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM switch_mac_snapshots LIMIT 1")).first():
        raise RuntimeError("Switch MAC snapshots exist; refuse a lossy downgrade")
    op.drop_table("switch_mac_entries")
    op.drop_table("switch_mac_snapshots")
