"""Verify software version storage on disposable netrix_test MariaDB only."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from sqlalchemy import inspect

assert engine().url.database == "netrix_test"


def migrate(*args):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], check=True)


migrate("upgrade", "head")
with session_factory()() as db:
    vrf = m.VRF(name="Version fixture")
    db.add(vrf)
    db.flush()
    device = m.Device(name="Existing", management_ip="192.0.2.1", vrf_id=vrf.id)
    db.add(device)
    db.commit()
    id = device.id
    assert device.software_version == ""
migrate("downgrade", "20261101_28")
migrate("upgrade", "head")
with session_factory()() as db:
    device = db.get(m.Device, id)
    assert device.name == "Existing" and device.software_version == ""
    device.software_version = "KB.16.11.0032"
    db.commit()
with session_factory()() as db:
    assert db.get(m.Device, id).software_version == "KB.16.11.0032"
column = next(c for c in inspect(engine()).get_columns("devices") if c["name"] == "software_version")
assert not column["nullable"]
print("MariaDB software version PASS: fresh install, upgrade/downgrade, existing defaults and persistence")
