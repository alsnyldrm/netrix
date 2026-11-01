"""Disposable MariaDB validation: schema parity, uniqueness and FK lifecycle."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.inventory.device_types import seed_defaults
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

assert engine().url.database == "netrix_test"


def migrate(action, revision):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", action, revision], check=True)


migrate("upgrade", "20261101_26")
migrate("upgrade", "head")
with session_factory()() as db:
    seed_defaults(db)
    cabinet = m.Cabinet(name="01", units=42)
    vrf = m.VRF(name="Patch fixture")
    db.add_all([cabinet, vrf])
    db.flush()
    device = m.Device(name="Switch", management_ip="192.0.2.1", vrf_id=vrf.id)
    db.add(device)
    db.flush()
    interface = m.Interface(device_id=device.id, name="A1")
    panel = m.PatchPanel(
        cabinet_id=cabinet.id, name="CAT-01", kind="cat", start_unit=42, units=1, port_count=24
    )
    db.add_all([interface, panel])
    db.flush()
    port = m.PatchPort(
        panel_id=panel.id,
        position=1,
        number="1",
        device_id=device.id,
        interface_id=interface.id,
        device_name="Switch",
        port_name="A1",
        cable_model="Cat6",
    )
    db.add(port)
    db.commit()
    panel_id, port_id, interface_id, device_id, cabinet_id = (
        panel.id,
        port.id,
        interface.id,
        device.id,
        cabinet.id,
    )
    db.add(m.PatchPort(panel_id=panel_id, position=2, number="1"))
    try:
        db.commit()
        raise AssertionError("Duplicate port number accepted")
    except IntegrityError:
        db.rollback()
    db.delete(db.get(m.Interface, interface_id))
    db.commit()
    db.expire_all()
    assert db.get(m.PatchPort, port_id).interface_id is None
    db.delete(db.get(m.Device, device_id))
    db.commit()
    db.expire_all()
    assert db.get(m.PatchPort, port_id).device_id is None
    assert db.get(m.PatchPort, port_id).device_name == "Switch"
    blocked = subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", "downgrade", "20261101_26"],
        capture_output=True,
        text=True,
    )
    assert blocked.returncode != 0 and "Patch panels exist" in blocked.stderr
    db.delete(db.get(m.PatchPanel, panel_id))
    db.commit()
    assert db.scalar(select(m.PatchPort.id).where(m.PatchPort.panel_id == panel_id)) is None
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
migrate("downgrade", "20261101_26")
migrate("upgrade", "head")
with engine().connect() as db:
    assert db.scalar(text("SELECT count(*) FROM cabinets WHERE id=:id"), {"id": cabinet_id}) == 1
print(
    "PASS: MariaDB upgrade, uniqueness, interface/device SET NULL, panel CASCADE, schema parity and downgrade/upgrade"
)
