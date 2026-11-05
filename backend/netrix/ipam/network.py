"""Bounded worker-only network evidence reads, separate from inventory discovery."""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..discovery.neighbor_detail import AOS_SWITCH, enrich_neighbors
from ..discovery.protocols import NetworkError, fetch_neighbor_detail
from ..identity.security import secret_data
from ..runtime_limits import device_slot
from ..services import get, publish
from .connections import network_device


def detail_profile(db, device):
    profile = (
        db.get(m.Credential, device.config_credential_id)
        if device.adapter in AOS_SWITCH and device.config_credential_id
        else None
    )
    return profile if profile and profile.protocol == "ssh" else None


def read_context(device, profile, ssh):
    return [
        device.management_ip,
        device.snmp_port,
        device.vrf_id,
        profile.id,
        profile.updated_at.isoformat(),
        device.adapter,
        device.config_port,
        device.ssh_trust_host_key,
        ssh.id if ssh else None,
        ssh.updated_at.isoformat() if ssh else None,
    ]


async def refresh(job_id, collector, *, detail_reader=None, address_id=None):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        if address_id:
            from .address_scan import target

            _, vlan = target(db, job)
        else:
            vlan = get(db, m.VLAN, job.target_id)
        devices = list(
            db.scalars(
                select(m.Device)
                .where(
                    m.Device.vrf_id == vlan.vrf_id,
                    m.Device.archived.is_(False),
                    m.Device.discovery_scope_id.is_not(None),
                    m.Device.lifecycle_status == "active",
                    m.Device.snmp_credential_id.is_not(None),
                )
                # Read identity gateways and detailed protocol sources early.
                # Resolution still considers every source, never this order.
                .order_by(
                    m.Device.is_gateway.desc(),
                    m.Device.adapter.in_(AOS_SWITCH).desc(),
                    m.Device.management_ip,
                    m.Device.id,
                )
            )
        )
        ids = [d.id for d in devices if network_device(d)]

    async def read(id):
        async with device_slot():
            with session_factory()() as db:
                job = get(db, m.Job, job_id)
                if address_id:
                    target(db, job)
                if job.cancel_requested or not db.get(m.VLAN, vlan.id):
                    raise Cancelled()
                device = get(db, m.Device, id)
                if device.archived or not device.discovery_scope_id or device.lifecycle_status != "active":
                    return False
                profile = get(db, m.Credential, device.snmp_credential_id)
                ssh = detail_profile(db, device)
                context = read_context(device, profile, ssh)
                completed = db.scalar(
                    select(m.Observation).where(
                        m.Observation.job_id == job.id,
                        m.Observation.device_id == id,
                        m.Observation.address == device.management_ip,
                        m.Observation.source == "ipam_network",
                    )
                )
                lifetime = timedelta(seconds=max(300, min(vlan.discovery_interval * 2, 86400)))
                if (
                    not address_id
                    and completed
                    and not completed.evidence.get("failed")
                    and not completed.evidence.get("neighbor_detail_failed")
                    and completed.created_at >= now() - lifetime
                ):
                    previous = completed.evidence.get("read_context")
                    # Earlier successful records lack the marker. Their creation
                    # time must prove that no device/profile edits followed.
                    compatible = (
                        previous == context
                        if previous
                        else completed.created_at
                        >= max(device.updated_at, profile.updated_at, *([ssh.updated_at] if ssh else []))
                    )
                    if compatible:
                        return True
                secret = secret_data(profile)
                ssh_secret = secret_data(ssh) if ssh else None
            try:
                async with asyncio.timeout(185):
                    data = await collector.ipam(device.management_ip, device.snmp_port, secret)
                    if ssh_secret:
                        try:
                            detail = await (detail_reader or fetch_neighbor_detail)(device, ssh_secret)
                            data = enrich_neighbors(data, detail)
                        except Exception as exc:
                            # Optional SSH must not discard valid SNMP facts or
                            # leak raw authentication/CLI errors. Cancellation propagates.
                            data["neighbor_detail_failed"] = type(exc).__name__
                success = not data.get("neighbor_detail_failed")
            except (TimeoutError, OSError, NetworkError) as exc:
                # No raw protocol errors or credentials in persisted/public data.
                data = {"failed": True, "error_class": type(exc).__name__}
                success = False
            with session_factory()() as db:
                job = get(db, m.Job, job_id)
                if address_id:
                    target(db, job)
                if job.cancel_requested or not db.get(m.VLAN, vlan.id):
                    raise Cancelled()
                current = get(db, m.Device, id)
                profile = db.get(m.Credential, current.snmp_credential_id)
                if (
                    not profile
                    or context != read_context(current, profile, detail_profile(db, current))
                    or current.archived
                    or not current.discovery_scope_id
                    or current.lifecycle_status != "active"
                ):
                    raise Cancelled()
                if address_id:
                    from .address_scan import save_network

                    save_network(db, job, current, context, data)
                else:
                    observation = db.scalar(
                        select(m.Observation).where(
                            m.Observation.job_id == job.id, m.Observation.address == current.management_ip
                        )
                    )
                    if not observation:
                        observation = m.Observation(
                            job_id=job.id, device_id=id, address=current.management_ip, source="ipam_network"
                        )
                        db.add(observation)
                    observation.evidence = {**data, "read_context": context}
                    observation.created_at = now()
                db.commit()
            publish(ipam_vlan=vlan.id)
            return success

    tasks = [asyncio.create_task(read(id)) for id in ids]
    try:
        results = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {"devices": len(results), "read": sum(results), "failed": len(results) - sum(results)}
