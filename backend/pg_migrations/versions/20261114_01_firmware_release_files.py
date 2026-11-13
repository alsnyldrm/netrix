"""Attach a document without changing existing firmware release text."""

import sqlalchemy as sa
from alembic import op

revision = "20261114_01"
down_revision = "20261113_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "firmware_release_files",
        sa.Column(
            "image_id",
            sa.String(36),
            sa.ForeignKey("firmware.firmware_images.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("filename", sa.String(180), nullable=False),
        sa.Column("media_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 20971520", name="ck_fw_release_size"),
        schema="firmware",
    )
    if op.get_bind().dialect.name == "postgresql" and op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='netrix_app')")
    ):
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON firmware.firmware_release_files TO netrix_app")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM firmware.firmware_release_files)")):
        raise RuntimeError("Release note files must be preserved before downgrade")
    op.drop_table("firmware_release_files", schema="firmware")
