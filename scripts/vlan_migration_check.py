"""Validate data-preserving VLAN ownership and config bases on disposable MariaDB."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from sqlalchemy import inspect, select

assert engine().url.database == "netrix_test"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
assert "prefixes" not in inspect(engine()).get_table_names()
with session_factory()() as db:
    vlan = db.get(m.VLAN, "fixture-vlan")
    assert vlan.cidr == "192.0.2.0/24" and vlan.warning_threshold == 75
    assert db.get(m.IPAddress, "fixture-address").vlan_id == vlan.id
    assert db.get(m.IPAddress, "fixture-address").hostname == "preserved"
    d = db.get(m.Device, "fixture-device")
    assert d.base_snapshot_id == "fixture-snapshot-0" and d.discovery_scope_id == "fixture-scope"
    assert not db.get(m.Snapshot, "fixture-snapshot-1").changed
    assert db.get(m.Snapshot, "fixture-snapshot-2").changed
    assert db.scalar(select(m.Integration)) is None
    assert db.get(m.Scope, "fixture-scope").vlan_vid == 20
subprocess.run(["alembic", "-c", "backend/alembic.ini", "check"], check=True)
print(
    "PASS: VLAN/IP ownership, removed switch integrations, first base config, normalized differences, schema parity"
)
