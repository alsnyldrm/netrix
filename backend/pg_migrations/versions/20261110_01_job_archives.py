"""Store atomic task ZIP archives in the owning operations schema."""

import sqlalchemy as sa
from alembic import op

revision = "20261110_01"
down_revision = "20261106_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_archives",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filename", sa.String(160), nullable=False),
        sa.Column("job_count", sa.Integer(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.CheckConstraint("job_count > 0 AND size_bytes > 0", name="ck_job_archive_size"),
        sa.CheckConstraint("source in ('manual','scheduled')", name="ck_job_archive_source"),
        schema="operasyon",
    )
    op.create_index("ix_job_archives_created_at", "job_archives", ["created_at"], schema="operasyon")
    op.add_column(
        "jobs", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True), schema="operasyon"
    )
    op.create_index("ix_jobs_archived_at", "jobs", ["archived_at"], schema="operasyon")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='netrix_app')")):
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON operasyon.job_archives TO netrix_app")


def downgrade():
    # Never silently discard archives, or resurrect already-deleted ZIP history.
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM operasyon.jobs WHERE archived_at IS NOT NULL)")
    ):
        raise RuntimeError("Archived task history must be explicitly reconciled before downgrade")
    op.drop_index("ix_jobs_archived_at", table_name="jobs", schema="operasyon")
    op.drop_column("jobs", "archived_at", schema="operasyon")
    op.drop_table("job_archives", schema="operasyon")
