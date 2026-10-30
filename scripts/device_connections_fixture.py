"""Disposable device connections fixture; no workers or real network traffic."""

from scripts.inventory_fixture import app as app  # noqa: I001 - initialize isolated storage first
from netrix import models as m
from netrix.core import now, session_factory
from sqlalchemy import select

with session_factory()() as db:
    devices = list(db.scalars(select(m.Device).order_by(m.Device.name)))
    core, edge = devices[:2]
    db.add(m.DeviceType(code="fixture-backbone", name="Backbone"))
    db.flush()
    core.name, core.kind = "HP-SW-BB-01-A-00-01", "fixture-backbone"
    edge.name = "HP-SW-CO-01-B-05-02"
    for local, remote, port, peer_port, source in [
        (core, edge, "F2", "49", "lldp"),
        (edge, core, "49", "F2", "cdp"),
        (core, edge, "F3", "50", "lldp"),
    ]:
        db.add(
            m.Link(
                device_id=local.id,
                remote_device_id=remote.id,
                remote_name=remote.name,
                interface_name=port,
                remote_port=peer_port,
                source=source,
                confidence=0.65,
                last_seen_at=now(),
            )
        )
    db.add(
        m.Link(
            device_id=edge.id,
            remote_name="Unresolved-neighbor",
            interface_name="48",
            remote_port="",
            source="lldp",
            confidence=0.5,
            last_seen_at=now(),
        )
    )
    db.commit()
