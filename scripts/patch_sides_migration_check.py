"""Disposable MariaDB: preserve fronts, migrate rear links, race two writers, safe rollback."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import sqlalchemy as sa
from fastapi import HTTPException
from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.ipam import patch_panels
from netrix.ipam.schemas import PatchPortInput
from sqlalchemy.exc import IntegrityError

assert engine().url.database == "netrix_test"


def migrate(action, revision, *, blocked=False):
    result = subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", action, revision], capture_output=blocked, text=True
    )
    if blocked:
        assert result.returncode and "External patch connections exist" in result.stderr
    else:
        assert result.returncode == 0


migrate("upgrade", "20261101_30")
with session_factory()() as db:
    cabinet = m.Cabinet(name="01", units=42)
    db.add(cabinet)
    db.flush()
    panel = m.PatchPanel(
        cabinet_id=cabinet.id, name="FIBER-01", kind="fiber", start_unit=41, units=1, port_count=3
    )
    db.add(panel)
    db.flush()
    previous = dict(
        id=str(uuid4()),
        created_at=now().replace(tzinfo=None),
        updated_at=now().replace(tzinfo=None),
        panel_id=panel.id,
        position=1,
        number="P-01",
        device_id=None,
        interface_id=None,
        device_name="Stored device",
        port_name="D38",
        cable_model="OM4",
        fiber_mode="multimode",
    )
    table = sa.Table("patch_ports", sa.MetaData(), autoload_with=db.connection())
    db.execute(table.insert().values(**previous))
    db.commit()
    cabinet_id, panel_id = cabinet.id, panel.id
migrate("upgrade", "head")
with engine().connect() as db:
    row = dict(
        db.execute(sa.text("SELECT * FROM patch_ports WHERE id=:id"), {"id": previous["id"]}).mappings().one()
    )
    assert row.pop("peer_port_id") is None
    assert row.pop("external_data") in ("{}", {})
    assert row == previous
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
with session_factory()() as db:
    sources = [m.PatchPort(panel_id=panel_id, position=n, number=str(n)) for n in (2, 3)]
    remote = m.Cabinet(name="02", units=42)
    db.add_all([*sources, remote])
    db.flush()
    target_panel = m.PatchPanel(
        cabinet_id=remote.id, name="FIBER-01", kind="fiber", start_unit=41, units=1, port_count=1
    )
    db.add(target_panel)
    db.flush()
    target = m.PatchPort(panel_id=target_panel.id, position=1, number="1")
    db.add(target)
    db.commit()
    source_ids = [r.id for r in sources]
    target_id, remote_id, remote_panel_id = target.id, remote.id, target_panel.id


def writer(index):
    with session_factory()() as db:
        payload = PatchPortInput(
            number=str(index + 2),
            external={"port_id": target_id, "device_name": "Target switch", "port_name": "49"},
        )
        try:
            patch_panels.save_port(db, cabinet_id, panel_id, source_ids[index], payload, None)
            return 200
        except HTTPException as exc:
            db.rollback()
            return exc.status_code


with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(writer, (0, 1)))
assert sorted(results) == [200, 409], results
with session_factory()() as db:
    all_ports = {p.id: p for p in db.scalars(sa.select(m.PatchPort))}
    linked = [p for p in all_ports.values() if p.peer_port_id]
    assert len(linked) == 2
    assert all(all_ports[p.peer_port_id].peer_port_id == p.id for p in linked)
    winner = source_ids[results.index(200)]
    loser = source_ids[results.index(409)]
    db.get(m.PatchPort, loser).peer_port_id = target_id
    try:
        db.commit()
        raise AssertionError("Duplicate rear target accepted")
    except IntegrityError:
        db.rollback()
    db.get(m.PatchPort, loser).peer_port_id = str(uuid4())
    try:
        db.commit()
        raise AssertionError("Dangling rear FK accepted")
    except IntegrityError:
        db.rollback()
migrate("downgrade", "20261101_30", blocked=True)
with session_factory()() as db:
    patch_panels.save_port(
        db,
        cabinet_id,
        panel_id,
        winner,
        PatchPortInput(number=str(results.index(200) + 2), external=None),
        None,
    )
    db.execute(sa.delete(m.PatchPort).where(m.PatchPort.id.in_([*source_ids, target_id])))
    db.execute(sa.delete(m.PatchPanel).where(m.PatchPanel.id == remote_panel_id))
    db.execute(sa.delete(m.Cabinet).where(m.Cabinet.id == remote_id))
    db.commit()
migrate("downgrade", "20261101_30")
with engine().connect() as db:
    row = dict(
        db.execute(sa.text("SELECT * FROM patch_ports WHERE id=:id"), {"id": previous["id"]}).mappings().one()
    )
    assert row == previous
migrate("upgrade", "head")
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
print(
    "PASS: MariaDB preserves existing fronts, rear UNIQUE/FK constraints, concurrent competing writers, reciprocal links, schema parity and safe downgrade/upgrade"
)
