"""Disposable MariaDB only: migration, bounded upserts, index, cascade and rollback guard."""

import subprocess

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models as m
from netrix.core import Base, engine, now, session_factory
from netrix.inventory.device_types import seed_defaults
from netrix.ipam.pipeline import save_result
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

assert engine().url.database == "netrix_test", "Disposable database required"


def migrate(*args, blocked=False):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True, text=True)
    assert (result.returncode != 0) if blocked else result.returncode == 0, result.stdout + result.stderr


migrate("upgrade", "20261104_48")
with session_factory()() as db:
    seed_defaults(db)
    vrf = m.VRF(name="Fixture")
    db.add(vrf)
    db.flush()
    vlan = m.VLAN(name="Fixture", vid=20, vrf_id=vrf.id, cidr="192.0.2.0/24")
    db.add(vlan)
    db.flush()
    row = m.IPAddress(
        address="192.0.2.10",
        vrf_id=vrf.id,
        vlan_id=vlan.id,
        hostname="MANUAL",
        mac_address="00:11:22:33:44:55",
    )
    device = m.Device(name="Fixture", management_ip="198.51.100.1", kind="other", vrf_id=vrf.id)
    db.add_all([row, device])
    db.commit()
    id, device_id = row.id, device.id
migrate("upgrade", "head")
with session_factory()() as db:
    row = db.get(m.IPAddress, id)
    assert row.hostname == "MANUAL"
    for i in range(100):
        assert save_result(
            db,
            row,
            now(),
            {
                "status": "success",
                "values": {"hostname": f"host-{i}", "mac_address": "00:11:22:33:44:55"},
                "issues": [],
                "steps": [{"source": "gateway", "status": "ok"}],
            },
        )
        db.commit()
    result = db.scalar(select(m.IPAMResult))
    assert result.values["hostname"] == "host-99"
    assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 1
    explain = (
        db.execute(text("EXPLAIN SELECT id FROM ipam_results WHERE address_id=:id"), {"id": id})
        .mappings()
        .one()
    )
    assert explain["key"] and int(explain["rows"]) <= 1, dict(explain)
    duplicate = m.IPAMResult(
        address_id=id,
        address_scope=[],
        status="success",
        values={},
        issues=[],
        steps=[],
        retained=False,
        started_at=now(),
        completed_at=now(),
    )
    db.add(duplicate)
    try:
        db.commit()
        raise AssertionError("Unique address result not enforced")
    except DBAPIError:
        db.rollback()
    item = db.scalar(select(m.IPAMResult))
    item.status = "bad"
    try:
        db.commit()
        raise AssertionError("Invalid result status allowed")
    except DBAPIError:
        db.rollback()
    db.add(m.IPAMNetworkState(device_id=device_id, address="198.51.100.1", evidence={}, observed_at=now()))
    db.commit()
    assert db.scalar(select(func.count()).select_from(m.IPAMNetworkState)) == 1
migrate("downgrade", "20261104_48", blocked=True)
with engine().connect() as connection:
    differences = compare_metadata(
        MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "include_object": lambda obj, name, type_, reflected, compare_to: (
                    (name in {"ipam_results", "ipam_network_states"})
                    if type_ == "table"
                    else (
                        not hasattr(obj, "table") or obj.table.name in {"ipam_results", "ipam_network_states"}
                    )
                ),
            },
        ),
        Base.metadata,
    )
    assert differences == [], differences
with session_factory()() as db:
    db.delete(db.get(m.IPAddress, id))
    db.delete(db.get(m.Device, device_id))
    db.commit()
    assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 0
    assert db.scalar(select(func.count()).select_from(m.IPAMNetworkState)) == 0
migrate("downgrade", "20261104_48")
migrate("upgrade", "head")
print(
    "PASS: MariaDB migration, preserved data, one-row upserts, indexed lookup, constraints, cascades and rollback guard"
)
