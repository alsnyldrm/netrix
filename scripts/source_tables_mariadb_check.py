"""Disposable MariaDB: verified migration, relational facts, repeat upserts and SQL-only teaming."""

import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from netrix import models as m
from netrix.core import engine, now, session_factory
from netrix.ipam import pipeline, teaming
from netrix.sources import records
from netrix.sources.migrate_v1 import LEGACY, verify
from sqlalchemy import func, inspect, select, text

assert engine().url.database == "netrix_test"
subprocess.run(["alembic", "-c", "backend/alembic.ini", "upgrade", "head"], check=True)
assert not set(LEGACY).intersection(inspect(engine()).get_table_names())
with engine().connect() as c:
    verify(c)
    context = MigrationContext.configure(
        c,
        opts={
            "include_object": lambda obj, name, kind, reflected, compared: (
                kind != "table"
                or name
                in {
                    t.name
                    for t in m.Base.metadata.tables.values()
                    if t.name.startswith(("vmware_", "source_", "ip_resolution_"))
                    or t.name
                    in {
                        "network_source_states",
                        "lldp_neighbors",
                        "cdp_neighbors",
                        "gateway_bindings",
                        "dhcp_bindings",
                        "dns_records",
                        "ping_states",
                        "ip_source_links",
                        "neighbor_links",
                        "discovery_reads",
                        "mac_port_records",
                    }
                }
            )
        },
    )
    assert not compare_metadata(context, m.Base.metadata)
with session_factory()() as db:
    ip = db.get(m.IPAddress, "ip")
    assert ip.hostname == "MANUAL" and ip.operating_system == "MANUAL-OS" and not ip.nic_teaming
    assert db.get(m.IPObservation, "vm-source").data["mac_address"] == "00:11:22:33:44:55"
    result = db.get(m.IPAMResult, "result")
    assert (
        result.values["hostname"],
        result.values["connected_device"],
        result.values["connected_port"],
        result.values["operating_system"],
    ) == ("server.example", "FBU-DS", "89", "Linux")
    assert db.scalar(select(func.count()).select_from(m.VMwareNIC)) == 1
    assert db.scalar(select(func.count()).select_from(m.Link)) == 1
    assert db.scalar(select(func.count()).select_from(m.LLDPNeighbor)) == 1
    assert db.scalar(select(func.count()).select_from(m.CDPNeighbor)) == 1
    state = db.scalar(select(m.IPAMNetworkState).where(m.IPAMNetworkState.device_id == "switch"))
    assert not state.healthy and state.error_class == "TimeoutError"
    assert state.attempted_at > state.observed_at
    assert len(state.mac_entries) == 1 and state.mac_entries[0].port == "A7"
    assert db.scalar(select(m.Event)).details == {"fields": ["hostname"]}
    ip.nic_teaming = True
    resolved = teaming.result("server.example", teaming.neighbors(db, ip, "server.example"), stored=True)
    assert resolved["status"] == "success"
    pipeline.save_result(db, ip, now(), resolved)
    db.commit()
    assert db.get(m.IPAMResult, "result").values["connected_port"] == "A7"
    for _ in range(10):
        pipeline.save_result(db, ip, now(), resolved)
        db.commit()
    assert db.scalar(select(func.count()).select_from(m.ResolutionConnection)) == 1
    assert db.scalar(select(func.count()).select_from(m.IPAMResult)) == 1
    plan = (
        db.execute(text("EXPLAIN SELECT id FROM ip_resolution_results WHERE address_id='ip'"))
        .mappings()
        .one()
    )
    assert plan["key"] and int(plan["rows"]) <= 1
barrier = Barrier(2)


def update_dhcp(index):
    barrier.wait(timeout=10)
    with session_factory()() as db:
        records.dhcp(
            db, "dhcp", {"hostname": "fresh-client", "mac_address": "00:11:22:33:44:66"}, "192.0.2.20"
        )
        db.commit()


with ThreadPoolExecutor(max_workers=2) as pool:
    futures = [pool.submit(update_dhcp, i) for i in range(2)]
    for future in futures:
        future.result(timeout=30)
with session_factory()() as db:
    assert (
        db.scalar(
            select(func.count()).select_from(m.DHCPBinding).where(m.DHCPBinding.address == "192.0.2.20")
        )
        == 1
    )
print(
    "PASS: migration parity, cleanup, typed source equality, NIC-Teaming SQL reads, bounded upserts, concurrent source writes, indexed result lookup"
)
