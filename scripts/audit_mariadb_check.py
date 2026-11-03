"""Audit JSON migration and transaction checks in a disposable MariaDB only."""

import subprocess

from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.identity import audit as audit_capture  # noqa: F401 - register the API's session hooks
from netrix.identity.audit_read import list_entries
from sqlalchemy import inspect, select, text

assert engine().url.database == "netrix_test", "Disposable database required"


def migrate(revision):
    subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", revision], check=True)


migrate("20261104_45")
with engine().begin() as db:
    db.execute(
        text("""INSERT INTO users
        (id, created_at, updated_at, email, display_name, password_hash, role, ssh_access, is_active)
        VALUES ('audit-fixture', :now, :now, 'fixture@example.test', 'MariaDB fixture', 'fixture-only', 'admin', 0, 1)
    """),
        {"now": now().replace(tzinfo=None)},
    )
    db.execute(
        text("""INSERT INTO audit_events
        (id, created_at, updated_at, actor_id, action, entity_type, entity_id, summary)
        VALUES ('legacy-fixture', :now, :now, 'audit-fixture', 'update', 'institutions', null, 'Geçmiş işlem')
    """),
        {"now": now().replace(tzinfo=None)},
    )
migrate("head")
assert "details" in {col["name"] for col in inspect(engine()).get_columns("audit_events")}
with session_factory()() as db:
    assert db.get(m.Audit, "legacy-fixture").details is None
    user = db.get(m.User, "audit-fixture")
    db.info["audit_actor"] = user
    row = m.Institution(name="Önceki değer", code="AUD")
    db.add(row)
    db.commit()
    row.name = "Yeni değer"
    db.commit()
    result = list_entries(db, 25, 0, "MariaDB fixture")
    change = next(r for r in result["items"] if r["entity_id"] == row.id and r["action"] == "update")
    assert change["details"]["changes"]["name"] == {"previous": "Önceki değer", "current": "Yeni değer"}
    assert change["created_at"].endswith("+00:00")
    assert list_entries(db, 25, 0, "Yeni değer")["total"] == 1
    assert list_entries(db, 25, 0, "%")["total"] == 0
    row.name = "Rolled back"
    db.flush()
    db.rollback()
    assert list_entries(db, 25, 0, "Rolled back")["total"] == 0
    count = len(list(db.scalars(select(m.Audit))))
subprocess.run(["alembic", "-c", "backend/alembic.ini", "downgrade", "20261104_45"], check=True)
assert "details" not in {col["name"] for col in inspect(engine()).get_columns("audit_events")}
migrate("head")
with session_factory()() as db:
    assert len(list(db.scalars(select(m.Audit)))) == count
print(
    "PASS: MariaDB upgrade/downgrade/upgrade, legacy preservation, JSON field changes, actor search, UTC and rollback"
)
