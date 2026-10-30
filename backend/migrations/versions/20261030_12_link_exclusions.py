"""Remember deleted neighbor records so discovery cannot add them again."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_12"
down_revision = "20261030_11"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "topology_links",
        sa.Column("auto_add_excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM topology_links WHERE auto_add_excluded = 1")):
        raise RuntimeError("Deleted neighbor exclusions exist; downgrade would allow rediscovery")
    op.drop_column("topology_links", "auto_add_excluded")
