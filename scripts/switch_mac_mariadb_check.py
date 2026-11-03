"""Real MariaDB constraints/index/migration validation, isolated netrix_test only."""

import subprocess

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from netrix import models as m
from netrix.core import Base, engine, session_factory
from netrix.inventory.device_types import seed_defaults
from netrix.ipam import mac_cache
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import DBAPIError

assert engine().url.database == "netrix_test", "Disposable database required"
revision = "20261103_44"
previous = ScriptDirectory.from_config(Config("backend/alembic.ini")).get_revision(revision).down_revision


def migrate(*args, blocked=False):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True, text=True)
    assert (result.returncode != 0) if blocked else result.returncode == 0, result.stdout + result.stderr


migrate("upgrade", previous)
with session_factory()() as db:
    seed_defaults(db)
    vrf = m.VRF(name="Fixture")
    profile = m.Credential(name="Fixture", protocol="snmpv2c", encrypted_secret="fixture-only")
    db.add_all([vrf, profile])
    db.flush()
    scope = m.Scope(name="Fixture", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=profile.id)
    db.add(scope)
    db.flush()
    device = m.Device(
        name="Cache fixture switch",
        management_ip="192.0.2.1",
        kind="switch",
        vrf_id=vrf.id,
        snmp_credential_id=profile.id,
        discovery_scope_id=scope.id,
    )
    job = m.Job(kind=mac_cache.KIND, target_id=mac_cache.TARGET, status="succeeded")
    db.add_all([device, job])
    db.commit()
    device_id, job_id, vrf_id = device.id, job.id, vrf.id
migrate("upgrade", "head")
with session_factory()() as db:
    device = db.get(m.Device, device_id)
    assert device.name == "Cache fixture switch"
    data = {
        "tables": {
            "vlan_fdb_id": {"0.20": "700"},
            "vlan_fdb_port": {"700.0.17.34.51.68.85": "9"},
            "vlan_fdb_status": {"700.0.17.34.51.68.85": "3"},
            "bridge_ifindex": {"9": "101"},
        },
        "interfaces": [{"if_index": 101, "name": "A1", "oper_status": "up"}],
        "neighbors": [],
        "neighbor_protocols_complete": ["lldp"],
    }
    mac_cache.save_snapshot(db, device, db.get(m.Credential, device.snmp_credential_id), job_id, data)
    db.commit()
    state = db.scalar(select(m.SwitchMacSnapshot))
    state_id = state.id
    for i in range(2048):
        mac = "02:00:00:" + f"{i:06x}"[:2] + ":" + f"{i:06x}"[2:4] + ":" + f"{i:06x}"[4:]
        db.add(
            m.SwitchMacEntry(
                snapshot_id=state.id, vrf_id=vrf_id, vlan_vid=20, mac_address=mac, port="A2", if_index=102
            )
        )
    db.commit()
    for changes in ({"vlan_vid": 5000}, {"if_index": 0}, {"snapshot_id": "missing"}):
        try:
            db.add(
                m.SwitchMacEntry(
                    snapshot_id=changes.get("snapshot_id", state_id),
                    vrf_id=vrf_id,
                    vlan_vid=changes.get("vlan_vid", 20),
                    mac_address="00:11:22:33:44:66",
                    port="B1",
                    if_index=changes.get("if_index", 101),
                )
            )
            db.commit()
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("MariaDB accepted invalid MAC binding")
    plan = (
        db.execute(
            text(
                "EXPLAIN SELECT snapshot_id FROM switch_mac_entries WHERE vrf_id=:vrf AND vlan_vid=20 AND mac_address='00:11:22:33:44:55'"
            ),
            {"vrf": vrf_id},
        )
        .mappings()
        .all()
    )
    assert any(row["key"] == "ix_switch_mac_lookup" for row in plan), plan
    db.delete(db.get(m.SwitchMacSnapshot, state_id))
    db.flush()
    assert not db.scalar(select(m.SwitchMacEntry.id))
    db.rollback()
migrate("downgrade", previous, blocked=True)
with session_factory()() as db:
    db.execute(delete(m.SwitchMacEntry))
    db.execute(delete(m.SwitchMacSnapshot))
    db.commit()
migrate("downgrade", previous)
assert "switch_mac_entries" not in inspect(engine()).get_table_names()
migrate("upgrade", "head")
with engine().connect() as connection:
    ctx = MigrationContext.configure(
        connection,
        opts={
            "compare_type": True,
            "include_object": lambda obj, name, type_, reflected, compare_to: (
                type_ != "table" or name in {"switch_mac_entries", "switch_mac_snapshots"}
            ),
        },
    )
    assert compare_metadata(ctx, Base.metadata) == []
print(
    "PASS: MariaDB migration, CHECK/FK/cascade, selective MAC index, guarded downgrade/upgrade and schema metadata"
)
