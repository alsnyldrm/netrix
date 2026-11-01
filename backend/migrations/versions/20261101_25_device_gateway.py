"""Add the user-managed gateway flag, off for existing devices."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_25"
down_revision = "20261101_24"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("devices", sa.Column("is_gateway", sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("devices", "is_gateway")
