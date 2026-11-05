"""Disposable MariaDB: lossless read-outcome migration and partial SNMP writes."""

import subprocess
from datetime import timedelta

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.sources import network
from sqlalchemy import select

assert engine().url.database == "netrix_test", "Disposable database required"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
with session_factory()() as db:
    vrf = m.VRF(name="Integrity fixture")
    db.add(vrf)
    db.flush()
    device = m.Device(name="Edge", management_ip="198.51.100.2", vrf_id=vrf.id, kind="switch")
    db.add(device)
    db.flush()
    state = network.state_for(db, device.id, device.management_ip)
    data = {
        "interfaces": [{"if_index": 101, "name": "1/1/1", "oper_status": "up"}],
        "tables": {
            "vlan_fdb_id": {"0.60": "700"},
            "vlan_fdb_port": {"700.0.17.34.51.68.85": "9"},
            "vlan_fdb_status": {"700.0.17.34.51.68.85": "3"},
            "bridge_ifindex": {"9": "101"},
        },
    }
    at = now()
    network.write(db, state, data, at)
    db.commit()
    state_id, fact_id = state.id, state.mac_entries[0].id
# This removes only new diagnostic columns, keeping source rows and identities.
subprocess.run(["alembic", "-c", "backend/alembic.ini", "downgrade", "20261104_50"], check=True)
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
with session_factory()() as db:
    state = db.get(m.IPAMNetworkState, state_id)
    assert state.mac_entries[0].id == fact_id
    for step in range(3):
        network.write(
            db,
            state,
            {
                "tables": {"vlan_fdb_port": {}, "vlan_fdb_status": {}, "bridge_ifindex": {"9": "101"}},
                "unsupported": ["vlan_fdb_port", "vlan_fdb_status"],
                "table_reads": {
                    "vlan_fdb_port": {"status": "timeout", "row_count": 0, "error_code": "table_timeout"},
                    "vlan_fdb_status": {"status": "error", "row_count": 0, "error_code": "pdu_5"},
                    "bridge_ifindex": {"status": "complete", "row_count": 1},
                },
            },
            at + timedelta(seconds=step + 1),
        )
        db.commit()
        db.expire_all()
        state = db.get(m.IPAMNetworkState, state_id)
        assert len(state.mac_entries) == 1 and state.mac_entries[0].id == fact_id
        assert state.mac_entries[0].present and state.mac_entries[0].status == "3"
        assert state.mac_entries[0].vlan_vid == 60 and state.fdb_at == at
        assert len(state.unsupported) == 4
        assert next(x for x in state.unsupported if x.name == "vlan_fdb_port").error_code == "table_timeout"
    assert len(list(db.scalars(select(m.SourceVLANFDB)))) == 1
with engine().connect() as connection:
    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda obj, name, kind, reflected, compared: (
                kind != "table" or name == "source_unsupported_tables"
            )
        },
    )
    assert not compare_metadata(context, m.Base.metadata)
print(
    "PASS: MariaDB 50/51 migration roundtrip, stable MAC identity/VLAN, partial-read retention, bounded read outcomes and schema parity"
)
