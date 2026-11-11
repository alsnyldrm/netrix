"""Allow hourly IPAM scan groups."""

import sqlalchemy as sa
from alembic import op

revision = "20261111_02"
down_revision = "20261111_01"
branch_labels = None
depends_on = None

SCHEMA = "ip_adres_yonetimi"
TABLE = "ipam_scan_groups"
CONSTRAINT = "ck_ipam_scan_frequency"


def upgrade():
    op.drop_constraint(CONSTRAINT, TABLE, type_="check", schema=SCHEMA)
    op.create_check_constraint(
        CONSTRAINT, TABLE, "frequency in ('hourly','daily','weekly','monthly')", schema=SCHEMA
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM ip_adres_yonetimi.ipam_scan_groups WHERE frequency = 'hourly')")
    ):
        raise RuntimeError("Hourly IPAM scan groups must be preserved before downgrade")
    op.drop_constraint(CONSTRAINT, TABLE, type_="check", schema=SCHEMA)
    op.create_check_constraint(CONSTRAINT, TABLE, "frequency in ('daily','weekly','monthly')", schema=SCHEMA)
