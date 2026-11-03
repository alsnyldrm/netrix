"""Disposable MariaDB: schedule-only policy, legacy job cleanup and bounded ping intervals."""

import subprocess
from datetime import timedelta

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from netrix import models as m
from netrix.core import engine, now, session_factory
from sqlalchemy import inspect

assert engine().url.database == "netrix_test", "Dedicated disposable database required"
revision = "20261103_41"
previous = ScriptDirectory.from_config(Config("backend/alembic.ini")).get_revision(revision).down_revision


def migrate(*args, blocked=False):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True, text=True)
    assert (result.returncode != 0) if blocked else result.returncode == 0, result.stdout + result.stderr


migrate("upgrade", previous)
with session_factory()() as db:
    vrf = m.VRF(name="Timer fixture")
    db.add(vrf)
    db.flush()
    vlan = m.VLAN(
        name="Timer fixture",
        vid=20,
        cidr="192.0.2.0/30",
        vrf_id=vrf.id,
        ping_enabled=False,
        ping_interval=300,
        discovery_enabled=True,
    )
    config = m.Integration(
        name="Old timer",
        kind="vcenter",
        host="fixture.test",
        port=443,
        encrypted_secret="fixture-only",
        interval_seconds=120,
    )
    group = m.IPAMScanGroup(
        name="Scheduled",
        frequency="daily",
        start_at=now() + timedelta(days=1),
        next_run_at=now() + timedelta(days=1),
    )
    db.add_all([vlan, config, group])
    db.flush()
    child = m.Job(
        kind="integration", target_id=config.id, status="running", active_key="integration:" + config.id
    )
    db.add(child)
    db.flush()
    full = m.Job(
        kind="ipam_discover",
        target_id=vlan.id,
        result={"source_jobs": [child.id]},
        active_key="ipam_discover:" + vlan.id,
    )
    old = [
        m.Job(kind="ipam_discover", target_id="legacy"),
        m.Job(kind="ipam_ping", target_id=vlan.id),
        m.Job(kind="integration", target_id="legacy"),
    ]
    db.add_all([full, *old])
    db.flush()
    db.add(
        m.IPAMScanRun(
            group_id=group.id,
            generation=0,
            scheduled_for=now(),
            jobs=[{"job_id": full.id, "vlan_id": vlan.id}],
        )
    )
    db.commit()
    vlan_id, config_id, group_id, full_id, child_id = vlan.id, config.id, group.id, full.id, child.id
    old_ids = [row.id for row in old]
    start, next_run, run_count = group.start_at, group.next_run_at, group.run_count
migrate("upgrade", "head")
with engine().connect() as conn:
    ctx = MigrationContext.configure(
        conn,
        opts={
            "include_object": lambda obj, name, kind, reflected, compared: kind != "table" or name == "vlans"
        },
    )
    assert not compare_metadata(ctx, m.Base.metadata)
    constraint = next(
        c for c in inspect(conn).get_check_constraints("vlans") if c["name"] == "ck_vlan_intervals"
    )
    assert "10" in constraint["sqltext"]
with session_factory()() as db:
    vlan, group = db.get(m.VLAN, vlan_id), db.get(m.IPAMScanGroup, group_id)
    assert vlan.ping_enabled and vlan.ping_interval == 30 and not vlan.discovery_enabled
    assert db.get(m.Integration, config_id).interval_seconds == 0
    assert (group.start_at, group.next_run_at, group.run_count) == (start, next_run, run_count)
    assert db.get(m.Job, full_id).result["ipam_origin"] == "schedule"
    assert db.get(m.Job, child_id).result["ipam_origin"] == "scheduled_source"
    for id in old_ids:
        row = db.get(m.Job, id)
        assert row.status == "cancelled" and row.cancel_requested and row.active_key is None
    assert len(db.query(m.Job).all()) == 5
    vlan.ping_interval = 10
    db.commit()
migrate("downgrade", previous, blocked=True)
with session_factory()() as db:
    db.get(m.VLAN, vlan_id).ping_interval = 30
    db.commit()
migrate("downgrade", previous)
migrate("upgrade", "head")
print(
    "PASS: MariaDB schedule policy, 30-second defaults, 10-second constraint, no new jobs, preserved groups and scheduled work, cancelled legacy work, schema parity and rollback"
)
