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
        (core, edge, "I4", "A1", "lldp"),
        (edge, core, "A1", "I4", "cdp"),
        (core, edge, "D2", "B1", "lldp"),
        (edge, core, "B1", "D2", "cdp"),
    ]:
        db.add(
            m.Link(
                device_id=local.id,
                remote_device_id=remote.id,
                remote_name=remote.name,
                interface_name=port,
                remote_port=peer_port,
                source=source,
                evidence={
                    "local_aggregate": {"name": "Trk1" if local == edge else "Trk7", "type": "LACP"},
                    "spanning_tree": {"port": "Trk1" if local == edge else None, "is_root": local == core},
                },
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
