"""Isolated physical cabinet position and VM label fixture; no workers/network I/O."""

import os

import uvicorn
from netrix.core import settings
from sqlalchemy import select
from vlan_configuration_fixture import m, main, observe, session_factory

os.environ["NETRIX_PUBLIC_URL"] = "http://127.0.0.1:8217"
settings.cache_clear()

with session_factory()() as db:
    vlan = db.scalar(select(m.VLAN))
    campus = db.get(m.Site, vlan.site_id)
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
    cabinet.name, cabinet.sub_site_id = "4", room.id
    device = m.Device(name="SV-ID-01", management_ip="192.0.2.11", vrf_id=vlan.vrf_id, kind="server")
    db.add(device)
    db.flush()
    db.add(m.RackPlacement(cabinet_id=cabinet.id, device_id=device.id, start_unit=13, units=1))
    observe(db, vlan, "192.0.2.11", "icmp", "fixture-physical", {"reachability": "reachable"})
    db.commit()

uvicorn.run(main.app, host="127.0.0.1", port=8217, log_level="warning")
