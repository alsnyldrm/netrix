"""Add explicit per-device SSH host key trust, disabled for all existing devices."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_04"
down_revision = "20261030_03"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "devices", sa.Column("ssh_trust_host_key", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade():
    op.drop_column("devices", "ssh_trust_host_key")
