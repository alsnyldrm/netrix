"""Persist observed device software versions, empty until a successful device read."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_29"
down_revision = "20261101_28"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("devices", sa.Column("software_version", sa.String(120), nullable=False, server_default=""))


def downgrade():
    op.drop_column("devices", "software_version")
