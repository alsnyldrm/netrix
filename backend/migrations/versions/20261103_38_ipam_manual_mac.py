"""Store manual IPAM MAC metadata separately from source observations."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_38"
down_revision = "20261103_36"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ip_addresses", sa.Column("mac_address", sa.String(17), nullable=False, server_default=""))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM ip_addresses WHERE mac_address <> ''")):
        raise RuntimeError("Clear saved manual MAC addresses explicitly before downgrade")
    op.drop_column("ip_addresses", "mac_address")
