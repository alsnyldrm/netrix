"""Compact per-user workspace and explicit device SSH grants."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_34"
down_revision = "20261103_33"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_workspaces",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("preferences", sa.JSON(), nullable=False),
        sa.Column("encrypted_ssh", sa.Text(), nullable=True),
        sa.Column("encrypted_commands", sa.Text(), nullable=True),
    )
    from netrix.core import UTCDateTime

    op.create_table(
        "access_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(400), nullable=False),
        sa.Column("ssh_enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.UniqueConstraint("owner_id", "name", name="uq_access_group_owner_name"),
    )
    op.create_index("ix_access_groups_owner_id", "access_groups", ["owner_id"])
    for suffix, target, field in (("devices", "devices", "device_id"), ("users", "users", "user_id")):
        table = "access_group_" + suffix
        op.create_table(
            table,
            sa.Column(
                "group_id",
                sa.String(36),
                sa.ForeignKey("access_groups.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                field, sa.String(36), sa.ForeignKey(target + ".id", ondelete="CASCADE"), primary_key=True
            ),
        )
        op.create_index(f"ix_{table}_{field}", table, [field])


def downgrade():
    bind = op.get_bind()
    for table in ("user_workspaces", "access_groups"):
        if bind.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError("Remove saved workspaces and access groups explicitly before downgrade")
    for table in ("access_group_users", "access_group_devices", "access_groups", "user_workspaces"):
        op.drop_table(table)
