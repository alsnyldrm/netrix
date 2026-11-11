"""Store the manual VIP marker in the device inventory."""

import sqlalchemy as sa
from alembic import op

revision = "20261111_01"
down_revision = "20261110_02"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "devices",
        sa.Column("is_vip", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="envanter",
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM envanter.devices WHERE is_vip)")):
        raise RuntimeError("Device VIP markers must be preserved before downgrade")
    op.drop_column("devices", "is_vip", schema="envanter")
