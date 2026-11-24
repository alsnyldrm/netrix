"""IP descriptions belong to the existing IPAM address record."""

import sqlalchemy as sa
from alembic import op

revision = "20261124_02"
down_revision = "20261124_01"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "ip_addresses",
        sa.Column("description", sa.String(400), nullable=False, server_default=""),
        schema="ip_adres_yonetimi",
    )


def downgrade():
    op.drop_column("ip_addresses", "description", schema="ip_adres_yonetimi")
