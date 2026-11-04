"""Persist each account's selected avatar or normalized private photo."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_47"
down_revision = "20261104_46"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_avatars",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("preset_id", sa.String(40), nullable=True),
        sa.Column("image", sa.LargeBinary(), nullable=True),
        sa.Column("version", sa.String(36), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(preset_id IS NULL AND image IS NOT NULL) OR (preset_id IS NOT NULL AND image IS NULL)",
            name="ck_user_avatar_source",
        ),
    )


def downgrade():
    op.drop_table("user_avatars")
