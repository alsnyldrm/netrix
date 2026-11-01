import asyncio
import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..identity.security import decrypt
from ..services import enqueue, get, in_scope, publish
from . import adapters
from .service import (
    connection_candidates,
    normalized_mac,
    observations,
    observe,
    physical_connections,
    scan_boundary,
    targets,
    virtual_connections,
    vlan_for,
)

KINDS = ("ipam_ping", "ipam_discover", "integration")
SCAN_BATCH_SIZE = 32


def validate_target(db, kind, id):
    if kind == "integration":
        row = get(db, m.Integration, id)
        if not row.enabled:
            raise HTTPException(422, "Entegrasyonu etkinleştirin")
    else:
        row = get(db, m.VLAN, id)
        targets(db, row, discover=kind == "ipam_discover")
    return row


def connection_options(db, row):
    virtual = virtual_connections(observations(db, [row])[row.id])
    integrations = []
    for candidate in virtual:
        config = db.get(m.Integration, candidate["integration_id"]) if candidate["integration_id"] else None
        if config and config.enabled:
            integrations.append({**candidate, "name": config.name})
    # A VM's access port is its virtual NIC backing, not every physical FDB hop.
    return {
        "interfaces": [] if virtual else physical_connections(connection_candidates(db, row)),
        "integrations": integrations if len(virtual) == 1 else [],
        "vm_conflict": len(virtual) > 1,
    }


async def scan(job_id):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        if job.cancel_requested:
            raise Cancelled()
        prefix = get(db, m.VLAN, job.target_id)
        discover = job.kind == "ipam_discover"
        addresses = targets(db, prefix, discover)
        dns = db.get(m.DNSServer, prefix.dns_server_id) if prefix.dns_server_id else None
        job.total = len(addresses)
        setattr(prefix, "last_discovery_at" if discover else "last_ping_at", now())
        db.commit()
    reached = 0
    # Batches bound tasks, subprocesses and cancellation latency.
    for start in range(0, len(addresses), SCAN_BATCH_SIZE):
        batch = addresses[start : start + SCAN_BATCH_SIZE]

        async def probe(address):
            up = await adapters.ping(address)
            hostname = await adapters.reverse_dns(address, dns) if up or not discover else ""
            return address, up, hostname

        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested:
                raise Cancelled()
            prefix = get(db, m.VLAN, job.target_id)
            scope = scan_boundary(db, prefix)
            batch = [address for address in batch if in_scope(address, scope)]
        values = await asyncio.gather(*(probe(address) for address in batch))
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested:
                raise Cancelled()
            prefix = get(db, m.VLAN, job.target_id)
            scope = scan_boundary(db, prefix)
            for address, up, hostname in values:
                if not in_scope(address, scope):
                    continue
                reached += int(up)
                observe(
                    db,
                    prefix,
                    address,
                    "icmp",
                    prefix.id,
                    {"reachability": "reachable" if up else "no_reply"},
                    create=up and discover,
                )
                if hostname:
                    observe(
                        db,
                        prefix,
                        address,
                        "dns",
                        dns.id if dns else "system",
                        {"hostname": hostname},
                        create=False,
                    )
            job.progress = min(start + SCAN_BATCH_SIZE, len(addresses))
            db.commit()
        publish()
    source_jobs = []
    if discover:
        with session_factory()() as db:
            if get(db, m.Job, job_id).cancel_requested:
                raise Cancelled()
            current = get(db, m.VLAN, prefix.id)
            scan_boundary(db, current)
            for config in db.scalars(select(m.Integration).where(m.Integration.enabled.is_(True))):
                source_jobs.append(enqueue(db, "integration", config.id, commit=False).id)
            db.commit()
    return {
        "checked": len(addresses),
        "reachable": reached,
        "no_reply": len(addresses) - reached,
        "source_jobs": source_jobs,
    }


