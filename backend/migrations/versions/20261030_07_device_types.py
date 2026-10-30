"""Managed device type catalog; preserve existing device kind identifiers."""

from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

revision = "20261030_07"
down_revision = "20261030_06"
branch_labels = None
depends_on = None
DEFAULTS = {
    "switch": "Switch",
    "router": "Router",
    "firewall": "Firewall",
    "server": "Sunucu",
    "other": "Diğer",
}


def upgrade():
    timestamp = sa.DateTime().with_variant(DATETIME(fsp=6), "mysql", "mariadb")
    table = op.create_table(
        "device_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", timestamp, nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(400), nullable=False),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    kinds = dict(DEFAULTS)
    for code in op.get_bind().scalars(sa.text("SELECT DISTINCT kind FROM devices")):
        if code not in kinds:
            kinds[code] = "Tür · " + code
    stamp = datetime.now(timezone.utc).replace(tzinfo=None)
    op.bulk_insert(
        table,
        [
            dict(id=str(uuid4()), created_at=stamp, updated_at=stamp, code=code, name=name, description="")
            for code, name in kinds.items()
        ],
    )
    with op.batch_alter_table("devices") as batch:
        batch.create_index("ix_devices_kind", ["kind"])
        batch.create_foreign_key("fk_device_type", "device_types", ["kind"], ["code"])


def downgrade():
    rows = op.get_bind().execute(sa.text("SELECT code, name, description FROM device_types")).all()
    if {r.code: r.name for r in rows} != DEFAULTS or any(r.description for r in rows):
        raise RuntimeError("Device type catalog has custom data; downgrade would lose it")
    with op.batch_alter_table("devices") as batch:
        batch.drop_constraint("fk_device_type", type_="foreignkey")
        batch.drop_index("ix_devices_kind")
    op.drop_table("device_types")
