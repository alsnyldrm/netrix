"""Allow independent local and Entra accounts to use the same email."""

from alembic import op

revision = "20261116_02"
down_revision = "20261116_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_users_auth_source_email", "users", ["auth_source", "email"], schema="yonetim"
    )
    op.drop_constraint("users_email_key", "users", type_="unique", schema="yonetim")


def downgrade():
    # Adding the stronger constraint first refuses duplicates atomically.
    # Never delete or merge an account to reinstate global uniqueness.
    op.create_unique_constraint("users_email_key", "users", ["email"], schema="yonetim")
    op.drop_constraint("uq_users_auth_source_email", "users", type_="unique", schema="yonetim")
