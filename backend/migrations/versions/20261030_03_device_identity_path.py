"""Add a separate REST endpoint for device identity, retaining existing device data."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_03"
down_revision = "20261029_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "devices", sa.Column("identity_path", sa.String(200), nullable=False, server_default="/api/system")
    )


def downgrade():
    op.drop_column("devices", "identity_path")
