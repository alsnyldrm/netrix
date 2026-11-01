"""Disposable MariaDB: legacy cabling preservation, independent mode and safe rollback."""

import subprocess
from uuid import uuid4

import sqlalchemy as sa
from netrix import models as m
from netrix.core import engine, now, session_factory
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test"


def migrate(action, revision, *, blocked=False):
    result = subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", action, revision], capture_output=blocked, text=True
    )
    if blocked:
        assert result.returncode and "Independent fiber model and mode exist" in result.stderr
    else:
        assert result.returncode == 0


migrate("upgrade", "20261101_29")
legacy = ["Multimode MM", "Singlemode SM", "OM3", "OM4", "", "Cat6"]
with session_factory()() as db:
    cabinet = m.Cabinet(name="01", units=42)
    db.add(cabinet)
    db.flush()
    fiber = m.PatchPanel(
        cabinet_id=cabinet.id, name="Fiber", kind="fiber", start_unit=1, units=1, port_count=5
    )
    cat = m.PatchPanel(cabinet_id=cabinet.id, name="CAT", kind="cat", start_unit=2, units=1, port_count=1)
    db.add_all([fiber, cat])
    db.flush()
    old_ports = sa.Table("patch_ports", sa.MetaData(), autoload_with=db.connection())
    ids, snapshots = [], []
    for n, cable in enumerate(legacy):
        row = dict(
            id=str(uuid4()),
            created_at=now().replace(tzinfo=None),
            updated_at=now().replace(tzinfo=None),
            panel_id=fiber.id if n < 5 else cat.id,
            position=n + 1 if n < 5 else 1,
            number=str(n + 1),
            device_id=None,
            interface_id=None,
            device_name="Stored device",
            port_name="A1",
            cable_model=cable,
        )
        db.execute(old_ports.insert().values(**row))
        ids.append(row["id"])
        snapshots.append(row)
    db.commit()

migrate("upgrade", "head")
with engine().connect() as db:
    rows = {r["id"]: dict(r) for r in db.execute(sa.text("SELECT * FROM patch_ports")).mappings()}
    for previous, cable in zip(snapshots, legacy):
        expected = {
            **previous,
            "fiber_mode": {"Multimode MM": "multimode", "Singlemode SM": "singlemode"}.get(cable, ""),
            "cable_model": "" if cable in legacy[:2] else cable,
        }
        assert rows[previous["id"]] == expected
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
with engine().begin() as db:
    db.execute(
        sa.text("UPDATE patch_ports SET cable_model='OM4', fiber_mode='multimode' WHERE id=:id"),
        {"id": ids[3]},
    )
try:
    with engine().begin() as db:
        db.execute(sa.text("UPDATE patch_ports SET fiber_mode='invalid' WHERE id=:id"), {"id": ids[3]})
    raise AssertionError("Invalid fiber mode accepted by MariaDB")
except (IntegrityError, OperationalError) as exc:
    assert exc.orig.args[0] == 4025
migrate("downgrade", "20261101_29", blocked=True)
with engine().begin() as db:
    db.execute(sa.text("UPDATE patch_ports SET fiber_mode='' WHERE id=:id"), {"id": ids[3]})
migrate("downgrade", "20261101_29")
with engine().connect() as db:
    assert "fiber_mode" not in {c["name"] for c in sa.inspect(db).get_columns("patch_ports")}
    rows = {r["id"]: dict(r) for r in db.execute(sa.text("SELECT * FROM patch_ports")).mappings()}
    assert all(rows[r["id"]] == r for r in snapshots)
migrate("upgrade", "head")
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
print(
    "PASS: MariaDB legacy mode transfer, all port metadata preserved, model/mode CHECK, schema parity and lossless downgrade/upgrade"
)
