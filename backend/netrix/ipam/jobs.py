import asyncio
import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..identity.security import decrypt, secret_data
from ..monitoring.rates import calculate_rate
from ..services import authorized_device, enqueue, get, in_scope, publish
from . import adapters
from .service import (
    connection_candidates,
    normalized_mac,
    observations,
    observe,
    physical_connections,
    prefix_for,
    require_scope,
    targets,
    virtual_connections,
)

KINDS = ("ipam_ping", "ipam_discover", "integration", "ipam_live")


def validate_target(db, kind, id):
    if kind == "integration":
        row = get(db, m.Integration, id)
        if not row.enabled or not row.prefix_ids:
            raise HTTPException(422, "Entegrasyonu etkinleştirin ve yetkili ağ bloklarını seçin")
    elif kind == "ipam_live":
        row = get(db, m.IPAddress, id)
    else:
        row = get(db, m.Prefix, id)
        targets(db, row, discover=kind == "ipam_discover")
    return row


def live_options(db, row):
    virtual = virtual_connections(observations(db, [row])[row.id])
    integrations = []
    for candidate in virtual:
        config = db.get(m.Integration, candidate["integration_id"]) if candidate["integration_id"] else None
        if config and config.enabled and row.prefix_id in config.prefix_ids:
            integrations.append({**candidate, "name": config.name})
    # A VM's access port is its virtual NIC backing, not every physical FDB hop.
    return {
        "interfaces": [] if virtual else physical_connections(connection_candidates(db, row)),
        "integrations": integrations if len(virtual) == 1 else [],
        "vm_conflict": len(virtual) > 1,
    }


def live_target(db, row, selection):
    options = live_options(db, row)
    if selection.get("interface_id"):
        candidate = next(
            (v for v in options["interfaces"] if v["interface_id"] == selection["interface_id"]), None
        )
        if not candidate:
            raise HTTPException(422, "Seçilen port bu IP için güncel bağlantı adayları arasında değil")
        interface = get(db, m.Interface, candidate["interface_id"])
        device = get(db, m.Device, interface.device_id)
        authorized_device(db, device)
        if interface.is_deleted or interface.if_index is None or not device.snmp_credential_id:
            raise HTTPException(422, "Port için SNMP erişimi ve güncel ifIndex gerekli")
        return "snmp", device, interface
    candidate = next(
        (v for v in options["integrations"] if v["integration_id"] == selection.get("integration_id")), None
    )
    if not candidate:
        raise HTTPException(422, "İzlenecek switch portunu veya vCenter bağlantısını seçin")
    return "vcenter", get(db, m.Integration, candidate["integration_id"]), candidate


async def scan(job_id):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        prefix = get(db, m.Prefix, job.target_id)
        discover = job.kind == "ipam_discover"
        addresses = targets(db, prefix, discover)
        dns = db.get(m.DNSServer, prefix.dns_server_id) if prefix.dns_server_id else None
        job.total = len(addresses)
        setattr(prefix, "last_discovery_at" if discover else "last_ping_at", now())
        db.commit()
    reached = 0
    # Batches bound tasks, subprocesses and cancellation latency.
    for start in range(0, len(addresses), 8):
        batch = addresses[start : start + 8]

        async def probe(address):
            up = await adapters.ping(address)
            hostname = await adapters.reverse_dns(address, dns) if up and dns else ""
            return address, up, hostname

        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            prefix = get(db, m.Prefix, job.target_id)
            scope = require_scope(db, prefix)
            if job.cancel_requested:
                raise Cancelled()
            batch = [address for address in batch if in_scope(address, scope)]
        values = await asyncio.gather(*(probe(address) for address in batch))
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            prefix = get(db, m.Prefix, job.target_id)
            scope = require_scope(db, prefix)
            if job.cancel_requested:
                raise Cancelled()
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
                    observe(db, prefix, address, "dns", dns.id, {"hostname": hostname}, create=False)
            job.progress = min(start + 8, len(addresses))
            db.commit()
        publish()
    source_jobs = []
    if discover:
        with session_factory()() as db:
            current = get(db, m.Prefix, prefix.id)
            require_scope(db, current)
            if get(db, m.Job, job_id).cancel_requested:
                raise Cancelled()
            for device in db.scalars(
                select(m.Device).where(
                    m.Device.vrf_id == current.vrf_id,
                    m.Device.archived.is_(False),
                    m.Device.snmp_credential_id.is_not(None),
                )
            ):
                try:
                    source_jobs.append(enqueue(db, "monitor", device.id, commit=False).id)
                except HTTPException:
                    continue
            for config in db.scalars(select(m.Integration).where(m.Integration.enabled.is_(True))):
                if current.id in config.prefix_ids:
                    source_jobs.append(enqueue(db, "integration", config.id, commit=False).id)
            db.commit()
    return {
        "checked": len(addresses),
        "reachable": reached,
        "no_reply": len(addresses) - reached,
        "source_jobs": source_jobs,
    }


