"""Add cabinet and operating system catalogs without changing IP observations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261031_14"
down_revision = "20261031_13"
branch_labels = None
depends_on = None


def upgrade():
    timestamp = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")
    for name, length in (("cabinets", 120), ("operating_systems", 190)):
        columns = [
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("created_at", timestamp, nullable=False),
            sa.Column("updated_at", timestamp, nullable=False),
            sa.Column("name", sa.String(length), nullable=False),
            sa.Column("description", sa.String(400), nullable=False),
            sa.UniqueConstraint("name"),
        ]
        if name == "cabinets":
            columns.append(sa.Column("site_id", sa.String(36), sa.ForeignKey("sites.id"), nullable=True))
        op.create_table(name, *columns)
    op.create_index("ix_cabinets_site_id", "cabinets", ["site_id"])


def downgrade():
    db = op.get_bind()
    for table in ("cabinets", "operating_systems"):
        if db.scalar(sa.text(f"SELECT COUNT(*) FROM {table}")):
            raise RuntimeError("IPAM catalogs contain data; export or remove it before downgrade")
    op.drop_table("cabinets")
    op.drop_table("operating_systems")
