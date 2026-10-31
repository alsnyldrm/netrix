"""Ordered SNMP profiles for discovery, preserving existing primary profiles."""

import sqlalchemy as sa
from alembic import op

revision = "20261031_16"
down_revision = "20261031_15"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("discovery_scopes") as batch:
        batch.add_column(sa.Column("institution_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_discovery_scopes_institution_id", "institutions", ["institution_id"], ["id"]
        )
        batch.create_index("ix_discovery_scopes_institution_id", ["institution_id"])
    op.execute(
        sa.text(
            "UPDATE discovery_scopes SET institution_id = (SELECT institution_id FROM sites WHERE sites.id = discovery_scopes.site_id)"
        )
    )
    op.create_table(
        "discovery_scope_credentials",
        sa.Column(
            "scope_id",
            sa.String(36),
            sa.ForeignKey("discovery_scopes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("credential_id", sa.String(36), sa.ForeignKey("credentials.id"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("scope_id", "position"),
    )
    op.create_index(
        "ix_discovery_scope_credentials_credential_id", "discovery_scope_credentials", ["credential_id"]
    )
    op.execute(
        sa.text(
            "INSERT INTO discovery_scope_credentials (scope_id, credential_id, position) SELECT id, credential_id, 0 FROM discovery_scopes"
        )
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM discovery_scope_credentials WHERE position > 0")):
        raise RuntimeError("Multiple discovery profiles exist; retain one per scope before downgrade")
    if op.get_bind().scalar(
        sa.text(
            "SELECT COUNT(*) FROM discovery_scopes WHERE institution_id IS NOT NULL AND (site_id IS NULL OR NOT EXISTS (SELECT 1 FROM sites WHERE sites.id = discovery_scopes.site_id AND sites.institution_id = discovery_scopes.institution_id))"
        )
    ):
        raise RuntimeError(
            "Discovery institution assignments without matching locations exist; export them before downgrade"
        )
    op.drop_table("discovery_scope_credentials")
    with op.batch_alter_table("discovery_scopes") as batch:
        batch.drop_constraint("fk_discovery_scopes_institution_id", type_="foreignkey")
        batch.drop_index("ix_discovery_scopes_institution_id")
        batch.drop_column("institution_id")
