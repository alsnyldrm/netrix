"""Keep actor identity and safe field changes in the audit journal."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_46"
down_revision = "20261104_45"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_events", sa.Column("details", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("audit_events", "details")
