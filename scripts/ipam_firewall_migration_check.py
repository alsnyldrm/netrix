"""Firewall source constraint round trip on disposable MariaDB only."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test"


def migrate(target):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", target], check=True)


migrate("20261101_22")
with session_factory()() as db:
    db.add(
        m.Integration(
            id="original",
            name="Original",
            kind="corner_switch",
            host="192.0.2.1",
            port=161,
            encrypted_secret="fixture",
        )
    )
    db.commit()
migrate("head")
with session_factory()() as db:
    assert db.get(m.Integration, "original").name == "Original"
    db.add(
        m.Integration(
            id="firewall",
            name="Firewall",
            kind="firewall",
            host="192.0.2.2",
            port=161,
            encrypted_secret="fixture",
        )
    )
    db.commit()
    try:
        db.execute(text("UPDATE integrations SET kind='unsupported' WHERE id='firewall'"))
        db.commit()
        raise AssertionError("Constraint accepted unsupported source")
    except (IntegrityError, OperationalError) as error:
        assert error.orig.args[0] == 4025, error
        db.rollback()
    db.delete(db.get(m.Integration, "firewall"))
    db.commit()
subprocess.run(["alembic", "-c", "backend/alembic.ini", "downgrade", "20261101_22"], check=True)
migrate("head")
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
print("PASS: firewall constraint, existing source preservation, downgrade/upgrade and schema parity")
