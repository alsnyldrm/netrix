"""Automatic port selection migration and stale-session protection on disposable MariaDB."""

import subprocess
from datetime import timedelta

from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.worker import sync_interfaces
from sqlalchemy import insert, select, text
from sqlalchemy.exc import OperationalError

assert engine().url.database == "netrix_test"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "20261030_07")
stamp = now()
with session_factory()() as db:
    db.execute(insert(m.VRF.__table__).values(id="ports-vrf", name="Ports test"))
    for name in ("fresh", "edited"):
        db.execute(
            insert(m.Device.__table__).values(
                id=name,
                name=name,
                management_ip="192.0.2.1" if name == "fresh" else "192.0.2.2",
                vrf_id="ports-vrf",
            )
        )
    for name, device, status, managed, deleted, later in (
        ("up", "fresh", "up", 0, 0, False),
        ("down", "fresh", "down", 0, 0, False),
        ("unknown", "fresh", "unknown", 0, 0, False),
        ("excluded", "edited", "up", 0, 0, False),
        ("manual", "edited", "down", 1, 0, False),
        ("deleted", "edited", "up", 0, 1, False),
        ("after", "edited", "up", 0, 0, True),
    ):
        created = (stamp + timedelta(minutes=1) if later else stamp - timedelta(minutes=1)).replace(
            tzinfo=None
        )
        db.execute(
            text("""INSERT INTO interfaces
            (id, created_at, updated_at, device_id, name, mac_address, oper_status, description, is_managed, monitoring_enabled, is_deleted)
            VALUES (:id, :created, :created, :device, :id, '', :status, '', :managed, 1, :deleted)"""),
            dict(id=name, created=created, device=device, status=status, managed=managed, deleted=deleted),
        )
    db.add(
        m.Audit(
            action="select_interfaces",
            entity_type="devices",
            entity_id="edited",
            summary="Legacy selection",
            created_at=stamp,
        )
    )
    db.commit()
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    ports = {p.id: p for p in db.scalars(select(m.Interface))}
    assert ports["up"].is_managed and not ports["up"].auto_add_excluded
    assert not ports["down"].is_managed and not ports["unknown"].is_managed
    assert ports["excluded"].auto_add_excluded and not ports["excluded"].is_managed
    assert ports["deleted"].auto_add_excluded and ports["deleted"].is_deleted
    assert ports["manual"].is_managed and not ports["manual"].auto_add_excluded
    assert ports["after"].is_managed and not ports["after"].auto_add_excluded
# A worker session may have an old ORM object when a user commits an exclusion.
with session_factory()() as worker_db:
    old = worker_db.get(m.Interface, "up")
    assert old.is_managed
    with session_factory()() as user_db:
        row = user_db.get(m.Interface, "up")
        row.auto_add_excluded, row.is_managed = True, False
        user_db.commit()
    device = worker_db.get(m.Device, "fresh")
    observation = {
        "interfaces": [
            {
                "name": "up",
                "if_index": 9,
                "oper_status": "up",
                "mac_address": "",
                "description": "",
                "speed_bps": 1000,
            }
        ]
    }
    for attempt in range(2):
        try:
            sync_interfaces(worker_db, device, observation, None)
            break
        except OperationalError as exc:
            # The worker retries a stale MariaDB locking read in a new transaction.
            if attempt or exc.orig.args[0] != 1020:
                raise
            worker_db.rollback()
    worker_db.commit()
    assert old.auto_add_excluded and not old.is_managed
result = migrate("downgrade", "20261030_07", check=False)
assert result.returncode and b"user preferences" in result.stderr
with session_factory()() as db:
    assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261030_08"
    db.execute(text("UPDATE interfaces SET auto_add_excluded = 0"))
    db.commit()
migrate("downgrade", "20261030_07")
migrate("upgrade", "head")
migrate("check")
print(
    "MariaDB automatic ports PASS: defaults, legacy choices, deleted/manual ports, later discoveries, stale worker exclusion, guarded downgrade and schema"
)
