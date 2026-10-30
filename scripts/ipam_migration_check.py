"""Verify additive IPAM migration and MariaDB constraints in netrix_test only."""

import subprocess

from netrix import models as m
from netrix.core import engine, now, session_factory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "head")
migrate("downgrade", "20261030_12")
with engine().begin() as db:
    db.execute(
        text(
            "INSERT INTO vrfs (id,name,description,lock_version,created_at,updated_at) VALUES ('vrf-ipam','IPAM test','',0,UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
    db.execute(
        text(
            "INSERT INTO prefixes (id,cidr,vrf_id,description,created_at,updated_at) VALUES ('prefix-ipam','192.0.2.0/24','vrf-ipam','old',UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
    db.execute(
        text(
            "INSERT INTO ip_addresses (id,address,vrf_id,prefix_id,hostname,status,created_at,updated_at) VALUES ('ip-ipam','192.0.2.10','vrf-ipam','prefix-ipam','old-host','reserved',UTC_TIMESTAMP(),UTC_TIMESTAMP())"
        )
    )
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    p = db.get(m.Prefix, "prefix-ipam")
    ip = db.get(m.IPAddress, "ip-ipam")
    assert p.warning_threshold == 80 and not p.ping_enabled and p.ping_interval == 300
    assert ip.hostname == "old-host" and ip.operating_system == ""
    assert ip.created_at.tzinfo is not None
    stamp = now().replace(microsecond=123456)
    config = m.Integration(
        name="Precision",
        kind="vcenter",
        host="fixture.example.test",
        port=443,
        encrypted_secret="fixture",
        created_at=stamp,
        updated_at=stamp,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    assert config.updated_at == stamp and config.created_at == stamp
    db.delete(config)
    db.commit()
    for field, value in [("warning_threshold", 101), ("ping_interval", 1), ("vlan_device_id", "missing")]:
        try:
            setattr(p, field, value)
            db.commit()
        except (IntegrityError, OperationalError):
            db.rollback()
        else:
            raise AssertionError("MariaDB constraint missing: " + field)
    db.add(
        m.IPObservation(
            address_id=ip.id, source="vcenter", source_key="test", data={"power_state": "poweredOn"}
        )
    )
    db.commit()
    db.add(m.IPObservation(address_id=ip.id, source="vcenter", source_key="test", data={}))
    try:
        db.commit()
    except (IntegrityError, OperationalError):
        db.rollback()
    else:
        raise AssertionError("Duplicate source observation allowed")
assert migrate("downgrade", "20261030_12", check=False).returncode != 0
with session_factory()() as db:
    db.execute(text("DELETE FROM ip_observations"))
    db.commit()
migrate("downgrade", "20261030_12")
migrate("upgrade", "head")
migrate("check")
print("MariaDB IPAM PASS: existing data, UTC, FK/CHECK/UNIQUE, guarded downgrade, roundtrip and schema check")
