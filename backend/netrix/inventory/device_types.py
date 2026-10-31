"""Initial catalog for disposable create_all fixtures; production uses Alembic."""

from sqlalchemy import select

from .. import models as m

DEFAULT_TYPES = {
    "switch": "Switch",
    "router": "Router",
    "firewall": "Firewall",
    "server": "Sunucu",
    "storage": "Storage",
    "san_switch": "SAN Switch",
    "other": "Diğer",
}


def seed_defaults(db):
    existing = set(db.scalars(select(m.DeviceType.code)))
    for code, name in DEFAULT_TYPES.items():
        if code not in existing:
            db.add(m.DeviceType(code=code, name=name))
    db.flush()
