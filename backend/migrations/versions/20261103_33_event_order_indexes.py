"""Index event and audit journals by their list order (newest first)."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_33"
down_revision = "20261102_32"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_change_events_created_at", "change_events", [sa.text("created_at DESC"), "id"])
    op.create_index("ix_audit_events_created_at", "audit_events", [sa.text("created_at DESC"), "id"])


def downgrade():
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_change_events_created_at", table_name="change_events")
