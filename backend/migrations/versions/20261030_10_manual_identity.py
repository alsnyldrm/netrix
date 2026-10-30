"""Remember manual inventory preferences separately from protocol observations."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_10"
down_revision = "20261030_09"
branch_labels = None
depends_on = None


def upgrade():
    # Existing values have no reliable per-field authorship; do not invent it.
    op.add_column(
        "devices", sa.Column("manual_identity_fields", sa.JSON(), nullable=False, server_default="[]")
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM devices WHERE JSON_LENGTH(manual_identity_fields) > 0")
    ):
        raise RuntimeError("Manual identity preferences exist; downgrade would discard them")
    op.drop_column("devices", "manual_identity_fields")
