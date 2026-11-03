"""Disposable MariaDB only: transcript migration, bounded text and concurrent sequence allocation."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from firmware_groups_mariadb_check import engine, ids, migrate, session_factory
from netrix import models as m
from netrix.firmware.history import add_event, transcript
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

migrate("upgrade", "head")
with engine().connect() as connection:
    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda obj, name, kind, reflected, compared: (
                kind != "table" or name in ("firmware_events", "firmware_group_members", "firmware_plans")
            )
        },
    )
    assert not compare_metadata(context, m.Base.metadata)
with session_factory()() as db:
    image = m.FirmwareImage(
        name="Fixture image",
        family="cx6100",
        version="PL.10.18.1010",
        models=["JL675A"],
        original_name="fixture.swi",
        expected_sha256="a" * 64,
    )
    plan = m.FirmwarePlan(name="Fixture history", mode="check", steps=[])
    db.add_all([image, plan])
    db.flush()
    target = m.FirmwareTarget(plan_id=plan.id, device_id=ids[0], image_id=image.id, stage=0)
    db.add(target)
    db.commit()
    target_id, plan_id = target.id, plan.id

barrier = Barrier(2)


def write(index):
    with session_factory()() as db:
        target = db.get(m.FirmwareTarget, target_id)  # establish a repeatable-read snapshot before contention
        barrier.wait(timeout=10)
        result = add_event(
            db,
            target,
            kind="command",
            title="Fixture command",
            command="show images",
            response="x" * 13000 + "password fixture-secret",
            status="succeeded",
            finished=True,
        )
        db.commit()
        return result.id


with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(write, (0, 1))) == [1, 2]
with session_factory()() as db:
    target = db.get(m.FirmwareTarget, target_id)
    add_event(
        db,
        target,
        kind="command",
        title="Bounded Unicode",
        response="ğ" * 14000,
        status="succeeded",
        finished=True,
    )
    db.commit()
    response = transcript(db, target_id)
    assert response["total"] == 3 and response["items"][2]["truncated"]
    assert len(response["items"][2]["response"]) == 12000
    assert "fixture-secret" not in str(response)
    try:
        db.add(
            m.FirmwareEvent(id=1, target_id=target_id, kind="command", phase="preflight", title="Duplicate")
        )
        db.commit()
        raise AssertionError("Duplicate transcript sequence was accepted")
    except IntegrityError:
        db.rollback()
migrate("downgrade", "20261103_41")
with session_factory()() as db:
    assert db.execute(text("SELECT id FROM firmware_targets WHERE id=:id"), {"id": target_id}).first()
    assert db.execute(text("SELECT id FROM firmware_plans WHERE id=:id"), {"id": plan_id}).first()
migrate("upgrade", "head")
with session_factory()() as db:
    assert db.scalar(select(func.count()).select_from(m.FirmwareEvent)) == 0
print(
    "PASS: MariaDB transcript schema parity, concurrent ordered writes, redaction, bounded Unicode, UNIQUE and migration roundtrip preserving plans/targets"
)
