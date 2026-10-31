"""MariaDB hierarchy/authorization migration checks; disposable netrix_test only."""

import subprocess

from netrix import models as m
from netrix.core import engine, now, session_factory
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "head")
migrate("check")
migrate("downgrade", "20261031_14")
with engine().begin() as db:
    db.execute(
        text(
            "INSERT INTO sites (id,name,code,description,timezone,created_at,updated_at) VALUES ('legacy-site','Existing','OLD','','Europe/Istanbul',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
        )
    )
    db.execute(
        text(
            "INSERT INTO vrfs (id,name,description,lock_version,created_at,updated_at) VALUES ('legacy-vrf','Legacy','',0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
        )
    )
    db.execute(
        text(
            "INSERT INTO prefixes (id,cidr,vrf_id,description,created_at,updated_at) VALUES ('legacy-prefix','192.0.2.0/24','legacy-vrf','Existing',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
        )
    )
    db.execute(
        text(
            "INSERT INTO ip_addresses (id,address,vrf_id,prefix_id,hostname,status,cabinet,location,operating_system,created_at,updated_at) VALUES ('legacy-ip','192.0.2.1','legacy-vrf','legacy-prefix','old-host','active','K-01','Kat 1','Linux',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
        )
    )
    db.execute(
        text(
            "INSERT INTO cabinets (id,name,description,site_id,created_at,updated_at) VALUES ('legacy-cabinet','K-01','','legacy-site',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))"
        )
    )
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    ip = db.get(m.IPAddress, "legacy-ip")
    assert (ip.hostname, ip.operating_system, ip.cabinet, ip.location) == (
        "old-host",
        "Linux",
        "K-01",
        "Kat 1",
    )
    assert db.get(m.Site, "legacy-site").institution_id is None
    assert db.get(m.Prefix, "legacy-prefix").scan_authorized is False
    assert db.get(m.Cabinet, "legacy-cabinet").units == 42
    stamp = now().replace(microsecond=123456)
    institution = m.Institution(name="Fixture", code="01", created_at=stamp, updated_at=stamp)
    db.add(institution)
    db.commit()
    db.refresh(institution)
    assert institution.created_at == stamp
    for row in (
        m.Institution(name="Duplicate", code="01"),
        m.Site(name="Invalid", code="BAD", institution_id="missing"),
        m.Cabinet(name="Invalid U", units=61),
    ):
        db.add(row)
        try:
            db.commit()
        except (IntegrityError, OperationalError):
            db.rollback()
        else:
            raise AssertionError("Hierarchy constraint missing")
assert migrate("downgrade", "20261031_14", check=False).returncode != 0
with engine().begin() as db:
    db.execute(text("DELETE FROM institutions"))
migrate("downgrade", "20261031_14")
migrate("upgrade", "head")
migrate("check")
assert {"institutions", "rack_placements", "model_images"}.issubset(inspect(engine()).get_table_names())
print(
    "MariaDB hierarchy PASS: legacy metadata preserved, explicit authorization defaults, UTC precision, FK/CHECK/UNIQUE, guarded downgrade and roundtrip"
)
