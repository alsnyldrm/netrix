"""Migrate current source facts in disposable SQL; fail before legacy cleanup on loss."""

import subprocess
import time

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.ipam.service import enrich
from netrix.sources.migrate_v1 import LEGACY, verify
from sqlalchemy import func, inspect, select

assert engine().url.database == "netrix_test"
started = time.perf_counter()
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
assert not set(LEGACY).intersection(inspect(engine()).get_table_names())
with engine().connect() as c:
    verify(c)
with session_factory()() as db:
    for cls in (
        m.GatewayBinding,
        m.DHCPBinding,
        m.VMwareVM,
        m.VMwareHost,
        m.VMwareNIC,
        m.VMwareAddress,
        m.SwitchMacEntry,
        m.LLDPNeighbor,
        m.CDPNeighbor,
        m.IPObservation,
        m.IPAMResult,
        m.Observation,
    ):
        print(cls.__tablename__, db.scalar(select(func.count()).select_from(cls)))
    rows = list(
        db.scalars(
            select(m.IPAddress).join(m.IPAMResult, m.IPAMResult.address_id == m.IPAddress.id).limit(100)
        )
    )
    before = time.perf_counter()
    values = enrich(db, rows, details=False)
    assert len(values) == len(rows)
    print(f"SQL summary read {len(values)} IPs: {(time.perf_counter() - before) * 1000:.1f}ms")
print(
    f"PASS: current-source rehearsal, verified legacy cleanup; elapsed {time.perf_counter() - started:.1f}s"
)
