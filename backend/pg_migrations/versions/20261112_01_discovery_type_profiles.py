"""Map device types to SNMP profiles per discovery scope."""

import sqlalchemy as sa
from alembic import op

revision = "20261112_01"
down_revision = "20261111_02"
branch_labels = None
depends_on = None

SCHEMA = "envanter"
TABLE = "discovery_scope_type_profiles"


def upgrade():
    op.create_table(
        TABLE,
        sa.Column(
            "scope_id",
            sa.String(36),
            sa.ForeignKey("envanter.discovery_scopes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "device_kind",
            sa.String(20),
            sa.ForeignKey("envanter.device_types.code", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("credential_id", sa.String(36), sa.ForeignKey("yonetim.credentials.id"), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_envanter_discovery_scope_type_profiles_device_kind", TABLE, ["device_kind"], schema=SCHEMA
    )
    op.create_index(
        "ix_envanter_discovery_scope_type_profiles_credential_id", TABLE, ["credential_id"], schema=SCHEMA
    )
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='netrix_app')")):
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON envanter.discovery_scope_type_profiles TO netrix_app"
        )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM envanter.discovery_scope_type_profiles)")):
        raise RuntimeError("Discovery device type mappings must be preserved before downgrade")
    op.drop_table(TABLE, schema=SCHEMA)
