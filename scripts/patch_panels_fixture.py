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
    other_room = m.Site(
        name="Elektrik Odası",
        code="01-000012",
        parent_id=campus.id,
        institution_id=campus.institution_id,
        floor_number="L-1",
        department_name="A",
    )
    db.add(other_room)
    db.flush()
    other_cabinet = m.Cabinet(name="01", site_id=campus.id, sub_site_id=other_room.id, units=42)
    db.add(other_cabinet)
    db.flush()
    other_panel = m.PatchPanel(
        cabinet_id=other_cabinet.id, name="FIBER-01", kind="fiber", start_unit=41, units=1, port_count=2
    )
    db.add(other_panel)
    db.flush()
    db.add_all([m.PatchPort(panel_id=other_panel.id, position=n, number=str(n)) for n in (1, 2)])
    db.commit()

uvicorn.run(main.app, host="127.0.0.1", port=8215, log_level="warning")
