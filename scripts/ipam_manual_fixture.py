"""Disposable manual metadata and duplicate room/cabinet fixture, no device traffic."""

import os
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("vlan_configuration_fixture.py")))

from netrix import main  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import session_factory, settings  # noqa: E402
from netrix.ipam.service import observe  # noqa: E402
from sqlalchemy import select  # noqa: E402

os.environ["NETRIX_PUBLIC_URL"] = "http://127.0.0.1:8224"
settings.cache_clear()

with session_factory()() as db:
    vlan = db.scalar(select(m.VLAN))
    site = db.get(m.Site, vlan.site_id)
    site.name = "FBU-F"
    rooms = []
    for index, (floor, department, name) in enumerate(
        [("L-0", "A", "Sunucu Odası"), ("L-1", "A", "Elektrik Odası"), ("L-1", "B", "Elektrik Odası")]
    ):
        room = m.Site(
            name=name,
            code=f"01-0000{11 + index}",
            institution_id=site.institution_id,
            parent_id=site.id,
            floor_number=floor,
            department_name=department,
        )
        db.add(room)
        db.flush()
        db.add(m.Cabinet(name="02", site_id=site.id, sub_site_id=room.id, units=42))
        rooms.append(room)
    for last in (11, 12):
        row = observe(db, vlan, f"192.0.2.{last}", "icmp", vlan.id, {"reachability": "reachable"})
        row.institution_id, row.site_id, row.sub_site_id = site.institution_id, site.id, rooms[0].id
        row.hostname, row.operating_system, row.cabinet = f"MANUAL-FW-{last}", "FortiOS", "02"
        observe(db, vlan, row.address, "dns", vlan.dns_server_id, {"hostname": f"dns-{last}.example.test"})
    db.add(m.OperatingSystem(name="FortiOS"))
    db.add(m.OperatingSystem(name="Linux"))
    db.commit()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8224, log_level="warning")
