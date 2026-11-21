"""Persist immutable per-device blacklist submissions beside their worker jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261122_02"
down_revision = "20261122_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "blacklist_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_id", sa.String(36), nullable=False),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False, unique=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entry_id"], ["kara_liste.blacklist_entries.id"], deferrable=True, initially="IMMEDIATE"
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["envanter.devices.id"], deferrable=True, initially="IMMEDIATE"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["operasyon.jobs.id"], deferrable=True, initially="IMMEDIATE"),
        schema="kara_liste",
    )
    for column in ("entry_id", "device_id"):
        op.create_index(
            "ix_kara_liste_blacklist_deliveries_" + column,
            "blacklist_deliveries",
            [column],
            schema="kara_liste",
        )
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname='netrix_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON kara_liste.blacklist_deliveries TO netrix_app;
            END IF;
        END $$;
    """)


def downgrade():
    op.drop_table("blacklist_deliveries", schema="kara_liste")
