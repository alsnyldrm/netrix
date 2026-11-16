"""Add management-owned SAML settings and stable identity bindings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261116_01"
down_revision = "20261114_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("auth_source", sa.String(10), nullable=False, server_default="local"),
        schema="yonetim",
    )
    op.create_check_constraint(
        "ck_user_auth_source", "users", "auth_source in ('local','saml')", schema="yonetim"
    )
    op.create_check_constraint(
        "ck_saml_no_super_admin", "users", "auth_source = 'local' OR role <> 'super_admin'", schema="yonetim"
    )
    op.create_table(
        "saml_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_saml_settings_singleton"),
        schema="yonetim",
    )
    op.create_table(
        "saml_identities",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("yonetim.users.id", deferrable=True, initially="IMMEDIATE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(400), nullable=False),
        sa.Column("manual_role", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("issuer", "subject", name="uq_saml_identity"),
        schema="yonetim",
    )
    op.execute("""
        DO $grant$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'netrix_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON yonetim.saml_settings, yonetim.saml_identities TO netrix_app;
          END IF;
        END $grant$
        """)


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM yonetim.saml_settings) OR EXISTS (SELECT 1 FROM yonetim.users WHERE auth_source = 'saml')"
        )
    ):
        raise RuntimeError("SAML settings and accounts must be preserved before downgrade")
    op.drop_table("saml_identities", schema="yonetim")
    op.drop_table("saml_settings", schema="yonetim")
    op.drop_constraint("ck_saml_no_super_admin", "users", type_="check", schema="yonetim")
    op.drop_constraint("ck_user_auth_source", "users", type_="check", schema="yonetim")
    op.drop_column("users", "auth_source", schema="yonetim")
