"""Disposable MariaDB schema/data validation; never connects to the production DB."""

import runpy
import subprocess

from netrix import models as m
from netrix import services
from netrix.core import engine, session_factory
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

assert engine().url.database == "netrix_test"


def migrate(action, revision):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", action, revision], check=True)


migrate("upgrade", "20261101_27")
with session_factory()() as db:
    legacy = m.Cabinet(name="4", units=42)
    db.add(legacy)
    db.commit()
    cabinet_id = legacy.id
migrate("upgrade", "head")
with session_factory()() as db:
    institution = m.Institution(name="Fixture", code="01")
    db.add(institution)
    db.flush()
    campus = m.Site(name="Campus", code="01-000001", institution_id=institution.id)
    db.add(campus)
    db.flush()
    rooms = [
        m.Site(
            name=f"Room {n}",
            code=f"01-00001{n}",
            parent_id=campus.id,
            institution_id=institution.id,
            floor_number="L-0",
            department_name="A",
        )
        for n in (1, 2)
    ]
    db.add_all(rooms)
    db.flush()
    legacy = db.get(m.Cabinet, cabinet_id)
    assert legacy.units == 42
    legacy.site_id, legacy.sub_site_id = campus.id, rooms[0].id
    db.add(m.Cabinet(name="4", site_id=campus.id, sub_site_id=rooms[1].id, units=42))
    db.commit()
    db.add(m.Cabinet(name="4", site_id=campus.id, sub_site_id=rooms[0].id, units=42))
    try:
        db.commit()
        raise AssertionError("Duplicate cabinet number in the same room accepted")
    except IntegrityError:
        db.rollback()
    assert db.scalar(select(m.Site.floor_number).where(m.Site.id == rooms[0].id)) == "L-0"
    assert db.scalar(select(m.Site.department_name).where(m.Site.id == rooms[0].id)) == "A"
# Verify the explicit owner-requested assignment independently of production data.
with session_factory()() as db:
    room = db.scalar(select(m.Site).where(m.Site.parent_id.is_not(None)).order_by(m.Site.code))
    room.name = "Sunucu Odası"
    cabinets = list(db.scalars(select(m.Cabinet).order_by(m.Cabinet.id)))
    cabinets[1].name = "5"
    db.add(
        m.User(
            email="fixture@example.test",
            display_name="Fixture",
            password_hash="isolated-fixture",
            role="admin",
        )
    )
    db.commit()
    room_id = room.id

services.publish = lambda: None
for _ in range(2):
    runpy.run_path("scripts/assign_server_room.py")
with session_factory()() as db:
    cabinets = list(db.scalars(select(m.Cabinet)))
    assert len(cabinets) == 2 and all(c.sub_site_id == room_id for c in cabinets)
    room = db.get(m.Site, room_id)
    assert (room.floor_number, room.department_name) == ("L-0", "A")
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
blocked = subprocess.run(
    ["alembic", "-c", "backend/alembic.ini", "downgrade", "20261101_27"], capture_output=True, text=True
)
assert blocked.returncode != 0 and "Room details exist" in blocked.stderr
with engine().begin() as db:
    db.execute(text("DELETE FROM cabinets WHERE id<>:id"), {"id": cabinet_id})
    db.execute(text("UPDATE cabinets SET sub_site_id=NULL, site_id=NULL"))
    db.execute(text("DELETE FROM sites WHERE parent_id IS NOT NULL"))
    db.execute(text("DELETE FROM sites"))
migrate("downgrade", "20261101_27")
migrate("upgrade", "head")
with engine().connect() as db:
    assert db.scalar(text("SELECT units FROM cabinets WHERE id=:id"), {"id": cabinet_id}) == 42
print(
    "PASS: room columns, existing cabinet preserved, room-scoped uniqueness, schema parity, guarded downgrade and re-upgrade"
)
