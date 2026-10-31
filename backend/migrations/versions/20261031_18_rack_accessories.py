"""Passive cabinet organizers, independent of managed devices."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261031_18"
down_revision = "20261031_17"
branch_labels = None
depends_on = None


def upgrade():
    stamp = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")
    op.create_table(
        "rack_accessories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", stamp, nullable=False),
        sa.Column("updated_at", stamp, nullable=False),
        sa.Column("cabinet_id", sa.String(36), sa.ForeignKey("cabinets.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("start_unit", sa.Integer(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.CheckConstraint("kind = 'brush_organizer'", name="ck_rack_accessory_kind"),
        sa.CheckConstraint(
            "start_unit >= 1 AND units >= 1 AND start_unit + units - 1 <= 60",
            name="ck_rack_accessory_position",
        ),
    )
    op.create_index("ix_rack_accessories_cabinet_id", "rack_accessories", ["cabinet_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM rack_accessories")):
        raise RuntimeError("Rack accessories exist; export them before downgrade")
    op.drop_table("rack_accessories")
