"""Keep user-written release notes with the owning firmware image."""

import sqlalchemy as sa
from alembic import op

revision = "20261110_02"
down_revision = "20261110_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "firmware_images",
        sa.Column("release_notes", sa.Text(), nullable=False, server_default=""),
        schema="firmware",
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM firmware.firmware_images WHERE release_notes <> '')")
    ):
        raise RuntimeError("Firmware release notes must be preserved before downgrade")
    op.drop_column("firmware_images", "release_notes", schema="firmware")
