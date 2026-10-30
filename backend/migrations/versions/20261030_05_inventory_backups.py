"""Managed interface selection, device archives and backup groups/policies."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261030_05"
down_revision = "20261030_04"
branch_labels = None
depends_on = None


def upgrade():
    timestamp = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")
    op.create_table(
        "backup_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(400), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("retention_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("name"),
        sa.CheckConstraint(
            "interval_seconds = 0 OR interval_seconds >= 300", name="ck_backup_group_interval"
        ),
        sa.CheckConstraint("retention_count >= 0", name="ck_backup_group_retention"),
    )
    op.add_column("devices", sa.Column("archived", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("devices", sa.Column("backup_retention", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("devices") as batch:
        batch.add_column(sa.Column("backup_group_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_device_backup_group", "backup_groups", ["backup_group_id"], ["id"])
        batch.create_index("ix_devices_backup_group_id", ["backup_group_id"])
    op.add_column("interfaces", sa.Column("is_managed", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column(
        "interfaces", sa.Column("monitoring_enabled", sa.Boolean(), nullable=False, server_default="1")
    )
    op.add_column("interfaces", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0"))
    op.execute("UPDATE interfaces SET is_managed = 1")


def downgrade():
    for name in ("is_deleted", "monitoring_enabled", "is_managed"):
        op.drop_column("interfaces", name)
    with op.batch_alter_table("devices") as batch:
        batch.drop_constraint("fk_device_backup_group", type_="foreignkey")
        batch.drop_index("ix_devices_backup_group_id")
        batch.drop_column("backup_group_id")
    op.drop_column("devices", "backup_retention")
    op.drop_column("devices", "archived")
    op.drop_table("backup_groups")
