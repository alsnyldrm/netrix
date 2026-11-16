"""Retain deleted identity references for audit and operational history."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_04"
down_revision = "20261116_03"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True)), schema="yonetim")
    op.create_check_constraint(
        "ck_user_deleted_inactive", "users", "deleted_at IS NULL OR NOT is_active", schema="yonetim"
    )
    op.create_index(
        "uq_users_auth_source_current_email",
        "users",
        ["auth_source", "email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        schema="yonetim",
    )
    op.drop_constraint("uq_users_auth_source_email", "users", type_="unique", schema="yonetim")


def downgrade():
    # Fail atomically if a deleted email has already been reused.
    op.create_unique_constraint("uq_users_auth_source_email", "users", ["auth_source", "email"], schema="yonetim")
    op.drop_index("uq_users_auth_source_current_email", table_name="users", schema="yonetim")
    op.drop_constraint("ck_user_deleted_inactive", "users", type_="check", schema="yonetim")
    op.drop_column("users", "deleted_at", schema="yonetim")
