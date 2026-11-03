"""Disposable netrix_test only: 1..10 constraint, retained controls and guarded rollback."""

import subprocess
from uuid import uuid4

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models as m
from netrix.core import engine, now, session_factory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

assert engine().url.database == "netrix_test", "Disposable DB required"


def migrate(direction, revision, blocked=False):
    result = subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", direction, revision], capture_output=True, text=True
    )
    if blocked:
        assert result.returncode and "refuse a lossy downgrade" in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr


migrate("upgrade", "20261103_44")
id = str(uuid4())
with engine().begin() as conn:
    conn.execute(
        text(
            "INSERT INTO firmware_plans (id,created_at,updated_at,name,status,mode,steps,concurrency,available_at,cancel_requested) VALUES (:id,:now,:now,'Existing plan','paused','stage','[]',4,:now,0)"
        ),
        {"id": id, "now": now().replace(tzinfo=None)},
    )
migrate("upgrade", "head")
with session_factory()() as db:
    plan = db.get(m.FirmwarePlan, id)
    assert plan.concurrency == 4 and not plan.force_stop_requested and plan.deleted_at is None
    plan.concurrency = 10
    db.commit()
    for invalid in (0, 11):
        plan.concurrency = invalid
        try:
            db.commit()
            raise AssertionError("MariaDB accepted an out-of-range concurrent device count")
        except DBAPIError as exc:
            assert exc.orig.args[0] == 4025
            db.rollback()
    plan.concurrency = 10
    plan.force_stop_requested, plan.deleted_at = True, now()
    db.commit()
with engine().connect() as connection:
    differences = compare_metadata(
        MigrationContext.configure(
            connection,
            opts={
                "include_object": lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name == "firmware_plans"
                )
            },
        ),
        m.Base.metadata,
    )
    assert not differences, differences
migrate("downgrade", "20261103_44", blocked=True)
with session_factory()() as db:
    plan = db.get(m.FirmwarePlan, id)
    assert plan.force_stop_requested and plan.deleted_at and plan.concurrency == 10
    plan.force_stop_requested, plan.deleted_at, plan.concurrency = False, None, 4
    db.commit()
migrate("downgrade", "20261103_44")
migrate("upgrade", "head")
with session_factory()() as db:
    assert db.get(m.FirmwarePlan, id).name == "Existing plan"
    assert db.get(m.FirmwarePlan, id).concurrency == 4
print(
    "PASS: MariaDB 1..10 constraint, old plan retention, controls defaults, schema parity and protected rollback/re-upgrade"
)
