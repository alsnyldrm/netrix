"""Separate 54xx and 29xx firmware families without replacing images or history."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_48"
down_revision = "20261104_47"
branch_labels = None
depends_on = None


def family_check(values):
    with op.batch_alter_table("firmware_images") as batch:
        batch.drop_constraint("ck_fw_image_family", type_="check")
        batch.create_check_constraint("ck_fw_image_family", f"family in ({values})")


def upgrade():
    conn = op.get_bind()
    if conn.execute(
        sa.text(
            "SELECT 1 FROM firmware_images WHERE family='aos_s' AND NOT (UPPER(version) LIKE 'K.%' OR UPPER(version) LIKE 'KB.%' OR UPPER(version) LIKE 'WB.%' OR UPPER(version) LIKE 'WC.%') LIMIT 1"
        )
    ).first():
        raise RuntimeError(
            "An existing AOS-S image has an unknown branch; refuse arbitrary family assignment"
        )
    family_check("'aos_s','aos_s_54xx','aos_s_29xx','cx6100','hp1950'")
    conn.execute(
        sa.text(
            "UPDATE firmware_images SET family=CASE WHEN UPPER(version) LIKE 'K.%' OR UPPER(version) LIKE 'KB.%' THEN 'aos_s_54xx' ELSE 'aos_s_29xx' END WHERE family='aos_s'"
        )
    )
    family_check("'aos_s_54xx','aos_s_29xx','cx6100','hp1950'")


def downgrade():
    family_check("'aos_s','aos_s_54xx','aos_s_29xx','cx6100','hp1950'")
    op.get_bind().execute(
        sa.text("UPDATE firmware_images SET family='aos_s' WHERE family IN ('aos_s_54xx','aos_s_29xx')")
    )
    family_check("'aos_s','cx6100','hp1950'")
