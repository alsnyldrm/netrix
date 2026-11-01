"""Isolated cabinet/patch browser fixture, without workers or real network I/O."""

import uvicorn
from sqlalchemy import select
from vlan_configuration_fixture import m, main, session_factory

with session_factory()() as db:
    campus = db.scalar(select(m.Site).where(m.Site.parent_id.is_(None)))
    room = m.Site(
        name="Sunucu Odası",
        code="01-000011",
        parent_id=campus.id,
        institution_id=campus.institution_id,
        floor_number="L-0",
        department_name="A",
    )
    db.add(room)
    db.flush()
    db.scalar(select(m.Cabinet)).sub_site_id = room.id
    for n, name in [(1, "A1"), (2, "B2")]:
        device = db.scalar(select(m.Device).where(m.Device.name == f"Switch {n}"))
        db.add(m.Interface(device_id=device.id, name=name, is_managed=True))
    db.commit()

uvicorn.run(main.app, host="127.0.0.1", port=8215, log_level="warning")
