"""Persist the operator-managed gateway designation on VLAN IP addresses."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_26"
down_revision = "20261101_25"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ip_addresses", sa.Column("is_gateway", sa.Boolean(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("ip_addresses", "is_gateway")
