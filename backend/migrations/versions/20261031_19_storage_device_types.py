"""Additional physical device types for mixed cabinet inventories."""

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "20261031_19"
down_revision = "20261031_18"
branch_labels = None
depends_on = None
TYPES = {"storage": "Storage", "san_switch": "SAN Switch"}


def upgrade():
    db = op.get_bind()
    for code, name in TYPES.items():
        if db.scalar(
            sa.text("SELECT id FROM device_types WHERE code=:code OR name=:name"),
            {"code": code, "name": name},
        ):
            continue
        db.execute(
            sa.text(
                "INSERT INTO device_types (id,code,name,description,created_at,updated_at) VALUES (:id,:code,:name,'',:stamp,:stamp)"
            ),
            {
                "id": str(uuid5(NAMESPACE_URL, "netrix:device-type:" + code)),
                "code": code,
                "name": name,
                "stamp": datetime.now(timezone.utc).replace(tzinfo=None),
            },
        )


def downgrade():
    # These remain valid, user-manageable catalog entries on the previous schema.
    # Preserve both referenced types and any operator renames instead of deleting inventory metadata.
    pass
