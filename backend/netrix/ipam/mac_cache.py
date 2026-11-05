"""Independent six-hour switch FDB cache; read-only fallback to primary IPAM evidence."""

import asyncio
import json
import time
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, tuple_
from sqlalchemy.orm import load_only

from .. import models as m
from ..core import now, session_factory
from ..discovery.protocols import NetworkError
from ..identity.security import audit, secret_data
from ..services import get, publish
from .connections import Evidence, Snapshot, projections

KIND = "switch_mac_scan"
TARGET = "switch-mac-cache"
LEDGER = "switch_mac_scan_slot"
FRESHNESS = timedelta(hours=7)
SCHEDULE_TIMES = ["00:00", "06:00", "12:00", "18:00"]
REQUIRED = {"vlan_fdb_port", "vlan_fdb_status", "bridge_ifindex"}


def is_switch(device):
    return device.kind not in {"router", "firewall"} and (
        device.kind == "switch"
        or device.device_type.name.casefold()
        in {"switch", "backbone", "backbone switch", "corner switch", "san switch"}
    )


def devices(db):
    return [
        d
        for d in db.scalars(
            select(m.Device)
            .join(m.Credential, m.Credential.id == m.Device.snmp_credential_id)
            .where(
                m.Credential.protocol.in_(("snmpv2c", "snmpv3")),
                m.Device.archived.is_(False),
                m.Device.lifecycle_status == "active",
                m.Device.discovery_scope_id.is_not(None),
                m.Device.snmp_credential_id.is_not(None),
            )
            .order_by(m.Device.management_ip, m.Device.id)
        )
        if is_switch(d)
    ]


def context(device, profile):
    from .network import read_context

    return read_context(device, profile, None)


