"""Durable VLAN scan groups, memberships and scheduled dispatch history."""

import sqlalchemy as sa
from alembic import op
from netrix.core import UTCDateTime

revision = "20261103_35"
down_revision = "20261103_34"
branch_labels = None
depends_on = None


def entity():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "ipam_scan_groups",
        *entity(),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("description", sa.String(400), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("frequency", sa.String(10), nullable=False),
        sa.Column("repeat_every", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=False),
        sa.Column("start_at", UTCDateTime(), nullable=False),
        sa.Column("next_run_at", UTCDateTime(), nullable=True),
        sa.Column("run_limit", sa.Integer(), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("last_run_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint("frequency in ('daily','weekly','monthly')", name="ck_ipam_scan_frequency"),
        sa.CheckConstraint("repeat_every >= 1 AND repeat_every <= 365", name="ck_ipam_scan_every"),
        sa.CheckConstraint(
            "run_count >= 0 AND (run_limit IS NULL OR run_limit >= 1)", name="ck_ipam_scan_count"
        ),
    )
    op.create_index("ix_ipam_scan_due", "ipam_scan_groups", ["enabled", "next_run_at"])
    op.create_table(
        "ipam_scan_members",
        sa.Column(
            "group_id",
            sa.String(36),
            sa.ForeignKey("ipam_scan_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "vlan_id",
            sa.String(36),
            sa.ForeignKey("vlans.id", ondelete="CASCADE"),
            primary_key=True,
            unique=True,
        ),
    )
    op.create_table(
        "ipam_scan_runs",
        *entity(),
        sa.Column(
            "group_id",
            sa.String(36),
            sa.ForeignKey("ipam_scan_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scheduled_for", UTCDateTime(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("jobs", sa.JSON(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=False),
        sa.UniqueConstraint("group_id", "generation", "scheduled_for", name="uq_ipam_scan_slot"),
    )
    op.create_index("ix_ipam_scan_runs_group_id", "ipam_scan_runs", ["group_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM ipam_scan_groups")):
        raise RuntimeError("Tarama grupları varken kayıplı downgrade yapılamaz")
    op.drop_table("ipam_scan_runs")
    op.drop_table("ipam_scan_members")
    op.drop_table("ipam_scan_groups")
