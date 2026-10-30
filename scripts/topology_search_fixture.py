"""Disposable connection search fixture, including reverse observations and trunks."""

import topology_fixture  # noqa: F401
from netrix import models as m
from netrix.core import session_factory
from sqlalchemy import select
from topology_fixture import app as app

with session_factory()() as db:
    controller = db.scalar(select(m.Device).where(m.Device.name == "Controller"))
    core = db.scalar(select(m.Device).where(m.Device.name == "HP-SW-BB-01-A-00-01"))
    edge = db.scalar(select(m.Device).where(m.Device.name == "Edge-01"))
    link = db.scalar(select(m.Link).where(m.Link.remote_device_id == controller.id))
    link.interface_name, link.remote_port = "B1", "GE0/0/4"
    link.evidence = {"local_aggregate": {"name": "Trk7", "type": "LACP"}}
    db.add(
        m.Link(
            device_id=edge.id,
            remote_device_id=core.id,
            remote_name=core.name,
            interface_name="Gi1/0/9",
            remote_port="D7",
            source="cdp",
            confidence=0.5,
        )
    )
    db.commit()
