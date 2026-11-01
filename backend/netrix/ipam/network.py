"""Bounded worker-only network evidence reads, separate from inventory discovery."""

import asyncio

from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..discovery.protocols import NetworkError
from ..identity.security import secret_data
from ..services import get
from .connections import network_device


async def refresh(job_id, collector):
    from ..worker import Cancelled

    with session_factory()() as db:
        job = get(db, m.Job, job_id)
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
                .order_by(m.Device.id)
            )
        )
        ids = [d.id for d in devices if network_device(d)]
    semaphore = asyncio.Semaphore(4)

    async def read(id):
        async with semaphore:
            with session_factory()() as db:
                job = get(db, m.Job, job_id)
                if job.cancel_requested or not db.get(m.VLAN, job.target_id):
                    raise Cancelled()
                device = get(db, m.Device, id)
                if device.archived or not device.discovery_scope_id or device.lifecycle_status != "active":
                    return False
                profile = get(db, m.Credential, device.snmp_credential_id)
                version = (
                    device.management_ip,
                    device.snmp_port,
                    device.vrf_id,
                    profile.id,
                    profile.updated_at,
                )
                secret = secret_data(profile)
            try:
                async with asyncio.timeout(185):
                    data = await collector.ipam(device.management_ip, device.snmp_port, secret)
                success = True
            except (TimeoutError, OSError, NetworkError) as exc:
                # No raw protocol errors or credentials in persisted/public data.
                data = {"failed": True, "error_class": type(exc).__name__}
                success = False
            with session_factory()() as db:
                job = get(db, m.Job, job_id)
                if job.cancel_requested or not db.get(m.VLAN, job.target_id):
                    raise Cancelled()
                current = get(db, m.Device, id)
                profile = db.get(m.Credential, current.snmp_credential_id)
                if (
                    not profile
                    or version
                    != (
                        current.management_ip,
                        current.snmp_port,
                        current.vrf_id,
                        profile.id,
                        profile.updated_at,
                    )
                    or current.archived
                    or not current.discovery_scope_id
                    or current.lifecycle_status != "active"
                ):
                    raise Cancelled()
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
                observation.evidence = data
                observation.created_at = now()
                db.commit()
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
