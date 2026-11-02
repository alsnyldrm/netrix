"""Firmware repository, independent groups and durable ordered rollouts."""

import sqlalchemy as sa
from alembic import op
from netrix.core import UTCDateTime

revision = "20261102_32"
down_revision = "20261102_31"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "firmware_images",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("family", sa.String(length=20), nullable=False, index=True),
        sa.Column("version", sa.String(length=120), nullable=False),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("original_name", sa.String(length=160), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("expected_sha256", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, index=True),
        sa.Column("uploaded_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("family in ('aos_s','cx6100','hp1950')", name="ck_fw_image_family"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_fw_image_size"),
        sa.CheckConstraint("status in ('uploading','ready')", name="ck_fw_image_status"),
    )
    op.create_table(
        "firmware_groups",
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("description", sa.String(length=400), nullable=False),
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "firmware_group_members",
        sa.Column(
            "group_id",
            sa.String(length=36),
            sa.ForeignKey("firmware_groups.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "device_id",
            sa.String(length=36),
            sa.ForeignKey("devices.id"),
            primary_key=True,
            nullable=False,
            index=True,
        ),
    )
    op.create_table(
        "firmware_plans",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, index=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("available_at", UTCDateTime(), nullable=False, index=True),
        sa.Column("requested_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("concurrency between 1 and 4", name="ck_fw_plan_concurrency"),
        sa.CheckConstraint("mode in ('check','stage','upgrade','activate','verify')", name="ck_fw_plan_mode"),
        sa.CheckConstraint(
            "status in ('draft','queued','running','paused','ready','succeeded','cancelled')",
            name="ck_fw_plan_status",
        ),
    )
    op.create_table(
        "firmware_targets",
        sa.Column(
            "plan_id", sa.String(length=36), sa.ForeignKey("firmware_plans.id"), nullable=False, index=True
        ),
        sa.Column("device_id", sa.String(length=36), sa.ForeignKey("devices.id"), nullable=False, index=True),
        sa.Column(
            "image_id", sa.String(length=36), sa.ForeignKey("firmware_images.id"), nullable=False, index=True
        ),
        sa.Column("stage", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, index=True),
        sa.Column("phase", sa.String(length=30), nullable=False),
        sa.Column("bank", sa.String(length=12), nullable=False),
        sa.Column("previous_bank", sa.String(length=12), nullable=False),
        sa.Column("previous_version", sa.String(length=120), nullable=False),
        sa.Column("verified_version", sa.String(length=120), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), sa.ForeignKey("config_snapshots.id"), nullable=True),
        sa.Column("active_device", sa.String(length=36), nullable=True, unique=True),
        sa.Column("heartbeat_at", UTCDateTime(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=False),
        sa.Column("error", sa.String(length=400), nullable=False),
        sa.Column("transfer_username", sa.String(length=60), nullable=True, unique=True),
        sa.Column("transfer_secret_hash", sa.String(length=64), nullable=False),
        sa.Column("transfer_name", sa.String(length=100), nullable=True, unique=True),
        sa.Column("transfer_expires_at", UTCDateTime(), nullable=True),
        sa.Column("transfer_bytes", sa.BigInteger(), nullable=False),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("stage >= 0", name="ck_fw_target_stage"),
        sa.CheckConstraint(
            "status in ('queued','running','checked','staged','succeeded','failed','attention','cancelled')",
            name="ck_fw_target_status",
        ),
        sa.UniqueConstraint("plan_id", "device_id", name="uq_fw_plan_device"),
    )


def downgrade():
    connection = op.get_bind()
    for table in ("firmware_targets", "firmware_plans", "firmware_images", "firmware_groups"):
        if connection.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("Firmware records exist; export and explicitly remove them before downgrade")
    for table in (
        "firmware_targets",
        "firmware_plans",
        "firmware_group_members",
        "firmware_groups",
        "firmware_images",
    ):
        op.drop_table(table)
