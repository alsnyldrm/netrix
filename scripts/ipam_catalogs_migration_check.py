"""Validate catalogs on a disposable MariaDB database only."""

import subprocess

from netrix import models as m
from netrix.core import engine, now, session_factory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

assert engine().url.database == "netrix_test"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "head")
migrate("check")
migrate("downgrade", "20261031_13")
with session_factory()() as db:
    site = m.Site(name="Existing campus", code="existing")
    vrf = m.VRF(name="Catalog migration")
    db.add_all([site, vrf])
    db.flush()
    prefix = m.Prefix(cidr="192.0.2.0/24", vrf_id=vrf.id, site_id=site.id)
    db.add(prefix)
    db.flush()
    address = m.IPAddress(
        address="192.0.2.10",
        prefix_id=prefix.id,
        vrf_id=vrf.id,
        operating_system="Legacy OS",
        cabinet="K-legacy",
        location="Legacy location",
    )
    db.add(address)
    db.commit()
    site_id, address_id = site.id, address.id
migrate("upgrade", "head")
with session_factory()() as db:
    address = db.get(m.IPAddress, address_id)
    assert (address.operating_system, address.cabinet, address.location) == (
        "Legacy OS",
        "K-legacy",
        "Legacy location",
    )
    stamp = now().replace(microsecond=123456)
    cabinet = m.Cabinet(name="K-01", site_id=site_id, created_at=stamp, updated_at=stamp)
    db.add(cabinet)
    db.commit()
    db.refresh(cabinet)
    assert cabinet.created_at == stamp and cabinet.updated_at == stamp
    for item in (m.Cabinet(name="K-01"), m.Cabinet(name="K-02", site_id="missing")):
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("Catalog UNIQUE/FK constraint missing")
    db.add(m.OperatingSystem(name="Windows Server"))
    db.commit()
    db.add(m.OperatingSystem(name="Windows Server"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        raise AssertionError("OS UNIQUE constraint missing")
assert migrate("downgrade", "20261031_13", check=False).returncode != 0
with engine().begin() as db:
    db.execute(text("DELETE FROM cabinets"))
    db.execute(text("DELETE FROM operating_systems"))
migrate("downgrade", "20261031_13")
migrate("upgrade", "head")
migrate("check")
print(
    "MariaDB catalog PASS: existing metadata, UTC microseconds, UNIQUE/FK, guarded downgrade, roundtrip and schema check"
)
