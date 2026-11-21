"""Add the blacklist workspace and its references to managed devices."""

import sqlalchemy as sa
from alembic import op

revision = "20261122_01"
down_revision = "20261116_04"
branch_labels = None
depends_on = None
SCHEMA = "kara_liste"


def entity_columns():
    return (
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade():
    op.execute(sa.schema.CreateSchema(SCHEMA))
    op.create_table(
        "acl_groups",
        *entity_columns(),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("profiles", sa.dialects.postgresql.JSONB(), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "blacklist_entries",
        *entity_columns(),
        sa.Column("address", sa.String(45), nullable=False, unique=True),
        sa.Column("description", sa.String(300), nullable=False),
        schema=SCHEMA,
    )
    op.create_table(
        "acl_group_devices",
        sa.Column("group_id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(36), primary_key=True),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["kara_liste.acl_groups.id"],
            ondelete="CASCADE",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["envanter.devices.id"],
            ondelete="CASCADE",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "blacklist_entry_groups",
        sa.Column("entry_id", sa.String(36), primary_key=True),
        sa.Column("group_id", sa.String(36), primary_key=True),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["kara_liste.blacklist_entries.id"],
            ondelete="CASCADE",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["kara_liste.acl_groups.id"],
            deferrable=True,
            initially="IMMEDIATE",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_kara_liste_acl_group_devices_device_id", "acl_group_devices", ["device_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_kara_liste_blacklist_entry_groups_group_id",
        "blacklist_entry_groups",
        ["group_id"],
        schema=SCHEMA,
    )
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'netrix_app') THEN
                GRANT USAGE ON SCHEMA kara_liste TO netrix_app;
                GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA kara_liste TO netrix_app;
            END IF;
        END $$;
    """)


def downgrade():
    for table in ("blacklist_entry_groups", "acl_group_devices", "blacklist_entries", "acl_groups"):
        op.drop_table(table, schema=SCHEMA)
    op.execute(sa.schema.DropSchema(SCHEMA))
