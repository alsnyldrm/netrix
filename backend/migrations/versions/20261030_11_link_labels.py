"""Keep operator neighbor labels separate from discovered values."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_11"
down_revision = "20261030_10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("topology_links", sa.Column("manual_remote_name", sa.String(190), nullable=True))
    op.add_column("topology_links", sa.Column("manual_remote_port", sa.String(120), nullable=True))
    op.add_column("topology_links", sa.Column("manual_remote_device_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_link_manual_remote_device", "topology_links", "devices", ["manual_remote_device_id"], ["id"]
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT COUNT(*) FROM topology_links WHERE manual_remote_name IS NOT NULL OR manual_remote_port IS NOT NULL"
        )
    ):
        raise RuntimeError("Manual neighbor labels exist; downgrade would discard them")
    op.drop_constraint("fk_link_manual_remote_device", "topology_links", type_="foreignkey")
    for column in ("manual_remote_device_id", "manual_remote_port", "manual_remote_name"):
        op.drop_column("topology_links", column)
