"""Isolated cabinet/patch browser fixture, without workers or real network I/O."""

import uvicorn
from sqlalchemy import select
from vlan_configuration_fixture import m, main, session_factory

with session_factory()() as db:
    for n, name in [(1, "A1"), (2, "B2")]:
        device = db.scalar(select(m.Device).where(m.Device.name == f"Switch {n}"))
        db.add(m.Interface(device_id=device.id, name=name, is_managed=True))
    db.commit()

uvicorn.run(main.app, host="127.0.0.1", port=8215, log_level="warning")
