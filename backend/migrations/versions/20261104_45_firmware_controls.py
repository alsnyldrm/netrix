"""Ten concurrent firmware targets, explicit forced stop and retained plan removal."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261104_45"
down_revision = "20261103_44"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("firmware_plans") as batch:
        batch.drop_constraint("ck_fw_plan_concurrency", type_="check")
        batch.create_check_constraint("ck_fw_plan_concurrency", "concurrency between 1 and 10")
        batch.add_column(
            sa.Column("force_stop_requested", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column(
                "deleted_at", sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb"), nullable=True
            )
        )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM firmware_plans WHERE concurrency > 4 OR force_stop_requested = 1 OR deleted_at IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Firmware controls contain retained state; refuse a lossy downgrade")
    with op.batch_alter_table("firmware_plans") as batch:
        batch.drop_column("deleted_at")
        batch.drop_column("force_stop_requested")
        batch.drop_constraint("ck_fw_plan_concurrency", type_="check")
        batch.create_check_constraint("ck_fw_plan_concurrency", "concurrency between 1 and 4")
