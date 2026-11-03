"""Disposable MariaDB only: constraints, concurrent scheduling, rollback and migration parity."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.ipam import scan_schedules as service
from netrix.ipam.schemas import ScanGroupInput
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test"


def migrate(*args, blocked=False):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True, text=True)
    if blocked:
        assert result.returncode and "downgrade" in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr


def parity():
    # MariaDB reflects existing journal DESC indexes as ASC. Restrict this
    # feature's parity assertion to its three new tables rather than rewriting them.
    with engine().connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "include_object": lambda obj, name, kind, reflected, compared: (
                    kind != "table" or name in {"ipam_scan_groups", "ipam_scan_members", "ipam_scan_runs"}
                )
            },
        )
        assert not compare_metadata(context, m.Base.metadata)


migrate("upgrade", "20261103_34")
with session_factory()() as db:
    vrf = m.VRF(name="Fixture")
    db.add(vrf)
    db.flush()
    vlans = [
        m.VLAN(name=f"Fixture {i}", vid=20 + i, cidr=f"192.0.{i + 2}.0/30", vrf_id=vrf.id) for i in range(4)
    ]
    db.add_all(vlans)
    db.commit()
    vlan_ids = [v.id for v in vlans]
migrate("upgrade", "head")
parity()
at = now() + timedelta(hours=1)
payload = dict(name="Sunucular", frequency="daily", repeat_every=1, start_at=at, vlan_ids=vlan_ids[:2])
with session_factory()() as db:
    group = service.save(db, ScanGroupInput(**payload), None)
    id = group["id"]
    other = m.IPAMScanGroup(name="Empty fixture", frequency="daily", repeat_every=1, start_at=at)
    db.add(other)
    db.commit()
    db.add(m.IPAMScanMember(group_id=other.id, vlan_id=vlan_ids[0]))
    try:
        db.commit()
        raise AssertionError("VLAN ownership UNIQUE is missing")
    except (IntegrityError, OperationalError):
        db.rollback()
    for values in ({"repeat_every": 0}, {"frequency": "hourly"}, {"run_limit": 0}):
        try:
            db.execute(update(m.IPAMScanGroup).where(m.IPAMScanGroup.id == id).values(**values))
            db.commit()
            raise AssertionError("Schedule CHECK is missing")
        except (IntegrityError, OperationalError):
            db.rollback()
barrier = Barrier(2)


def dispatch():
    barrier.wait(timeout=10)
    service.dispatch_due(at)


with ThreadPoolExecutor(max_workers=2) as pool:
    results = [pool.submit(dispatch) for _ in range(2)]
    for result in results:
        result.result(timeout=30)
with session_factory()() as db:
    assert db.get(m.IPAMScanGroup, id).run_count == 1
    assert db.scalar(select(func.count()).select_from(m.IPAMScanRun)) == 1
    assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == "ipam_discover")) == 2
    db.delete(db.get(m.VLAN, vlan_ids[0]))
    db.commit()
    assert len(list(db.scalars(select(m.IPAMScanMember)))) == 1
    atomic = service.save(
        db,
        ScanGroupInput(
            **{**payload, "name": "Atomic", "vlan_ids": vlan_ids[2:], "start_at": at + timedelta(minutes=1)}
        ),
        None,
    )
original = service.enqueue
calls = []


def interrupted(*args, **kwargs):
    calls.append(1)
    if len(calls) == 2:
        raise RuntimeError("Simulated handoff failure")
    return original(*args, **kwargs)


service.enqueue = interrupted
try:
    service.dispatch_due(at + timedelta(minutes=1))
    raise AssertionError("Interruption was not simulated")
except RuntimeError as exc:
    assert "Simulated" in str(exc)
finally:
    service.enqueue = original
with session_factory()() as db:
    assert db.get(m.IPAMScanGroup, atomic["id"]).run_count == 0
    assert not list(db.scalars(select(m.Job).where(m.Job.target_id.in_(vlan_ids[2:]))))
    assert not list(db.scalars(select(m.IPAMScanRun).where(m.IPAMScanRun.group_id == atomic["id"])))
migrate("downgrade", "20261103_34", blocked=True)
with session_factory()() as db:
    for id in list(db.scalars(select(m.IPAMScanGroup.id))):
        service.remove(db, id, None)
migrate("downgrade", "20261103_34")
migrate("upgrade", "head")
parity()
with engine().connect() as db:
    assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261103_35"
print(
    "PASS: MariaDB migration roundtrip/parity, CHECK/UNIQUE/FK, two concurrent schedulers dispatch one slot and failed dispatch rolls all jobs back"
)
