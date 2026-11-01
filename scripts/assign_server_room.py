"""Explicit one-time operation requested by the owner; no sample records are created."""

from netrix import models as m
from netrix.core import session_factory
from netrix.identity.security import audit
from netrix.services import publish
from sqlalchemy import select

with session_factory()() as db:
    matches = list(
        db.scalars(
            select(m.Site)
            .where(m.Site.name == "Sunucu Odası", m.Site.parent_id.is_not(None))
            .with_for_update()
        )
    )
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one existing Sunucu Odası; no changes made")
    room = matches[0]
    user = db.scalar(
        select(m.User)
        .where(m.User.role == "admin", m.User.is_active.is_(True))
        .order_by(m.User.created_at)
        .limit(1)
    )
    if not user:
        raise RuntimeError("Active administrator required")
    cabinets = list(db.scalars(select(m.Cabinet).order_by(m.Cabinet.id).with_for_update()))
    # Cabinet records have no archive flag: all existing cabinet records are active.
    room.floor_number, room.department_name = "L-0", "A"
    for cabinet in cabinets:
        cabinet.site_id, cabinet.sub_site_id = room.parent_id, room.id
        cabinet.lock_version += 1
    audit(
        db,
        user,
        "room_assignment",
        "sites",
        room.id,
        f"Kullanıcı talebi: Sunucu Odası, kat L-0, bölüm A; {len(cabinets)} aktif kabinet bağlandı",
    )
    db.commit()
    publish()
    print(f"PASS: Sunucu Odası L-0 / A; {len(cabinets)} active cabinets assigned, placements preserved")