def slot(at):
    local = at.astimezone(ZoneInfo("Europe/Istanbul"))
    return local.replace(hour=(local.hour // 6) * 6, minute=0, second=0, microsecond=0).astimezone(
        timezone.utc
    )


def _enqueue(db, *, user=None, scheduled_at=None):
    """Singleton durable queue entry; repeated API/scheduler calls share one active scan."""
    from fastapi import HTTPException
    from sqlalchemy.dialects.mysql import insert as mysql_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    if scheduled_at is None and user is None:
        raise HTTPException(409, "Switch MAC taraması zamanlama veya yetkili kullanıcı gerektirir")
    statement = (sqlite_insert if db.get_bind().dialect.name == "sqlite" else mysql_insert)(
        m.SystemState
    ).values(key=LEDGER, value="")
    statement = (
        statement.on_conflict_do_nothing(index_elements=["key"])
        if db.get_bind().dialect.name == "sqlite"
        else statement.on_duplicate_key_update(key=LEDGER)
    )
    db.execute(statement)
    ledger = db.scalar(select(m.SystemState).where(m.SystemState.key == LEDGER).with_for_update())
    due = slot(scheduled_at).isoformat() if scheduled_at else None
    saved = json.loads(ledger.value) if ledger.value.startswith("{") else {"slot": ledger.value, "version": 0}
    if due and saved["slot"] >= due:
        db.commit()
        return None
    if not devices(db):
        db.commit()
        if user:
            raise HTTPException(422, "MAC tablosu okunabilecek etkin switch ve SNMP profili bulunamadı")
        return None
    job = db.scalar(select(m.Job).where(m.Job.active_key == KIND))
    if not job:
        if not due and not user:
            raise HTTPException(409, "Switch MAC taraması zamanlama veya yetkili kullanıcı gerektirir")
        job = m.Job(
            kind=KIND,
            target_id=TARGET,
            active_key=KIND,
            requested_by=user.id if user else None,
            result={"origin": "schedule" if due else "manual", "slot": due},
        )
        db.add(job)
        db.flush()
        audit(db, user, "enqueue", "jobs", job.id, "Switch MAC tablosu taraması kuyruğa alındı")
    ledger.value = json.dumps(
        {"slot": due or saved["slot"], "version": saved["version"] + 1}, separators=(",", ":")
    )
    db.commit()
    publish(ipam_vlan="*")
    return job


def enqueue(db, *, user=None, scheduled_at=None):
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError, OperationalError

    for attempt in range(3):
        try:
            return _enqueue(db, user=user, scheduled_at=scheduled_at)
        except (IntegrityError, OperationalError) as exc:
            db.rollback()
            code = getattr(exc.orig, "args", [None])[0]
            if code not in (1062, 1205, 1213):
                raise
            if attempt == 2:
                raise HTTPException(409, "MAC taraması kuyruğu meşgul; tekrar deneyin") from None
            time.sleep(0.05 * (attempt + 1))


def save_snapshot(db, device, profile, job_id, evidence, *, error=""):
    """Diff current rows in one transaction; failed/partial reads never retire old bindings."""
    state = db.scalar(
        select(m.SwitchMacSnapshot).where(m.SwitchMacSnapshot.device_id == device.id).with_for_update()
    )
    if state is None:
        state = m.SwitchMacSnapshot(device_id=device.id)
        db.add(state)
        db.flush()
    state.address = device.management_ip
    state.job_id, state.attempted_at = job_id, now()
    incomplete = (
        (REQUIRED | {"if_status"}) & set(evidence.get("unsupported") or [])
        or not REQUIRED <= (evidence.get("tables") or {}).keys()
        or not evidence.get("interfaces")
        or {"if_name", "if_descr"} <= set(evidence.get("unsupported") or [])
    )
    if error or evidence.get("failed") or incomplete:
        # Persist read diagnostics and valid positive rows; never retire previous facts.
        from ..sources.network import write

        write(db, state, {**evidence, "failed": bool(error or evidence.get("failed"))}, now())
        state.healthy = False
        state.error_class = error or ("IncompleteFDB" if incomplete else "SourceFailed")
        db.flush()
        return {"read": 0, "failed": 1, "added": 0, "removed": 0, "error_class": state.error_class}
    existing = {(e.fdb_id, e.mac_address, e.port) for e in state.mac_entries if e.present}
    state.observed_at, state.healthy, state.error_class = now(), True, ""
    state.read_context = context(device, profile)
    state.evidence = evidence
    db.flush()
    current = {(e.fdb_id, e.mac_address, e.port) for e in state.mac_entries if e.present}
    added, removed = len(current - existing), len(existing - current)
    if any(r.name in REQUIRED and r.status != "complete" for r in state.unsupported):
        state.healthy, state.error_class = False, "IncompleteFDB"
        db.flush()
        return {"read": 0, "failed": 1, "added": added, "removed": 0, "error_class": state.error_class}
    if added or removed:
        db.add(
            m.Event(
                device_id=device.id,
                kind="switch_mac_change",
                message=f"{device.name}: switch MAC tablosu güncellendi",
                details={"added": added, "removed": removed},
            )
        )
    db.flush()
    return {"read": 1, "failed": 0, "added": added, "removed": removed}


async def scan(job_id, collector):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        if (
            job.target_id != TARGET
            or job.result.get("origin") not in ("schedule", "manual")
            or (job.result.get("origin") == "manual" and not job.requested_by)
        ):
            raise Cancelled()
        ids = [d.id for d in devices(db)]
        if not ids:
            raise Cancelled()
        job.total, job.progress = len(ids), 0
        db.commit()
    semaphore = asyncio.Semaphore(4)

    async def read(id):
        async with semaphore:
            with session_factory()() as db:
                if get(db, m.Job, job_id).cancel_requested:
                    raise Cancelled()
                device = get(db, m.Device, id)
                profile = get(db, m.Credential, device.snmp_credential_id)
                expected = context(device, profile)
                secret = secret_data(profile)
            evidence, error = {}, ""
            try:
                async with asyncio.timeout(185):
                    for attempt in range(3):
                        try:
                            evidence = await collector.switch_macs(
                                device.management_ip, device.snmp_port, secret
                            )
                            break
                        except (TimeoutError, OSError, NetworkError):
                            if attempt == 2:
                                raise
                            await asyncio.sleep(attempt + 1)
            except (TimeoutError, OSError, NetworkError) as exc:
                error = type(exc).__name__
            with session_factory()() as db:
                job = get(db, m.Job, job_id)
                current = db.get(m.Device, id)
                profile = (
                    db.get(m.Credential, current.snmp_credential_id)
                    if current and current.snmp_credential_id
                    else None
                )
                if job.cancel_requested:
                    raise Cancelled()
                if (
                    not profile
                    or context(current, profile) != expected
                    or current.archived
                    or current.lifecycle_status != "active"
                    or not is_switch(current)
                ):
                    result = {
                        "read": 0,
                        "failed": 1,
                        "added": 0,
                        "removed": 0,
                        "error_class": "SourceChanged",
                    }
                else:
                    result = save_snapshot(db, current, profile, job_id, evidence, error=error)
                job.progress += 1
                totals = job.result.get("totals", {"read": 0, "failed": 0, "added": 0, "removed": 0})
                totals = {key: totals[key] + result[key] for key in totals}
                failures = job.result.get("failed_devices", [])
                if result["failed"]:
                    failures = [
                        *failures,
                        {
                            "device_id": id,
                            "device_name": device.name,
                            "error_class": result.get("error_class", "SourceFailed"),
                        },
                    ]
                job.result = {**job.result, "totals": totals, "failed_devices": failures}
                from ..sources.cleanup import prune

                prune(db)
                db.commit()
            from .result_fallback import refresh

            with session_factory()() as db:
                refresh(db, id)
                db.commit()
            publish(ipam_vlan="*")
            return result

    tasks = [asyncio.create_task(read(id)) for id in ids]
    try:
        results = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {key: sum(r[key] for r in results) for key in ("read", "failed", "added", "removed")}


class CachedEvidence(Evidence):
    def _static_links(self, vrf_id, cutoff):
        return super()._static_links(vrf_id, self.at - FRESHNESS)


def fallback(db, rows, items, prefixes, primary, *, scoped=None):
    """One indexed bulk lookup, only for rows without any primary/manual/VM attachment."""
    eligible = {}
    for row, item in zip(rows, items):
        macs = {g["mac_address"] for g in item.get("gateway_evidence", [])}
        if (
            len(macs) != 1
            or item.get("mac_conflict")
            or item.get("gateway_mac_conflict")
            or item.get("connection_ambiguous")
            or item.get("connected_device")
            or item.get("connected_port")
            or item.get("connections")
            or item.get("connection_type") == "vcenter"
            or item.get("manual_connection")
        ):
            continue
        eligible[row.id] = (row.vrf_id, prefixes[row.vlan_id].vid, next(iter(macs)))
    if not eligible:
        return items
    pairs, ids = list(set(eligible.values())), set()
    for start in range(0, len(pairs), 250):
        ids.update(
            db.scalars(
                select(m.SwitchMacEntry.snapshot_id).where(
                    tuple_(
                        m.SwitchMacEntry.vrf_id, m.SwitchMacEntry.vlan_vid, m.SwitchMacEntry.mac_address
                    ).in_(pairs[start : start + 250])
                )
            )
        )
    states = (
        list(
            db.scalars(
                select(m.SwitchMacSnapshot)
                .options(
                    load_only(
                        m.SwitchMacSnapshot.id,
                        m.SwitchMacSnapshot.device_id,
                        m.SwitchMacSnapshot.observed_at,
                        m.SwitchMacSnapshot.updated_at,
                    )
                )
                .where(
                    m.SwitchMacSnapshot.id.in_(ids),
                    m.SwitchMacSnapshot.healthy.is_(True),
                    m.SwitchMacSnapshot.observed_at >= primary.at - FRESHNESS,
                )
            )
        )
        if ids
        else []
    )
    profiles = (
        {
            p.id: p
            for p in db.scalars(
                select(m.Credential)
                .options(load_only(m.Credential.id, m.Credential.updated_at))
                .where(
                    m.Credential.id.in_(
                        {
                            primary.devices[s.device_id].snmp_credential_id
                            for s in states
                            if s.device_id in primary.devices
                        }
                    )
                )
            )
        }
        if states
        else {}
    )
    valid = []
    for state in states:
        device = primary.devices.get(state.device_id)
        profile = profiles.get(device.snmp_credential_id) if device else None
        if (
            device
            and profile
            and device.lifecycle_status == "active"
            and is_switch(device)
            and state.read_context == context(device, profile)
        ):
            valid.append(state)
    if not valid:
        return items
    cached = CachedEvidence.__new__(CachedEvidence)
    cached.__dict__.update(primary.__dict__)
    cached.static, cached.attached = {}, {}
    cached.snapshots = {
        s.device_id: (Snapshot(s.id, s.observed_at), p)
        for s, p in projections(db, valid, model=m.SwitchMacSnapshot)
    }
    cached.links = [l for l in primary.links if l.device_id in cached.snapshots]
    cached.raw_neighbors, cached.excluded_raw_neighbors = {}, {}
    cached.refresh_neighbors()
    for row, item in zip(rows, items):
        if row.id not in eligible:
            continue
        resolver = cached
        address_primary = (scoped or {}).get(row.id)
        if address_primary:
            # A new one-IP read (including an empty/failed source) supersedes
            # older cached positives for that source, only for this address.
            snapshots = {
                id: value
                for id, value in cached.snapshots.items()
                if id not in address_primary.snapshots
                or value[0].created_at > address_primary.snapshots[id][0].created_at
            }
            if not snapshots:
                continue
            resolver = CachedEvidence.__new__(CachedEvidence)
            resolver.__dict__.update(cached.__dict__)
            resolver.snapshots = snapshots
            resolver.links = [l for l in cached.links if l.device_id in snapshots]
            resolver.static, resolver.attached = {}, {}
            resolver.raw_neighbors, resolver.excluded_raw_neighbors = {}, {}
            resolver.refresh_neighbors()
        proof = resolver.resolve(
            row, prefixes[row.vlan_id], identity_mac=eligible[row.id][2], identity_source="switch_mac_cache"
        )
        if not proof["connections"]:
            continue
        for candidate in proof["connections"]:
            candidate["primary_source"] = candidate["source"]
            candidate["source"] = "switch_mac_cache"
        for key in (
            "connections",
            "connection_groups",
            "connected_device",
            "connected_port",
            "connection_type",
            "connection_ambiguous",
            "connection_reason",
        ):
            item[key] = proof[key]
        item["connection_type"] = "switch_mac_cache" if proof["connected_device"] else ""
        item["sources"] = sorted(set(item["sources"]) | {"switch_mac_cache"})
    return items


def status(db):
    states = list(db.scalars(select(m.SwitchMacSnapshot)))
    job = db.scalar(
        select(m.Job).where(m.Job.kind == KIND).order_by(m.Job.created_at.desc(), m.Job.id.desc()).limit(1)
    )
    current_devices = {d.id: d for d in devices(db)}
    profiles = {
        p.id: p
        for p in db.scalars(
            select(m.Credential)
            .options(load_only(m.Credential.id, m.Credential.updated_at))
            .where(m.Credential.id.in_({d.snmp_credential_id for d in current_devices.values()}))
        )
    }
    healthy = sum(
        bool(
            s.healthy
            and s.observed_at
            and s.observed_at >= now() - FRESHNESS
            and s.device_id in current_devices
            and s.read_context
            == context(
                current_devices[s.device_id], profiles[current_devices[s.device_id].snmp_credential_id]
            )
        )
        for s in states
    )
    from ..services import serialize

    return {
        "schedule_times": SCHEDULE_TIMES,
        "timezone": "Europe/Istanbul",
        "switches": len(current_devices),
        "entries": sum(s.entry_count for s in states),
        "healthy": healthy,
        "last_scan": serialize(job) if job else None,
    }