async def integration(job_id, collector=None):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        if job.cancel_requested:
            raise Cancelled()
        config = validate_target(db, "integration", job.target_id)
        secret = json.loads(decrypt(config.encrypted_secret))
        config.last_run_at = now()
        db.commit()
        version = config.updated_at
    if config.kind in ("corner_switch", "backbone_switch", "firewall"):
        return await switch_records(job_id, config, version, collector)
    reader = adapters.vcenter_records if config.kind == "vcenter" else adapters.windows_dhcp
    # All remote reads finish before atomic persistence. Exceptions leave prior observations intact.
    records = await asyncio.to_thread(reader, config, secret)
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        if job.cancel_requested:
            raise Cancelled()
        current = validate_target(db, "integration", job.target_id)
        if current.updated_at != version:
            raise Cancelled()
        prefixes = db.scalars(select(m.VLAN).where(m.VLAN.cidr.is_not(None))).all()
        count, matched = 0, 0
        address_evidence = list(
            db.execute(
                select(m.IPAddress, m.IPObservation)
                .join(m.IPObservation, m.IPObservation.address_id == m.IPAddress.id)
                .where(
                    m.IPObservation.source.in_(
                        ("windows_dhcp", "corner_switch", "backbone_switch", "firewall")
                    ),
                    m.IPObservation.observed_at >= now() - timedelta(hours=24),
                )
            )
        )
        known = {}
        seen = set()
        for address, evidence in address_evidence:
            if not evidence.data.get("present", True):
                continue
            mac = normalized_mac(evidence.data.get("mac_address"))
            if mac:
                item = known.setdefault(address.id, {"row": address, "macs": set(), "dhcp": False})
                item["macs"].add(mac)
                item["dhcp"] |= evidence.source == "windows_dhcp"
        mac_owners = {}
        if current.kind == "vcenter":
            for entry in records:
                mac = normalized_mac(entry.get("mac_address"))
                mac_owners.setdefault(mac, set()).add((entry["vm_id"], entry["nic_key"]))
        for entry in records:
            prefix = vlan_for(db, entry["address"], prefixes) if entry.get("address") else None
            key = current.id + (
                ":" + entry["vm_id"] + ":" + entry["nic_key"] if current.kind == "vcenter" else ""
            )
            data = {k: v for k, v in entry.items() if k != "address"}
            data["integration_id"] = current.id
            observed = observe(db, prefix, entry["address"], current.kind, key, data) if prefix else None
            if observed:
                seen.add((observed.id, key))
                count += 1
            mac = normalized_mac(entry.get("mac_address"))
            if current.kind == "vcenter" and mac and len(mac_owners.get(mac, ())) == 1:
                for item in known.values():
                    address = item["row"]
                    if address.address != entry.get("address") and item["macs"] == {mac}:
                        scope = next(p for p in prefixes if p.id == address.vlan_id)
                        observed = observe(
                            db,
                            scope,
                            address.address,
                            "vcenter",
                            key,
                            {
                                **data,
                                "matched_by": "dhcp_mac" if item["dhcp"] else "switch_mac",
                                "guest_address": entry.get("address", ""),
                            },
                            create=False,
                        )
                        if observed:
                            seen.add((observed.id, key))
                            matched += 1
        if current.kind in ("vcenter", "windows_dhcp"):
            # Retire disappeared IP/NIC associations only after a complete, successful snapshot.
            # Keep their evidence/history, but never use it as a current attachment.
            for old in db.scalars(
                select(m.IPObservation).where(
                    m.IPObservation.source == current.kind,
                    m.IPObservation.source_key.startswith(current.id + ":")
                    if current.kind == "vcenter"
                    else m.IPObservation.source_key == current.id,
                )
            ):
                if (old.address_id, old.source_key) not in seen and old.data.get("present", True):
                    db.add(
                        m.Event(
                            kind="ip_observation_change",
                            message=f"{current.name}: adres bağlantısı artık gözlemlenmiyor",
                            details={
                                "address_id": old.address_id,
                                "source": current.kind,
                                "previous": old.data,
                            },
                        )
                    )
                    old.data = {**old.data, "present": False}
                    old.observed_at = now()
        if current.kind == "windows_dhcp":
            # Refresh VM information after reservations exist, using already enabled integrations only.
            for config in db.scalars(
                select(m.Integration).where(m.Integration.kind == "vcenter", m.Integration.enabled.is_(True))
            ):
                enqueue(db, "integration", config.id, commit=False)
        current.last_success_at = now()
        for vlan in prefixes:
            if vlan.scan_authorized:
                enqueue(db, "ipam_ping", vlan.id, commit=False)
        job.total = job.progress = len(records)
        db.commit()
    publish()
    return {
        "observed": len(records),
        "imported": count,
        "outside_vlans": len(records) - count,
        "matched_by_mac": matched,
    }


async def execute(job_id, kind, collector):
    if kind == "integration":
        return await integration(job_id, collector)
    return await scan(job_id)


async def switch_records(job_id, config, version, collector):
    from ..discovery.protocols import SNMPCollector
    from ..worker import Cancelled
    from .connections import project_snapshot

    with session_factory()() as db:
        profile = get(db, m.Credential, config.credential_id)
        secret = json.loads(decrypt(profile.encrypted_secret))
        secret["protocol"] = profile.protocol
        profile_version = profile.updated_at
    evidence = await (collector or SNMPCollector()).collect(config.host, config.port, secret)
    with session_factory()() as db:
        current = validate_target(db, "integration", config.id)
        profile = get(db, m.Credential, current.credential_id)
        job = get(db, m.Job, job_id)
        if job.cancel_requested or current.updated_at != version or profile.updated_at != profile_version:
            raise Cancelled()
        vlans = list(db.scalars(select(m.VLAN).where(m.VLAN.cidr.is_not(None))))
        imported = 0
        for address, entries in project_snapshot(evidence)["arp"].items():
            vlan = vlan_for(db, address, vlans)
            if not vlan:
                continue
            for mac, index in entries:
                if observe(
                    db,
                    vlan,
                    address,
                    current.kind,
                    current.id,
                    {"mac_address": mac, "integration_id": current.id, "switch_name": current.name},
                ):
                    imported += 1
        for vlan in vlans:
            if vlan.scan_authorized:
                enqueue(db, "ipam_ping", vlan.id, commit=False)
        current.evidence = evidence
        current.last_success_at = now()
        job.total = job.progress = imported
        db.commit()
    publish()
    return {"imported": imported}
