"""Each device belongs to one firmware group; preserve legacy conflicts for review."""

import sqlalchemy as sa
from alembic import op

revision = "20261103_39"
down_revision = "20261103_38"
branch_labels = None
depends_on = None


def upgrade():
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT device_id FROM firmware_group_members GROUP BY device_id HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate:
        raise RuntimeError("Resolve duplicate firmware group memberships explicitly before migration")
    op.create_unique_constraint("uq_firmware_member_device", "firmware_group_members", ["device_id"])
    op.drop_index("ix_firmware_group_members_device_id", table_name="firmware_group_members")


def downgrade():
    op.create_index("ix_firmware_group_members_device_id", "firmware_group_members", ["device_id"])
    op.drop_constraint("uq_firmware_member_device", "firmware_group_members", type_="unique")
