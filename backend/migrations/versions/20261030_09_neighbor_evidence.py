"""Preserve neighbor evidence and separate current topology from historical records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261030_09"
down_revision = "20261030_08"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("topology_links", sa.Column("evidence", sa.JSON(), nullable=True))
    op.execute("UPDATE topology_links SET evidence = '{}' WHERE evidence IS NULL")
    op.alter_column("topology_links", "evidence", existing_type=sa.JSON(), nullable=False)
    op.add_column("topology_links", sa.Column("is_current", sa.Boolean(), nullable=False, server_default="1"))
    op.add_column("topology_links", sa.Column("last_seen_at", DATETIME(fsp=6), nullable=True))
    op.execute("UPDATE topology_links SET last_seen_at = updated_at WHERE source <> 'manual'")
    op.create_index("ix_topology_links_is_current", "topology_links", ["is_current"])


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM topology_links WHERE is_current = 0 OR evidence <> '{}'")
    ):
        raise RuntimeError("Neighbor evidence/history exists; downgrade would discard it")
    op.drop_index("ix_topology_links_is_current", table_name="topology_links")
    op.drop_column("topology_links", "last_seen_at")
    op.drop_column("topology_links", "is_current")
    op.drop_column("topology_links", "evidence")
