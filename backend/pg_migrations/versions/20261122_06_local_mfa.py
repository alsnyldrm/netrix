"""Mandatory local Authenticator enrollment; identity stays in yonetim.users."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_06"
down_revision = "20261122_05"
branch_labels = depends_on = None


def upgrade():
    for column in (
        sa.Column("encrypted_mfa_secret", sa.Text()),
        sa.Column("encrypted_mfa_pending", sa.Text()),
        sa.Column("mfa_challenge_hash", sa.String(64)),
        sa.Column("mfa_expires_at", sa.DateTime(timezone=True)),
        sa.Column("mfa_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mfa_last_step", sa.BigInteger()),
    ):
        op.add_column("users", column, schema="yonetim")
    op.create_unique_constraint(
        "uq_users_mfa_challenge_hash", "users", ["mfa_challenge_hash"], schema="yonetim"
    )
    # Existing local sessions predate the second factor and must authenticate again.
    op.execute(
        "DELETE FROM yonetim.auth_sessions WHERE user_id IN (SELECT id FROM yonetim.users WHERE auth_source = 'local')"
    )


def downgrade():
    op.drop_constraint("uq_users_mfa_challenge_hash", "users", schema="yonetim")
    for name in (
        "mfa_last_step",
        "mfa_attempts",
        "mfa_expires_at",
        "mfa_challenge_hash",
        "encrypted_mfa_pending",
        "encrypted_mfa_secret",
    ):
        op.drop_column("users", name, schema="yonetim")
