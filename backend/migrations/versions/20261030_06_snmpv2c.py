"""Allow encrypted SNMPv2c community profiles without changing existing secrets."""

import sqlalchemy as sa
from alembic import op

revision = "20261030_06"
down_revision = "20261030_05"
branch_labels = None
depends_on = None


def replace_constraint(expression):
    with op.batch_alter_table("credentials") as batch:
        batch.drop_constraint("ck_credential_protocol", type_="check")
        batch.create_check_constraint("ck_credential_protocol", expression)


def upgrade():
    replace_constraint("protocol in ('snmpv3','snmpv2c','ssh','rest')")


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM credentials WHERE protocol = 'snmpv2c'")):
        raise RuntimeError("Remove SNMPv2c profiles before downgrading; credentials will not be deleted")
    replace_constraint("protocol in ('snmpv3','ssh','rest')")
