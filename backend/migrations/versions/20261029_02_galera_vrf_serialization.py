"""Make VRF writes participate in Galera certification across nodes."""

import sqlalchemy as sa
from alembic import op

revision = "20261029_02"
down_revision = "782797ae48d5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("vrfs", sa.Column("lock_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("vrfs", "lock_version")
