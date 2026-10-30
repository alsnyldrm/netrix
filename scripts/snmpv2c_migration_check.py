"""Data-preserving migration and real CHECK enforcement on disposable MariaDB only."""

import subprocess
from uuid import uuid4

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.identity.security import encrypt, secret_data
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test", "Dedicated disposable database required"


def migrate(*args, check=True):
    return subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], check=check, capture_output=True)


migrate("downgrade", "20261030_05")
with session_factory()() as db:
    original = m.Credential(
        name="v3-" + uuid4().hex, protocol="snmpv3", encrypted_secret=encrypt('{"username":"fixture"}')
    )
    db.add(original)
    db.commit()
    original_id, ciphertext = original.id, original.encrypted_secret
    db.add(m.Credential(name="pre-v2", protocol="snmpv2c", encrypted_secret="fixture"))
    try:
        db.commit()
    except (IntegrityError, OperationalError):
        db.rollback()
    else:
        raise AssertionError("Old constraint must reject SNMPv2c")
migrate("upgrade", "head")
with session_factory()() as db:
    original = db.get(m.Credential, original_id)
    assert original.encrypted_secret == ciphertext and original.protocol == "snmpv3"
    profile = m.Credential(
        name="v2-" + uuid4().hex,
        protocol="snmpv2c",
        encrypted_secret=encrypt('{"community":"fixture-community"}'),
    )
    db.add(profile)
    db.commit()
    profile_id = profile.id
    assert secret_data(profile)["community"] == "fixture-community"
    db.add(m.Credential(name="invalid", protocol="snmpv1", encrypted_secret="fixture"))
    try:
        db.commit()
    except (IntegrityError, OperationalError):
        db.rollback()
    else:
        raise AssertionError("Constraint must reject unsupported protocol")
result = migrate("downgrade", "20261030_05", check=False)
assert result.returncode != 0 and b"Remove SNMPv2c profiles" in result.stderr
with session_factory()() as db:
    assert db.get(m.Credential, profile_id).protocol == "snmpv2c"
    assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261030_06"
    db.delete(db.get(m.Credential, profile_id))
    db.commit()
migrate("downgrade", "20261030_05")
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    assert db.get(m.Credential, original_id).encrypted_secret == ciphertext
    db.delete(db.get(m.Credential, original_id))
    db.commit()
print("MariaDB SNMPv2c PASS: constraint, upgrade/downgrade/upgrade, existing data, guarded downgrade, schema")
