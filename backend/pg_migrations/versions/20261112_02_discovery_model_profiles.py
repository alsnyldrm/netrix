"""Replace discovery device-type assignments with device-model assignments."""

from importlib import import_module

import sqlalchemy as sa
from alembic import op

revision = "20261112_02"
down_revision = "20261112_01"
branch_labels = None
depends_on = None

SCHEMA = "envanter"
TABLE = "discovery_scope_model_profiles"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column(
            "scope_id",
            sa.String(36),
            sa.ForeignKey("envanter.discovery_scopes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("device_model", sa.String(190), primary_key=True),
        sa.Column("credential_id", sa.String(36), sa.ForeignKey("yonetim.credentials.id"), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_envanter_discovery_scope_model_profiles_credential_id", TABLE, ["credential_id"], schema=SCHEMA
    )
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='netrix_app')")):
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON envanter.discovery_scope_model_profiles TO netrix_app"
        )
    op.drop_table("discovery_scope_type_profiles", schema=SCHEMA)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM envanter.discovery_scope_model_profiles)")):
        raise RuntimeError("Discovery device model mappings must be preserved before downgrade")
    op.drop_table(TABLE, schema=SCHEMA)
    import_module("pg_migrations.versions.20261112_01_discovery_type_profiles").upgrade()
