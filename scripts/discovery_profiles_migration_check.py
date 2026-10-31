"""Verify profile backfill and constraints on disposable MariaDB netrix_test only."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
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
migrate("downgrade", "20261031_15")
with engine().begin() as db:
    for sql in (
        "INSERT INTO institutions (id,name,code,lock_version,created_at,updated_at) VALUES ('i','Fixture','I',0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
        "INSERT INTO sites (id,name,code,institution_id,description,timezone,created_at,updated_at) VALUES ('s','Fixture','S','i','','Europe/Istanbul',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
        "INSERT INTO vrfs (id,name,description,lock_version,created_at,updated_at) VALUES ('v','Fixture','',0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
        "INSERT INTO credentials (id,name,protocol,encrypted_secret,key_version,created_at,updated_at) VALUES ('c1','Fixture one','snmpv3','fixture',1,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6)),('c2','Fixture two','snmpv2c','fixture',1,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
        "INSERT INTO discovery_scopes (id,name,cidr,vrf_id,credential_id,site_id,exclusions,seeds,enabled,interval_seconds,created_at,updated_at) VALUES ('scope','Fixture','192.0.2.0/30','v','c1','s','[]','[]',0,0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
    ):
        db.execute(text(sql))
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    scope = db.get(m.Scope, "scope")
    assert scope.credential_ids == ["c1"]
    assert scope.institution_id == "i"
    assert scope.enabled is False and scope.interval_seconds == 0
    for row in (
        m.ScopeCredential(scope_id="scope", credential_id="missing", position=1),
        m.ScopeCredential(scope_id="missing", credential_id="c2", position=1),
        m.ScopeCredential(scope_id="scope", credential_id="c2", position=0),
    ):
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("Missing profile association constraint")
    db.add(m.ScopeCredential(scope_id="scope", credential_id="c2", position=1))
    db.commit()
    try:
        db.delete(db.get(m.Credential, "c2"))
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        raise AssertionError("In-use secondary credential was deleted")
assert migrate("downgrade", "20261031_15", check=False).returncode != 0
with engine().begin() as db:
    db.execute(text("DELETE FROM discovery_scope_credentials WHERE position=1"))
migrate("downgrade", "20261031_15")
migrate("upgrade", "head")
migrate("check")
with engine().begin() as db:
    db.execute(text("DELETE FROM discovery_scopes WHERE id='scope'"))
    assert db.scalar(text("SELECT COUNT(*) FROM discovery_scope_credentials")) == 0
print(
    "PASS: MariaDB legacy profile/institution backfill, association FKs/ordering, downgrade guard and cascade"
)
