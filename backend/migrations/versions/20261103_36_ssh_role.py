"""Move SSH permission to an independently assignable user role; groups stay personal."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_36"
down_revision = "20261103_35"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("ssh_access", sa.Boolean(), nullable=False, server_default="0"))
    # Preserve users explicitly granted SSH access by an administrator in the old UI.
    op.execute(
        sa.text("""
        UPDATE users SET ssh_access = 1 WHERE id IN (
            SELECT agu.user_id FROM access_group_users agu
            JOIN access_groups ag ON ag.id = agu.group_id WHERE ag.ssh_enabled = 1
        )
    """)
    )
    op.drop_table("access_group_users")
    op.drop_column("access_groups", "ssh_enabled")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM users WHERE ssh_access = 1")):
        raise RuntimeError(
            "Remove SSH roles explicitly before downgrade; group scopes cannot be reconstructed"
        )
    op.add_column("access_groups", sa.Column("ssh_enabled", sa.Boolean(), nullable=False, server_default="0"))
    op.create_table(
        "access_group_users",
        sa.Column(
            "group_id", sa.String(36), sa.ForeignKey("access_groups.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_access_group_users_user_id", "access_group_users", ["user_id"])
    op.drop_column("users", "ssh_access")
