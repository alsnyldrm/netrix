"""Scheduled/manual VLAN scan: bounded ICMP discovery, common gateway-first IP processing."""

import asyncio
from contextlib import aclosing

from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..runtime_limits import sql_quick, sql_read, sql_write
from ..services import in_scope, lock_vrf, publish
from . import absence, pipeline
from .bulk_sources import BulkContext
from .service import observe, scan_boundary, targets


async def scan(job_id, collector):
    from ..worker import Cancelled
    from .jobs import SCAN_BATCH_SIZE, completed_batches, ping_result, scan_phase

    started = now()
    with session_factory()() as db:
        job = db.get(m.Job, job_id)
        vlan = db.get(m.VLAN, job.target_id)
        if job.cancel_requested or not vlan:
            raise Cancelled()
        if job.result.get("ipam_origin") == "manual":
            from .sql_sources import scan_vlan

            manual_sql = True
        else:
            manual_sql = False
    if manual_sql:
        return await scan_vlan(job_id)

    def prepare():
        # Read-only and slow: never keep this snapshot open across a job row write.
        with session_factory()() as db:
            job = db.get(m.Job, job_id)
            vlan = db.get(m.VLAN, job.target_id)
            return vlan, targets(db, vlan, True), BulkContext(db, vlan, collector, job_id)

    vlan, addresses, context = await sql_read(prepare)

    def begin():
        with session_factory()() as db:
            job = db.get(m.Job, job_id)
            current = db.get(m.VLAN, job.target_id)
            if job.cancel_requested or not current:
                raise Cancelled()
            current.last_discovery_at = started
            job.total = len(addresses)
            job.progress = 0
            db.commit()

    await sql_quick(begin)
    await sql_quick(scan_phase, job_id, "gateway")
    await context.network("gateway")
    owned = context.gateway_bindings
    await sql_quick(scan_phase, job_id, "addresses")

    async def ping(address):
        result = await ping_result(address)
        return address, result, now()

    async def ready_batches():
        for start in range(0, len(addresses), SCAN_BATCH_SIZE):
            context.check()
            async with aclosing(
                completed_batches(ping(address) for address in addresses[start : start + SCAN_BATCH_SIZE])
            ) as batches:
                async for ready in batches:
                    yield ready

    checked = reached = problems = resolved = ping_failed = removed = 0
    async with aclosing(ready_batches()) as batches:
        async for ready in batches:
            context.check()

            def store(ready):
                nonlocal checked, reached, ping_failed
                ids = []
                checked_count = reached_count = failed_count = 0
                with session_factory()() as db:
                    job = db.get(m.Job, job_id)
                    vlan = db.get(m.VLAN, job.target_id)
                    if job.cancel_requested or not vlan:
                        raise Cancelled()
                    scope = scan_boundary(db, vlan)
                    lock_vrf(db, vlan.vrf_id)
                    existing = {
                        row.address: row
                        for row in db.scalars(
                            select(m.IPAddress).where(
                                m.IPAddress.vrf_id == vlan.vrf_id,
                                m.IPAddress.address.in_([address for address, _, _ in ready]),
                            )
                        )
                    }
                    for address, up, checked_at in ready:
                        if not in_scope(address, scope):
                            continue
                        row = existing.get(address)
                        if up is None:
                            failed_count += 1
                            checked_count += 1
                            if row and row.vlan_id == vlan.id:
                                ids.append((row.id, up))
                            continue
                        if not up and not row and address not in owned:
                            checked_count += 1
                            continue
                        latest = (
                            db.scalar(
                                select(m.IPObservation.observed_at).where(
                                    m.IPObservation.address_id == row.id,
                                    m.IPObservation.source == "icmp",
                                    m.IPObservation.source_key == vlan.id,
                                )
                            )
                            if row
                            else None
                        )
                        if not latest or latest <= checked_at:
                            row = observe(
                                db,
                                vlan,
                                address,
                                "icmp",
                                vlan.id,
                                {"reachability": "reachable" if up else "no_reply"},
                                create=up or address in owned,
                            )
                        checked_count += 1
                        reached_count += int(up)
                        if row:
                            ids.append((row.id, up))
                    db.commit()
                    checked += checked_count
                    reached += reached_count
                    ping_failed += failed_count
                    return ids, vlan

            ids, vlan = await sql_write(store, ready)
            publish(ipam_vlan=vlan.id)

            async def process(id, up):
                context.check()
                with session_factory()() as db:
                    row = db.get(m.IPAddress, id)
                    if not row or row.vlan_id != vlan.id:
                        return None
                    sources = context.for_row(row)
                result = await pipeline.resolve(row.address, sources)
                context.check()
                may_remove = (
                    up is False
                    and result.get("absence_candidate")
                    and absence.complete_sources(context, vlan, started)
                )

                def save():
                    with session_factory()() as db:
                        job = db.get(m.Job, job_id)
                        current_vlan = db.get(m.VLAN, vlan.id)
                        if (
                            job.cancel_requested
                            or not current_vlan
                            or (
                                current_vlan.vrf_id,
                                current_vlan.cidr,
                                current_vlan.vid,
                                current_vlan.dns_server_id,
                            )
                            != (vlan.vrf_id, vlan.cidr, vlan.vid, vlan.dns_server_id)
                        ):
                            raise Cancelled()
                        current = db.get(m.IPAddress, id)
                        if not current or [current.address, current.vrf_id, current.vlan_id] != [
                            row.address,
                            row.vrf_id,
                            row.vlan_id,
                        ]:
                            return None
                        if may_remove and absence.delete_if_absent(db, current, vlan, started):
                            db.commit()
                            return "removed"
                        written = pipeline.save_result(db, current, started, result)
                        db.commit()
                        return result["status"] if written else None

                status = await sql_write(save)
                if status is None:
                    return None
                publish(ipam_vlan=vlan.id)
                return status

            # Four full resolutions bound per-IP work; scheduled bulk sources are memoized.
            for offset in range(0, len(ids), 4):
                tasks = [asyncio.create_task(process(id, up)) for id, up in ids[offset : offset + 4]]
                try:
                    statuses = await asyncio.gather(*tasks)
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                problems += statuses.count("problem")
                removed += statuses.count("removed")
                resolved += sum(s is not None for s in statuses)

            def record():
                with session_factory()() as db:
                    job = db.get(m.Job, job_id)
                    if job.cancel_requested:
                        raise Cancelled()
                    job.progress = checked
                    job.result = {
                        **job.result,
                        "resolved": resolved,
                        "problems": problems,
                        "removed": removed,
                    }
                    db.commit()

            await sql_quick(record)
            publish(ipam_vlan=vlan.id)

    def finish():
        from ..sources.cleanup import prune
        from ..sources.resolutions import prepare_read
        from .service import observations

        with session_factory()() as db:
            prune(db, inventory=False)
            db.commit()
            results = list(
                db.scalars(
                    select(m.IPAMResult)
                    .join(m.IPAddress, m.IPAddress.id == m.IPAMResult.address_id)
                    .where(m.IPAddress.vlan_id == vlan.id)
                )
            )
            if results:
                addresses = list(db.scalars(select(m.IPAddress).where(m.IPAddress.vlan_id == vlan.id)))
                prepare_read(db, results, observations(db, addresses))
            matching = {
                field: sum(bool(r.values.get(field)) for r in results)
                for field in (
                    "hostname",
                    "mac_address",
                    "connected_device",
                    "connected_port",
                    "operating_system",
                )
            }
            matching.update(
                addresses=len(results),
                ambiguous=sum(any(i["code"] == "ambiguous" for i in r.issues) for r in results),
            )
            return matching

    matching = await sql_write(finish)
    await sql_quick(
        scan_phase,
        job_id,
        "complete",
        resolved=resolved,
        problems=problems,
        removed=removed,
        matching=matching,
    )
    return {
        "checked": checked,
        "reachable": reached,
        "no_reply": checked - reached - ping_failed,
        "ping_failed": ping_failed,
        "source_jobs": [],
        "source_failed": int(bool(context.errors) or problems > 0 or ping_failed > 0),
        "resolved": resolved,
        "problems": problems,
        "removed": removed,
        "matching": matching,
        "network": {
            "switch_mode": "inventory_sql",
            "devices": sum(context.read_counts.values()),
            "read": sum(context.read_counts.values()) - len(context.failed_devices),
            "failed": len(context.failed_devices),
        },
    }
