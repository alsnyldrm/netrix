"""Separate fiber grade from mode, retaining existing manual cabling records."""

import sqlalchemy as sa
from alembic import op

revision = "20261101_30"
down_revision = "20261101_29"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("patch_ports", sa.Column("fiber_mode", sa.String(12), nullable=False, server_default=""))
    op.create_check_constraint(
        "ck_patch_fiber_mode", "patch_ports", "fiber_mode in ('','multimode','singlemode')"
    )
    op.execute(
        sa.text(
            "UPDATE patch_ports SET fiber_mode = CASE cable_model "
            "WHEN 'Multimode MM' THEN 'multimode' WHEN 'Singlemode SM' THEN 'singlemode' END, "
            "cable_model = '' WHERE cable_model IN ('Multimode MM','Singlemode SM')"
        )
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM patch_ports WHERE fiber_mode <> '' AND cable_model <> ''")
    ):
        raise RuntimeError("Independent fiber model and mode exist; export them before downgrade")
    op.execute(
        sa.text(
            "UPDATE patch_ports SET cable_model = CASE fiber_mode "
            "WHEN 'multimode' THEN 'Multimode MM' WHEN 'singlemode' THEN 'Singlemode SM' END "
            "WHERE fiber_mode <> ''"
        )
    )
    op.drop_constraint("ck_patch_fiber_mode", "patch_ports", type_="check")
    op.drop_column("patch_ports", "fiber_mode")
