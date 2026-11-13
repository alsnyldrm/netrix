"""Reference the canonical neighbor that supplied an IP hostname."""

import sqlalchemy as sa
from alembic import op

revision = "20261113_01"
down_revision = "20261112_02"
branch_labels = None
depends_on = None

SCHEMA = "ip_adres_yonetimi"
TABLE = "ip_resolution_fields"
INDEX = "ix_ip_adres_yonetimi_ip_resolution_fields_neighbor_id"


def upgrade():
    op.add_column(TABLE, sa.Column("neighbor_id", sa.String(36)), schema=SCHEMA)
    op.create_foreign_key(
        "fk_ip_resolution_fields_neighbor", TABLE, "neighbor_links", ["neighbor_id"], ["id"],
        source_schema=SCHEMA, referent_schema="baglanti", ondelete="CASCADE",
    )
    op.create_index(INDEX, TABLE, ["neighbor_id"], schema=SCHEMA)


def downgrade():
    op.execute("DELETE FROM ip_adres_yonetimi.ip_resolution_fields WHERE neighbor_id IS NOT NULL")
    op.drop_index(INDEX, table_name=TABLE, schema=SCHEMA)
    op.drop_column(TABLE, "neighbor_id", schema=SCHEMA)
