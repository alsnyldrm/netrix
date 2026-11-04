"""Post-deployment SQL/source cleanup verification; never queries a device."""

import json

from netrix import models as m
from netrix.core import engine, redis_client
from netrix.sources.migrate_v1 import LEGACY, verify
from sqlalchemy import func, inspect, select, text

assert engine().url.database == "netrix"
tables = set(inspect(engine()).get_table_names())
assert not tables.intersection(LEGACY), "Legacy source tables still exist"
with engine().connect() as connection:
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261104_50"
    verify(connection)
    counts = {
        cls.__tablename__: connection.scalar(select(func.count()).select_from(cls))
        for cls in (
            m.Device,
            m.IPAddress,
            m.GatewayBinding,
            m.DHCPBinding,
            m.VMwareVM,
            m.VMwareHost,
            m.VMwareNIC,
            m.SwitchMacEntry,
            m.LLDPNeighbor,
            m.CDPNeighbor,
            m.IPObservation,
            m.IPAMResult,
            m.Observation,
        )
    }
    assert "nic_teaming" in {c["name"] for c in inspect(connection).get_columns("ip_addresses")}
    for cls, columns in (
        (m.GatewayBinding, ("source_key", "vrf_id", "address", "mac_address", "if_index")),
        (m.DHCPBinding, ("source_key", "address", "mac_address")),
        (m.SwitchMacEntry, ("snapshot_id", "fdb_id", "mac_address", "port")),
        (m.VMwareNIC, ("source_key", "owner_key", "nic_key")),
        (m.LLDPNeighbor, ("link_id",)),
        (m.CDPNeighbor, ("link_id",)),
    ):
        duplicate = connection.execute(
            select(*(getattr(cls, column) for column in columns))
            .group_by(*(getattr(cls, column) for column in columns))
            .having(func.count() > 1)
            .limit(1)
        ).first()
        assert duplicate is None, f"Duplicate canonical identity: {cls.__tablename__}"

# Retire the old short-lived serialized response cache and its revision marker.
# Queued jobs, sessions and all other Redis namespaces remain untouched.
cache = redis_client()
for key in cache.scan_iter(match="netrix:ipam:read:v1:*", count=200):
    cache.unlink(key)
cache.unlink("netrix:ipam:revision")
assert not next(cache.scan_iter(match="netrix:ipam:read:v1:*", count=200), None)
print(json.dumps({"schema": "20261104_50", "legacy_source_tables": 0, "canonical_counts": counts}))
print("PASS: canonical SQL identities, legacy cleanup and obsolete JSON response cache removal")
