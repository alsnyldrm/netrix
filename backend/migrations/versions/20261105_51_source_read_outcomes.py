"""Keep per-table collection outcomes without replacing canonical source facts."""

import sqlalchemy as sa
from alembic import op
from netrix.core import UTCDateTime

revision = "20261105_51"
down_revision = "20261104_50"
branch_labels = None
depends_on = None


def upgrade():
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("source_unsupported_tables")}
    for col in (
        sa.Column("status", sa.String(20), nullable=False, server_default="unsupported"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80), nullable=False, server_default=""),
        sa.Column("attempted_at", UTCDateTime(), nullable=True),
        sa.Column("successful_at", UTCDateTime(), nullable=True),
    ):
        if col.name not in existing:
            op.add_column("source_unsupported_tables", col)


def downgrade():
    for name in ("successful_at", "attempted_at", "error_code", "row_count", "status"):
        op.drop_column("source_unsupported_tables", name)
