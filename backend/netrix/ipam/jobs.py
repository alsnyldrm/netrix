import asyncio
import json
import time
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from .. import models as m
from ..core import now, session_factory
from ..identity.security import decrypt
from ..services import enqueue, get, in_scope, publish
from . import adapters
from .service import (
    dns_hostname,
    hostname_vm_records,
    normalized_hostname,
    normalized_mac,
    observations,
    observe,
    scan_boundary,
    targets,
    virtual_connections,
    vlan_for,
    vmware_observations,
)

KINDS = ("ipam_ping", "ipam_discover", "integration")
SCAN_BATCH_SIZE = 32
SOURCE_WAIT_SECONDS = 900


def scan_phase(job_id, phase, **result):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        if job.cancel_requested or not db.get(m.VLAN, job.target_id):
            raise Cancelled()
        job.result = {**job.result, **result, "scan_phase": phase}
        db.commit()
    publish()


async def wait_for_sources(job_id, ids):
    """Dependency jobs use reserved worker slots; the parent never finishes early."""
    from ..worker import Cancelled

    deadline = time.monotonic() + SOURCE_WAIT_SECONDS
    while True:
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested or not db.get(m.VLAN, job.target_id):
                raise Cancelled()
            sources = {j.id: j.status for j in db.scalars(select(m.Job).where(m.Job.id.in_(ids)))}
        if all(sources.get(id) not in ("queued", "running") for id in ids):
            return {id: sources.get(id, "missing") for id in ids}
        if time.monotonic() >= deadline:
            return {
                id: status if status not in ("queued", "running") else "timeout"
                for id, status in sources.items()
            }
        await asyncio.sleep(0.5)


async def complete_dns(job_id, started_at):
    """Resolve newly imported/ICMP-silent IPs before matching is reported complete."""
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        vlan = get(db, m.VLAN, job.target_id)
        dns = db.get(m.DNSServer, vlan.dns_server_id) if vlan.dns_server_id else None
        addresses = list(
            db.scalars(
                select(m.IPAddress.address)
                .outerjoin(
                    m.IPObservation,
                    and_(
                        m.IPObservation.address_id == m.IPAddress.id,
                        m.IPObservation.source == "dns",
                        m.IPObservation.source_key == (vlan.dns_server_id or "system"),
                    ),
                )
                .where(
                    m.IPAddress.vlan_id == vlan.id,
                    or_(m.IPObservation.id.is_(None), m.IPObservation.observed_at < started_at),
                )
            )
        )
    for start in range(0, len(addresses), SCAN_BATCH_SIZE):
        batch = addresses[start : start + SCAN_BATCH_SIZE]
        values = await asyncio.gather(*(adapters.reverse_dns(address, dns) for address in batch))
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested:
                raise Cancelled()
            vlan = get(db, m.VLAN, job.target_id)
            # A DNS selection changed during the scan: do not attach the old answer.
            if vlan.dns_server_id != (dns.id if dns else None):
                raise Cancelled()
            for address, hostname in zip(batch, values):
                observe(
                    db,
                    vlan,
                    address,
                    "dns",
                    dns.id if dns else "system",
                    {"hostname": hostname, "present": bool(hostname)},
                    create=False,
                )
            db.commit()
        publish()
    return len(addresses)


def validate_target(db, kind, id):
    if kind == "integration":
        row = get(db, m.Integration, id)
        if row.kind not in ("vcenter", "windows_dhcp"):
            raise HTTPException(422, "Yalnızca DHCP ve VMware entegrasyonları desteklenir")
        if not row.enabled:
            raise HTTPException(422, "Entegrasyonu etkinleştirin")
    else:
        row = get(db, m.VLAN, id)
        targets(db, row, discover=kind == "ipam_discover")
    return row


