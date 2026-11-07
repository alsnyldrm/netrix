"""Point reconciliation reads only relevant SQL and never waits for a VRF-wide mutex."""

import asyncio

from netrix import models as m
from netrix import worker
from netrix.core import now
from netrix.ipam import pipeline, sql_sources
from test_ipam_source_contract import network as network


async def test_sql_context_does_not_eagerly_load_entire_inventory(network, monkeypatch):
    sf, vid, rid, _ = network

    def forbidden(*a, **kw):
        raise AssertionError("Unrelated inventory must not load before source branch is known")

    monkeypatch.setattr(sql_sources, "Evidence", forbidden)
    with sf() as db:
        job = m.Job(kind="ipam_address_scan", target_id=rid, status="running")
        db.add(job)
        db.commit()
        context = sql_sources.SQLContext(db, db.get(m.VLAN, vid), job.id)
        row = db.get(m.IPAddress, rid)
    sources = context.for_row(row)
    assert (await sources.gateway(row.address))["mac_address"] == "00:11:22:33:44:55"
    assert await sources.dns(row.address) == "dns.example"


def test_result_write_does_not_take_global_vrf_lock(network, monkeypatch):
    from netrix import services

    sf, _, rid, _ = network

    def forbidden(*a, **kw):
        raise AssertionError("Point result must not wait for ping VRF mutex")

    monkeypatch.setattr(services, "lock_vrf", forbidden)
    with sf() as db:
        assert pipeline.save_result(
            db,
            db.get(m.IPAddress, rid),
            now(),
            {"status": "problem", "issues": [], "steps": [], "values": {"hostname": "", "mac_address": ""}},
        )
        db.commit()


async def test_point_claim_has_capacity_when_long_jobs_fill_background(env, monkeypatch):
    monkeypatch.setattr(worker, "stop", False)
    running = set()
    long_ready = asyncio.Event()
    point_ready = asyncio.Event()
    release = asyncio.Event()

    async def execute(id):
        with env() as db:
            kind = db.get(m.Job, id).kind
        if kind == "ipam_address_scan":
            point_ready.set()
            return
        running.add(id)
        if len(running) == worker.BACKGROUND_CAPACITY:
            long_ready.set()
        await release.wait()

    monkeypatch.setattr(worker, "execute", execute)
    with env() as db:
        for i in range(worker.BACKGROUND_CAPACITY):
            db.add(m.Job(kind="backup", target_id="long-" + str(i), result={}))
        db.commit()
    task = asyncio.create_task(worker.worker_loop())
    try:
        await asyncio.wait_for(long_ready.wait(), 3)
        with env() as db:
            db.add(m.Job(kind="ipam_address_scan", target_id="point", result={}))
            db.commit()
        await asyncio.wait_for(point_ready.wait(), 2)
        assert len(running) == worker.BACKGROUND_CAPACITY
    finally:
        worker.stop = True
        release.set()
        await asyncio.wait_for(task, 3)


async def test_point_transactions_do_not_queue_behind_bulk_or_ping_writes():
    import threading

    from netrix.runtime_limits import sql_point, sql_quick, sql_write

    release = threading.Event()
    ready = [threading.Event(), threading.Event()]

    def block(index):
        ready[index].set()
        release.wait(3)

    tasks = [asyncio.create_task(sql_write(block, 0)), asyncio.create_task(sql_quick(block, 1))]
    try:
        for marker in ready:
            assert await asyncio.to_thread(marker.wait, 1)
        assert await asyncio.wait_for(sql_point(lambda: "saved"), 0.5) == "saved"
    finally:
        release.set()
        await asyncio.gather(*tasks)


def test_point_projection_excludes_multi_mac_uplinks_but_keeps_all_edge_candidates(network):
    from netrix.ipam.inventory_sources import point_evidence

    sf, vid, rid, ids = network
    with sf() as db:
        template = db.get(m.Device, ids[1])
        noise = m.Device(
            name="Unrelated uplink",
            kind="switch",
            management_ip="198.51.100.99",
            vrf_id=template.vrf_id,
            discovery_scope_id=template.discovery_scope_id,
            snmp_credential_id=template.snmp_credential_id,
        )
        db.add(noise)
        db.flush()
        job = m.Job(kind="discovery", target_id=template.discovery_scope_id)
        db.add(job)
        db.flush()
        db.add(
            m.Observation(
                job_id=job.id,
                device_id=noise.id,
                address=noise.management_ip,
                source="snmpv3",
                evidence={
                    "tables": {
                        "vlan_fdb_id": {"0.20": "700"},
                        "vlan_fdb_port": {"700.0.17.34.51.68.85": "9", "700.0.17.34.51.68.102": "9"},
                        "vlan_fdb_status": {"700.0.17.34.51.68.85": "3", "700.0.17.34.51.68.102": "3"},
                        "bridge_ifindex": {"9": "101"},
                    },
                    "interfaces": [{"name": "Gi1/0/1", "if_index": 101, "oper_status": "up"}],
                    "neighbors": [],
                    "neighbor_protocols_complete": ["lldp", "cdp"],
                },
            )
        )
        db.commit()
        row = db.get(m.IPAddress, rid)
        vlan = db.get(m.VLAN, vid)
        evidence = point_evidence(db, row, vlan, "00:11:22:33:44:55")
        assert noise.id in evidence.devices  # Retain infrastructure identity for uplink checks.
        assert noise.id not in evidence.snapshots
        assert set(ids) <= evidence.snapshots.keys()
        result = evidence.resolve(row, vlan, identity_mac="00:11:22:33:44:55")
        assert {(c["device_id"], c["port"]) for c in result["connections"]} == {(ids[1], "Gi1/0/1")}