async def integration(job_id):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
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
        current = validate_target(db, "integration", job.target_id)
        if job.cancel_requested or current.updated_at != version:
            raise Cancelled()
        prefixes = db.scalars(select(m.Prefix).where(m.Prefix.id.in_(current.prefix_ids))).all()
        count, matched = 0, 0
        address_evidence = list(
            db.execute(
                select(m.IPAddress, m.IPObservation)
                .join(m.IPObservation, m.IPObservation.address_id == m.IPAddress.id)
                .where(
                    m.IPAddress.prefix_id.in_(current.prefix_ids),
                    m.IPObservation.source.in_(("windows_dhcp", "inventory")),
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
            prefix = prefix_for(db, entry["address"], prefixes) if entry.get("address") else None
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
                        scope = next(p for p in prefixes if p.id == address.prefix_id)
                        observed = observe(
                            db,
                            scope,
                            address.address,
                            "vcenter",
                            key,
                            {
                                **data,
                                "matched_by": "dhcp_mac" if item["dhcp"] else "inventory_mac",
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
                if set(config.prefix_ids) & set(current.prefix_ids):
                    enqueue(db, "integration", config.id, commit=False)
        current.last_success_at = now()
        job.total = job.progress = len(records)
        db.commit()
    publish()
    return {
        "observed": len(records),
        "imported": count,
        "outside_selected_prefixes": len(records) - count,
        "matched_by_mac": matched,
    }


def live_signature(db, kind, target, detail):
    if kind == "snmp":
        profile = get(db, m.Credential, target.snmp_credential_id)
        return (
            target.management_ip,
            target.snmp_port,
            profile.id,
            profile.updated_at,
            detail.id,
            detail.if_index,
            detail.is_deleted,
        )
    return (
        target.host,
        target.port,
        target.encrypted_secret,
        target.verify_tls,
        target.enabled,
        tuple(target.prefix_ids),
        detail["vm_id"],
        detail["nic_key"],
    )


async def live(job_id, collector):
    from ..worker import Cancelled

    previous, previous_time = None, None
    with session_factory()() as db:
        selection = dict(get(db, m.Job, job_id).result)
    count = 0
    for _ in range(12):
        started = asyncio.get_running_loop().time()
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested:
                raise Cancelled()
            row = get(db, m.IPAddress, job.target_id)
            kind, target, detail = live_target(db, row, selection)
            credential = get(db, m.Credential, target.snmp_credential_id) if kind == "snmp" else target
            secret = (
                secret_data(credential)
                if kind == "snmp"
                else json.loads(decrypt(credential.encrypted_secret))
            )
            signature = live_signature(db, kind, target, detail)
        if kind == "snmp":
            counters = await collector.interface_counters(
                target.management_ip, target.snmp_port, secret, detail.if_index
            )
            stamp = now()
            incoming, outgoing, _ = calculate_rate(
                previous,
                counters,
                (stamp - previous_time).total_seconds() if previous_time else 0,
                int(detail.speed_bps) if detail.speed_bps is not None else None,
            )
            sample = {
                "sampled_at": stamp,
                "interval_seconds": round((stamp - previous_time).total_seconds()) if previous_time else 5,
                "in_bps": incoming,
                "out_bps": outgoing,
            }
            previous, previous_time = counters, stamp
            source_key = "interface:" + detail.id
        else:
            sample = await asyncio.to_thread(
                adapters.vcenter_traffic, target, secret, detail["vm_id"], detail["nic_key"]
            )
            source_key = "vcenter:" + target.id + ":" + detail["vm_id"] + ":" + detail["nic_key"]
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            row = get(db, m.IPAddress, job.target_id)
            current_kind, current, current_detail = live_target(db, row, selection)
            if job.cancel_requested or live_signature(db, current_kind, current, current_detail) != signature:
                raise Cancelled()
            if sample and not db.scalar(
                select(m.IPTraffic.id).where(
                    m.IPTraffic.address_id == row.id,
                    m.IPTraffic.source_key == source_key,
                    m.IPTraffic.sampled_at == sample["sampled_at"],
                )
            ):
                db.add(m.IPTraffic(address_id=row.id, source_key=source_key, **sample))
                count += 1
            job.progress += 1
            job.total = 12
            db.commit()
        publish()
        await asyncio.sleep(max(0, 5 - (asyncio.get_running_loop().time() - started)))
    return {**selection, "samples": count}


async def execute(job_id, kind, collector):
    if kind == "integration":
        return await integration(job_id)
    if kind == "ipam_live":
        return await live(job_id, collector)
    return await scan(job_id)
