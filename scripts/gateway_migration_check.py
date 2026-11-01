"""Validate the gateway migration against disposable netrix_test MariaDB only."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from sqlalchemy import text

assert engine().url.database == "netrix_test"


def migrate(*args):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], check=True)


migrate("upgrade", "head")
with session_factory()() as db:
    vrf = m.VRF(name="Gateway fixture")
    db.add(vrf)
    db.flush()
    device = m.Device(name="Existing fixture", management_ip="192.0.2.1", vrf_id=vrf.id)
    db.add(device)
    db.commit()
    id = device.id
    assert device.is_gateway is False

# Exercise an existing device through rollback and upgrade without changing its identity.
migrate("downgrade", "20261101_24")
migrate("upgrade", "head")
with session_factory()() as db:
    device = db.get(m.Device, id)
    assert device.name == "Existing fixture" and device.is_gateway is False
    assert db.scalar(text("SELECT COUNT(*) FROM devices WHERE is_gateway IS NULL")) == 0
    device.is_gateway = True
    db.commit()
with session_factory()() as db:
    assert db.get(m.Device, id).is_gateway is True
    db.get(m.Device, id).is_gateway = False
    db.commit()
with session_factory()() as db:
    assert db.get(m.Device, id).is_gateway is False
print("MariaDB gateway migration PASS: existing rows default off, upgrade/downgrade, persistent toggling")