def connection_options(db, row, *, obs=None):
    if obs is None:
        from .connections import Evidence

        obs = observations(db, [row])[row.id]
        vlan = get(db, m.VLAN, row.vlan_id)
        physical = Evidence(db, {row.vrf_id}).resolve(row, vlan)
        obs, _ = vmware_observations(obs, dns_hostname(obs, vlan), row.address, physical)
    virtual = virtual_connections(obs)
    integrations = []
    for candidate in virtual:
        config = (
            db.execute(
                select(m.Integration.name, m.Integration.enabled).where(
                    m.Integration.id == candidate["integration_id"]
                )
            ).first()
            if candidate["integration_id"]
            else None
        )
        if config and config.enabled:
            integrations.append({**candidate, "name": config.name})
    # A VM's access port is its virtual NIC backing, not every physical FDB hop.
    return {
        "interfaces": [],
        "integrations": integrations if len(virtual) == 1 else [],
        "vm_conflict": len(virtual) > 1,
    }


async def scan(job_id, collector=None):
    from ..worker import Cancelled

    started_at = now()
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
    if discover:
        scan_phase(job_id, "addresses")
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
                if hostname or up or not discover:
                    observe(
                        db,
                        prefix,
                        address,
                        "dns",
                        dns.id if dns else "system",
                        {"hostname": hostname, "present": bool(hostname)},
                        create=False,
                    )
            job.progress = min(start + SCAN_BATCH_SIZE, len(addresses))
            db.commit()
        publish()
    source_jobs = []
    followup_ids = []
    network_result = None
    source_statuses = {}
    matching = None
    if discover:
        from ..discovery.protocols import SNMPCollector
        from .network import refresh

        scan_phase(job_id, "network")
        network_result = await refresh(job_id, collector or SNMPCollector())
        # DHCP must finish before VMware starts, including NICs without guest IPs.
        for kind, phase in (("windows_dhcp", "dhcp"), ("vcenter", "vmware")):
            with session_factory()() as db:
                if get(db, m.Job, job_id).cancel_requested:
                    raise Cancelled()
                current = get(db, m.VLAN, prefix.id)
                scan_boundary(db, current)
                followups = {
                    j.target_id: j for j in db.scalars(select(m.Job).where(m.Job.id.in_(followup_ids)))
                }
                ids = [
                    (followups.get(config.id) or enqueue(db, "integration", config.id, commit=False)).id
                    for config in db.scalars(
                        select(m.Integration).where(
                            m.Integration.enabled.is_(True), m.Integration.kind == kind
                        )
                    )
                ]
                source_jobs.extend(ids)
                db.commit()
            scan_phase(job_id, phase, network=network_result, source_jobs=source_jobs)
            source_statuses.update(await wait_for_sources(job_id, ids))
            with session_factory()() as db:
                followup_ids = [
                    child
                    for source in db.scalars(select(m.Job).where(m.Job.id.in_(ids)))
                    for child in source.result.get("source_jobs", [])
                ]
        scan_phase(job_id, "dns", source_statuses=source_statuses)
        await complete_dns(job_id, started_at)
        scan_phase(job_id, "matching")
        from .service import enrich

        with session_factory()() as db:
            rows = enrich(
                db,
                list(db.scalars(select(m.IPAddress).where(m.IPAddress.vlan_id == prefix.id))),
                details=False,
            )
            matching = {
                field: sum(bool(r.get(field)) for r in rows)
                for field in (
                    "hostname",
                    "mac_address",
                    "connected_device",
                    "connected_port",
                    "operating_system",
                )
            }
            matching.update(addresses=len(rows), ambiguous=sum(bool(r["connection_ambiguous"]) for r in rows))
        scan_phase(job_id, "complete", matching=matching)
    return {
        "checked": len(addresses),
        "reachable": reached,
        "no_reply": len(addresses) - reached,
        "source_jobs": source_jobs,
        "network": network_result,
        "source_statuses": source_statuses,
        "source_failed": sum(status != "succeeded" for status in source_statuses.values()),
        "matching": matching,
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
                    m.IPObservation.source.in_(("windows_dhcp", "dns")),
                    m.IPObservation.observed_at >= now() - timedelta(hours=24),
                )
            )
        )
        known = {}
        dns = {}
        seen = set()
        for address, evidence in address_evidence:
            if evidence.source == "dns":
                dns.setdefault(address.id, []).append(evidence)
                continue
            if not evidence.data.get("present", True):
                continue
            mac = normalized_mac(evidence.data.get("mac_address"))
            if mac:
                item = known.setdefault(address.id, {"row": address, "macs": set()})
                item["macs"].add(mac)
                item["matched_by"] = "dhcp_mac"
        mac_owners = {}
        gateway_macs = {}
        named_records = {}
        ip_rows = []
        if current.kind == "vcenter":
            from .connections import Evidence

            # A VM without guest tools/IP can still be identified by the gateway
            # MAC. A conflicting gateway identity vetoes a stale DHCP binding.
            network = Evidence(db, {p.vrf_id for p in prefixes})
            vlans = {p.id: p for p in prefixes}
            ip_rows = list(db.scalars(select(m.IPAddress).where(m.IPAddress.vlan_id.in_(vlans))))
            for address in ip_rows:
                identity = network.resolve(address, vlans[address.vlan_id])
                gateway_macs[address.id] = identity["mac_address"]
                if identity["mac_conflict"]:
                    known.pop(address.id, None)
                elif identity["mac_address"]:
                    known[address.id] = {
                        "row": address,
                        "macs": {identity["mac_address"]},
                        "matched_by": "gateway_mac",
                    }
            for entry in records:
                mac = normalized_mac(entry.get("mac_address"))
                mac_owners.setdefault(mac, set()).add((entry["vm_id"], entry["nic_key"]))
                named_records.setdefault(normalized_hostname(entry.get("hostname")), []).append(entry)
        for entry in records:
            prefix = vlan_for(db, entry["address"], prefixes) if entry.get("address") else None
            key = current.id + (
                ":" + entry["vm_id"] + ":" + entry["nic_key"] if current.kind == "vcenter" else ""
            )
            data = {k: v for k, v in entry.items() if k != "address"}
            data["integration_id"] = current.id
            if current.kind == "vcenter":
                data["guest_address"] = entry.get("address", "")
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
                                "matched_by": item["matched_by"],
                                "guest_address": entry.get("address", ""),
                            },
                            create=False,
                        )
                        if observed:
                            seen.add((observed.id, key))
                            matched += 1
        for address in ip_rows:
            scope = vlans[address.vlan_id]
            hostname = dns_hostname(dns.get(address.id, []), scope)
            chosen = hostname_vm_records(
                named_records.get(normalized_hostname(hostname), []),
                hostname,
                address.address,
                gateway_macs.get(address.id, ""),
            )
            if not chosen:
                continue
            entry = next((d for d in chosen if d.get("address") == address.address), chosen[0])
            key = current.id + ":" + entry["vm_id"] + ":" + entry["nic_key"]
            binding = {}
            if entry.get("address") != address.address:
                prior = known.get(address.id, {})
                binding["matched_by"] = (
                    prior["matched_by"]
                    if prior.get("macs") == {normalized_mac(entry.get("mac_address"))}
                    else "dns_hostname"
                )
            observed = observe(
                db,
                scope,
                address.address,
                "vcenter",
                key,
                {
                    **{k: v for k, v in entry.items() if k != "address"},
                    "integration_id": current.id,
                    "guest_address": entry.get("address", ""),
                    **binding,
                },
                create=False,
            )
            if observed:
                seen.add((observed.id, key))
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
        source_jobs = []
        if current.kind == "windows_dhcp":
            # Refresh VM information after reservations exist, using already enabled integrations only.
            for config in db.scalars(
                select(m.Integration).where(m.Integration.kind == "vcenter", m.Integration.enabled.is_(True))
            ):
                source_jobs.append(enqueue(db, "integration", config.id, commit=False).id)
        current.last_success_at = now()
        for vlan in prefixes:
            enqueue(db, "ipam_ping", vlan.id, commit=False)
        job.total = job.progress = len(records)
        db.commit()
    publish()
    return {
        "observed": len(records),
        "imported": count,
        "outside_vlans": len(records) - count,
        "matched_by_mac": matched,
        "source_jobs": source_jobs,
    }


async def execute(job_id, kind, collector):
    if kind == "integration":
        return await integration(job_id, collector)
    return await scan(job_id, collector)
