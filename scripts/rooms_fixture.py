"""Isolated room/cabinet fixture; no workers or production/network access."""

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
    cabinet = db.scalar(select(m.Cabinet))
    cabinet.name = "4"
    cabinet.sub_site_id = room.id
    device = db.scalar(select(m.Device).where(m.Device.name == "Switch 1"))
    db.add(m.RackPlacement(cabinet_id=cabinet.id, device_id=device.id, start_unit=13, units=1))
    for code, name, floor, department in [
        ("01-000012", "Storage Odası", "L-10", "C"),
        ("01-000013", "Çalışma Odası", "L-2", "A"),
        ("01-000014", "Arşiv Odası", "L-0", "B"),
    ]:
        db.add(
            m.Site(
                name=name,
                code=code,
                parent_id=campus.id,
                institution_id=campus.institution_id,
                floor_number=floor,
                department_name=department,
            )
        )
    db.commit()

uvicorn.run(main.app, host="127.0.0.1", port=8215, log_level="warning")
