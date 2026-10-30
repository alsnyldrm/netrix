"""Disposable topology browser fixture. Never connects to real devices."""

import inventory_fixture  # noqa: F401
from inventory_fixture import app as app
from netrix import models as m
from netrix.core import session_factory
from netrix.discovery.manual_links import confirm_link
from sqlalchemy import select

with session_factory()() as db:
    for device in db.scalars(select(m.Device)):
        device.archived = True
    db.add(m.DeviceType(code="controller", name="Controller"))
    vrf = m.VRF(name="Topology fixture")
    db.add(vrf)
    db.flush()
    devices = []
    for i, (name, kind) in enumerate(
        [
            ("FG-FW-GW-A-01-00-01", "firewall"),
            ("HP-SW-BB-01-A-00-01", "switch"),
            ("Controller", "controller"),
            ("Edge-01", "switch"),
            ("Edge-02", "switch"),
        ]
    ):
        device = m.Device(name=name, kind=kind, management_ip=f"198.51.100.{i + 1}", vrf_id=vrf.id)
        db.add(device)
        db.flush()
        devices.append(device)
    confirm_link(db, devices[1].id, devices[0].id)
    for a, b in [(1, 2), (1, 3), (3, 4)]:
        db.add(
            m.Link(
                device_id=devices[a].id,
                remote_device_id=devices[b].id,
                remote_name=devices[b].name,
                interface_name="1",
                remote_port="2",
                confidence=0.65,
            )
        )
    db.add(
        m.Link(
            device_id=devices[1].id,
            remote_name=bytes.fromhex("187a3b4f1440").decode("latin1"),
            interface_name="C3",
            remote_port="UPLINK-49",
            source="cdp",
        )
    )
    db.commit()
