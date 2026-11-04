"""Scheduled/manual VLAN scan: bounded ICMP discovery, common gateway-first IP processing."""

import asyncio
from contextlib import aclosing

from .. import models as m
from ..core import now, session_factory
from ..services import in_scope, publish
from . import adapters, pipeline
from .bulk_sources import BulkContext
from .scoped_vlan_sources import ScopedVLANContext
from .service import observe, scan_boundary, targets


async def scan(job_id, collector):
    from ..worker import Cancelled
    from .jobs import SCAN_BATCH_SIZE, completed_batches, scan_phase

    started = now()
    with session_factory()() as db:
        job = db.get(m.Job, job_id)
        vlan = db.get(m.VLAN, job.target_id)
        if job.cancel_requested or not vlan:
            raise Cancelled()
        addresses = targets(db, vlan, True)
        manual = job.result.get("ipam_origin") == "manual"
        context = (ScopedVLANContext if manual else BulkContext)(db, vlan, collector, job_id)
        vlan.last_discovery_at = started
        job.total = len(addresses)
        job.progress = 0
        db.commit()
    scan_phase(job_id, "gateway")
    # Finish each source stage before advancing its dependent branch.
    if not manual:
        await context.network("gateway")
    owned = set()
    import ipaddress

    from .connections import gateway_interfaces

    snapshots = () if manual else context.gateway_evidence.snapshots.values()
    for _, projected in snapshots:
        indexes = gateway_interfaces(projected["tables"], ipaddress.ip_network(vlan.cidr))
        owned.update(
            address
            for address, bindings in projected["bindings"].items()
            if any(index in indexes for _, index in bindings)
        )
    scan_phase(job_id, "addresses")
    checked, reached, problems, resolved = 0, 0, 0, 0
    for start in range(0, len(addresses), SCAN_BATCH_SIZE):
        context.check()

        async def ping(address):
            up = await adapters.ping(address)
            gateway = await context.gateway(address) if manual else None
            return address, up, gateway

        async with aclosing(
            completed_batches(ping(a) for a in addresses[start : start + SCAN_BATCH_SIZE])
        ) as batches:
            async for ready in batches:
                ids = []
                with session_factory()() as db:
                    job = db.get(m.Job, job_id)
                    vlan = db.get(m.VLAN, job.target_id)
                    if job.cancel_requested or not vlan:
                        raise Cancelled()
                    scope = scan_boundary(db, vlan)
                    for address, up, gateway in ready:
                        if not in_scope(address, scope):
                            continue
                        row = observe(
                            db,
                            vlan,
                            address,
                            "icmp",
                            vlan.id,
                            {"reachability": "reachable" if up else "no_reply"},
                            create=up
                            or address in owned
                            or bool(isinstance(gateway, dict) and gateway.get("mac_address")),
                        )
                        checked += 1
                        reached += int(up)
                        if row:
                            ids.append((row.id, gateway))
                    db.commit()
                publish(ipam_vlan=vlan.id)

                async def process(id, gateway):
                    context.check()
                    with session_factory()() as db:
                        row = db.get(m.IPAddress, id)
                        if not row or row.vlan_id != vlan.id:
                            return None
                        sources = context.for_row(row, gateway) if manual else context.for_row(row)
                    result = await pipeline.resolve(row.address, sources)
                    context.check()
                    if manual:
                        sources.check()
                    with session_factory()() as db:
                        current = db.get(m.IPAddress, id)
                        if not current or [current.address, current.vrf_id, current.vlan_id] != [
                            row.address,
                            row.vrf_id,
                            row.vlan_id,
                        ]:
                            return None
                        pipeline.save_result(db, current, started, result)
                        db.commit()
                    publish(ipam_vlan=vlan.id)
                    return result["status"]

                # Four full resolutions bound per-IP work; scheduled bulk sources are memoized.
                for offset in range(0, len(ids), 4):
                    tasks = [asyncio.create_task(process(id, g)) for id, g in ids[offset : offset + 4]]
                    try:
                        statuses = await asyncio.gather(*tasks)
                    finally:
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                    problems += statuses.count("problem")
                    resolved += sum(s is not None for s in statuses)
                with session_factory()() as db:
                    job = db.get(m.Job, job_id)
                    if job.cancel_requested:
                        raise Cancelled()
                    job.progress = checked
                    job.result = {**job.result, "resolved": resolved, "problems": problems}
                    db.commit()
                publish(ipam_vlan=vlan.id)
    from sqlalchemy import select

    with session_factory()() as db:
        results = list(
            db.scalars(
                select(m.IPAMResult)
                .join(m.IPAddress, m.IPAddress.id == m.IPAMResult.address_id)
                .where(m.IPAddress.vlan_id == vlan.id)
            )
        )
        matching = {
            field: sum(bool(r.values.get(field)) for r in results)
            for field in ("hostname", "mac_address", "connected_device", "connected_port", "operating_system")
        }
        matching.update(
            addresses=len(results),
            ambiguous=sum(any(i["code"] == "ambiguous" for i in r.issues) for r in results),
        )
    scan_phase(job_id, "complete", resolved=resolved, problems=problems, matching=matching)
    return {
        "checked": checked,
        "reachable": reached,
        "no_reply": checked - reached,
        "source_jobs": [],
        "source_failed": int(bool(context.errors) or problems > 0),
        "resolved": resolved,
        "problems": problems,
        "matching": matching,
        "network": {
            "mode": "targeted",
            "targeted_ips": context.read_counts["gateway"],
            "failed": len(context.errors),
        }
        if manual
        else {
            "devices": sum(context.read_counts.values()),
            "read": sum(context.read_counts.values()) - len(context.failed_devices),
            "failed": len(context.failed_devices),
        },
    }
