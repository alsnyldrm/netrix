"""PostgreSQL baseline: table ownership by menu, preserving existing identifiers."""

from pathlib import Path

from alembic import op

revision = "20261106_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Frozen DDL: future model changes cannot change this historical migration.
    ddl = Path(__file__).with_name("20261106_01.sql").read_text()
    for statement in ddl.split(";\n"):
        if statement.strip():
            op.execute(statement)
    # Refuse a nonempty public schema rather than hiding unexpected tables.
    op.execute("DROP SCHEMA IF EXISTS public")


def downgrade():
    raise RuntimeError("Cross-engine data migration requires the verified cutover rollback procedure")
