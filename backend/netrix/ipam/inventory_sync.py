"""Replay cached inventory into a new block outside the API request transaction."""

import asyncio
import ipaddress
from datetime import timedelta

from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..services import SNMP_PROTOCOLS, get, publish
from .connections import project_snapshot
from .service import normalized_mac, observe, prefix_for


def cached_records(device_id, vrf_id, cidr):
    with session_factory()() as db:
        device = db.get(m.Device, device_id)
        if not device or device.archived or device.vrf_id != vrf_id:
            return []
        record = {"address": device.management_ip, "hostname": device.name, "mac_address": ""}
        observation = db.scalar(
            select(m.Observation)
            .where(
                m.Observation.device_id == device_id,
                m.Observation.source.in_(SNMP_PROTOCOLS),
                m.Observation.created_at >= now() - timedelta(hours=24),
            )
            .order_by(m.Observation.created_at.desc(), m.Observation.id.desc())
            .limit(1)
        )
        evidence = observation.evidence if observation else {}
        name = device.name
    # Parse once before acquiring any write lock. FDB joins aren't needed to
    # import IP/MAC identity; the connection resolver handles port evidence.
    entries = [record]
    for address, values in project_snapshot(evidence)["arp"].items():
        for mac, _ in values:
            entries.append({"address": address, "mac_address": mac})
    network = ipaddress.ip_network(cidr)
    return [
        {
            **entry,
            "device_id": device_id,
            "device_name": name,
            "mac_address": normalized_mac(entry["mac_address"]),
        }
        for entry in entries
        if ipaddress.ip_address(entry["address"]) in network
    ]


def persist_batch(job_id, device_id, records, cidr, vrf_id):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        if job.cancel_requested:
            raise Cancelled()
        prefix = get(db, m.Prefix, job.target_id)
        if (prefix.cidr, prefix.vrf_id) != (cidr, vrf_id):
            raise Cancelled()
        device = db.get(m.Device, device_id)
        if not device or device.archived or device.vrf_id != vrf_id:
            return 0
        prefixes = list(db.scalars(select(m.Prefix).where(m.Prefix.vrf_id == vrf_id)))
        imported = 0
        for entry in records:
            # Respect existing, more specific blocks without touching their IPs.
            owner = prefix_for(db, entry["address"], prefixes)
            if not owner or owner.id != prefix.id:
                continue
            row = observe(
                db,
                prefix,
                entry["address"],
                "inventory",
                device_id,
                {key: value for key, value in entry.items() if key != "address"},
            )
            imported += row is not None
        db.commit()
        return imported


async def run(job_id):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        if job.cancel_requested:
            raise Cancelled()
        prefix = get(db, m.Prefix, job.target_id)
        cidr, vrf_id = prefix.cidr, prefix.vrf_id
        device_ids = list(
            db.scalars(
                select(m.Device.id)
                .where(m.Device.vrf_id == vrf_id, m.Device.archived.is_(False))
                .order_by(m.Device.id)
            )
        )
        job.total = len(device_ids)
        db.commit()
    imported = 0
    for index, device_id in enumerate(device_ids):
        records = await asyncio.to_thread(cached_records, device_id, vrf_id, cidr)
        # Small transactions let interactive saves acquire the shared VRF lock
        # between batches. Never hold it while reading/parsing all device evidence.
        for start in range(0, len(records), 8):
            imported += await asyncio.to_thread(
                persist_batch, job_id, device_id, records[start : start + 8], cidr, vrf_id
            )
        with session_factory()() as db:
            job = get(db, m.Job, job_id)
            if job.cancel_requested:
                raise Cancelled()
            job.progress = index + 1
            db.commit()
    publish()
    return {"devices": len(device_ids), "imported": imported}
