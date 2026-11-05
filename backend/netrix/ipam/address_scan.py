"""Explicit one-address scans. Every result is scoped to the original address ID/VRF/VLAN."""

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..runtime_limits import sql_read, sql_write
from ..services import in_scope, lock_vrf, publish
from .service import hostname_vm_records, normalized_hostname, normalized_mac, observe, scan_boundary

NETWORK_SOURCE = "address_network"


def target(db, job, *, lock=False):
    from ..worker import Cancelled

    row = db.get(m.IPAddress, job.target_id)
    if row and lock:
        lock_vrf(db, row.vrf_id)
        row = db.scalar(
            select(m.IPAddress)
            .where(m.IPAddress.id == job.target_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if (
        job.cancel_requested
        or not row
        or job.result.get("address_scope") != [row.address, row.vrf_id, row.vlan_id]
    ):
        raise Cancelled()
    vlan = db.get(m.VLAN, row.vlan_id)
    try:
        if not vlan or vlan.vrf_id != row.vrf_id or not in_scope(row.address, scan_boundary(db, vlan)):
            raise Cancelled()
    except HTTPException:
        raise Cancelled() from None
    return row, vlan


def phase(job_id, name, **values):
    with session_factory()() as db:
        job = db.get(m.Job, job_id)
        row, _ = target(db, job, lock=True)
        job.result = {**job.result, **values, "scan_phase": name}
        db.commit()
        vlan_id = row.vlan_id
    publish(ipam_vlan=vlan_id)


def compact_network(data, address):
    """Scope ARP/NDP to this IP; keep complete FDB populations for safe uplink rejection."""
    import ipaddress

    data = {**data, "tables": {k: dict(v) for k, v in data.get("tables", {}).items()}}
    tables = data["tables"]
    suffix = "." + ".".join(str(b) for b in ipaddress.ip_address(address).packed)
    for prefix in ("arp", "ndp"):
        keys = {k for k in tables.get(prefix + "_mac", {}) if k.endswith(suffix)}
        for key in tuple(tables):
            if key.startswith(prefix + "_"):
                tables[key] = {k: v for k, v in tables[key].items() if k in keys}
    return data


def save_network(db, job, device, context, evidence):
    row, _ = target(db, job, lock=True)
    item = db.scalar(
        select(m.IPObservation).where(
            m.IPObservation.address_id == row.id,
            m.IPObservation.source == NETWORK_SOURCE,
            m.IPObservation.source_key == device.id,
        )
    )
    if item is None:
        item = m.IPObservation(address_id=row.id, source=NETWORK_SOURCE, source_key=device.id)
        db.add(item)
    at = now()
    snapshot = db.scalar(
        select(m.Observation).where(
            m.Observation.job_id == job.id,
            m.Observation.device_id == device.id,
            m.Observation.source == NETWORK_SOURCE,
        )
    )
    if snapshot is None:
        snapshot = m.Observation(
            job_id=job.id, device_id=device.id, address=device.management_ip, source=NETWORK_SOURCE
        )
        db.add(snapshot)
    snapshot.evidence, snapshot.created_at = compact_network(evidence, row.address), at
    db.flush()
    item.data = {
        "address_scope": job.result["address_scope"],
        "device_address": device.management_ip,
        "read_context": context,
        "observation_id": snapshot.id,
    }
    item.observed_at = at


def persist_integration(db, row, vlan, config, records):
    """Reuse source keys and identity rules, but never import/retire another IP's NICs."""
    from .connections import Evidence
    from .service import dns_hostname, observations

    obs = observations(db, [row])[row.id]
    evidence = Evidence(db, {row.vrf_id}).for_address(db, row, obs)
    physical = evidence.resolve(row, vlan)
    mac = physical["mac_address"] if not physical["mac_conflict"] else ""
    hostname = dns_hostname(obs, vlan)
    chosen = []
    if config.kind == "windows_dhcp":
        chosen = [r for r in records if r.get("address") == row.address]
    else:
        owners = defaultdict(set)
        for record in records:
            if record.get("record_type") != "host":
                owners[normalized_mac(record.get("mac_address"))].add((record["vm_id"], record["nic_key"]))
        named = hostname_vm_records(
            [
                r
                for r in records
                if r.get("record_type") != "host"
                and normalized_hostname(r.get("hostname")) == normalized_hostname(hostname)
            ],
            hostname,
            row.address,
            mac,
        )
        named_ids = {(r["vm_id"], r["nic_key"]) for r in named}
        for record in records:
            direct = record.get("address") == row.address
            if record.get("record_type") == "host":
                if direct:
                    chosen.append(record)
                continue
            identity = (record["vm_id"], record["nic_key"])
            if (
                direct
                or (mac and normalized_mac(record.get("mac_address")) == mac and len(owners[mac]) == 1)
                or identity in named_ids
            ):
                chosen.append(record)
    unique = {}
    for record in chosen:
        identity = (
            (record.get("host_id"), record.get("vmkernel_device"))
            if record.get("record_type") == "host"
            else (record.get("vm_id"), record.get("nic_key"))
        )
        if identity not in unique or record.get("address") == row.address:
            unique[identity] = record
    seen = set()
    for record in unique.values():
        key = config.id
        data = {k: v for k, v in record.items() if k != "address"}
        data["integration_id"] = config.id
        if config.kind == "vcenter":
            key += (
                ":host:" + record["host_id"] + ":" + record["vmkernel_device"]
                if record.get("record_type") == "host"
                else ":" + record["vm_id"] + ":" + record["nic_key"]
            )
            data["guest_address"] = record.get("address", "")
            if record.get("address") != row.address:
                data["matched_by"] = (
                    "gateway_mac"
                    if mac and normalized_mac(record.get("mac_address")) == mac
                    else "dns_hostname"
                )
        observe(db, vlan, row.address, config.kind, key, data, create=False)
        seen.add(key)
    for old in db.scalars(
        select(m.IPObservation).where(
            m.IPObservation.address_id == row.id,
            m.IPObservation.source == config.kind,
            m.IPObservation.source_key.startswith(config.id + ":")
            if config.kind == "vcenter"
            else m.IPObservation.source_key == config.id,
        )
    ):
        if old.source_key not in seen:
            old.data = {**old.data, "present": False}
            old.observed_at = now()
    return len(seen)


async def execute(job_id, collector):
    from . import pipeline
    from .sql_sources import SQLContext

    started = now()

    def prepare():
        # Read-only and slow: never keep this snapshot open across a job row write.
        with session_factory()() as db:
            job = db.get(m.Job, job_id)
            row, vlan = target(db, job)
            return vlan.id, SQLContext(db, vlan, job_id).for_row(row)

    vlan_id, sources = await sql_read(prepare)

    def begin():
        with session_factory()() as db:
            job = db.get(m.Job, job_id)
            target(db, job)
            job.total, job.progress = 1, 0
            db.commit()

    await sql_write(begin)

    async def progress(name):
        await sql_write(phase, job_id, name)

    result = await sources.resolve(progress)

    def save():
        with session_factory()() as db:
            job = db.get(m.Job, job_id)
            row, _ = target(db, job, lock=True)
            pipeline.save_result(db, row, started, result)
            job.progress = 1
            db.commit()

    await sql_write(save)
    publish(ipam_vlan=vlan_id)
    await sql_write(
        phase, job_id, "complete", resolution_status=result["status"], source_errors=result["issues"]
    )
    return {
        "checked": 1,
        "network": {"mode": "sql", "devices": 0},
        "source_failed": int(result["status"] == "problem"),
        "source_errors": result["issues"],
        "resolution_status": result["status"],
    }
