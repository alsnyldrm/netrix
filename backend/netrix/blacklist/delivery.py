"""Durable submissions and per-device worker execution for explicit send actions."""

import asyncio
import re
from ipaddress import ip_address

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory, settings
from ..identity.permissions import can_operate
from ..identity.security import audit, secret_data
from ..runtime_limits import device_slot, sql_quick
from ..services import connection_profile, get, publish
from . import adapters, state
from .cli import ACLError, connect
from .service import ACLProfile, GroupInput, device_family, eligible_inventory

ACTIVE_KEY = "blacklist_send:"


def endpoint(device):
    return [
        device.management_ip,
        device.adapter,
        device.config_port,
        device.config_credential_id,
        device.ssh_trust_host_key,
    ]


def enqueue(db, user, device_ids, *, entry_id=None, reason="entry", strict=True):
    """Queue one sync job per device. An active job of the same device is reused:
    it reads the desired state again before finishing.

    strict=False skips devices that cannot be synced and reports them instead."""
    device_ids = sorted(set(device_ids))
    jobs, skipped = [], []
    desired = state.desired_state(db, device_ids) if device_ids else {}
    recorded = state.states(db, device_ids) if device_ids else {}

    def refuse(device, status, message):
        if strict:
            raise HTTPException(status, message)
        skipped.append({"device_id": device.id if device else None, "name": device.name if device else "", "reason": message})

    for device_id in device_ids:
        item = desired.get(device_id)
        if item is None:
            continue
        device = db.scalar(select(m.Device).where(m.Device.id == device_id).with_for_update())
        if item.issue:
            refuse(device, 422, f"{device.name if device else 'Cihaz'} · {item.issue}")
            continue
        if not item.addresses and device_id not in recorded:
            continue  # Nothing was ever written and nothing is wanted.
        if not device or not connection_profile(db, device, "ssh"):
            refuse(device, 422, f"{device.name if device else 'Cihaz'} için SSH erişim profili gerekli.")
            continue
        if db.scalar(
            select(m.FirmwareTarget.id).where(
                m.FirmwareTarget.active_device == device_id,
                m.FirmwareTarget.status == "running",
            )
        ):
            refuse(device, 409, f"{device.name} cihazında firmware işlemi sürüyor.")
            continue
        active = db.scalar(select(m.Job).where(m.Job.active_key == ACTIVE_KEY + device_id))
        if active:
            jobs.append(active)
            continue
        job = m.Job(
            kind="blacklist_send",
            target_id=device_id,
            active_key=ACTIVE_KEY + device_id,
            requested_by=user.id if user else None,
            total=1,
            result={"phase": "queued", "reason": reason},
        )
        db.add(job)
        db.flush()
        db.add(
            m.BlacklistDelivery(
                entry_id=entry_id,
                device_id=device_id,
                job_id=job.id,
                payload={"endpoint": endpoint(device), "reason": reason},
            )
        )
        audit(db, user, "enqueue", "jobs", job.id, f"Kara Liste eşitlemesi kuyruğa alındı · {device.name}")
        jobs.append(job)
    return {"job_ids": [job.id for job in jobs], "devices": len(jobs), "skipped": skipped}


def latest_jobs(db, device_ids=None):
    query = (
        select(m.BlacklistDelivery.device_id, m.Job)
        .join(m.Job, m.Job.id == m.BlacklistDelivery.job_id)
        .order_by(m.Job.created_at.desc(), m.Job.id.desc())
    )
    if device_ids is not None:
        query = query.where(m.BlacklistDelivery.device_id.in_(device_ids))
    result = {}
    for device_id, job in db.execute(query):
        result.setdefault(device_id, job)
    return result


def job_view(job):
    if job is None:
        return None
    return {
        "job_id": job.id,
        "status": job.status,
        "phase": job.result.get("phase", ""),
        "error": job.error,
        "ports": job.result.get("ports", []),
        "added": job.result.get("added", []),
        "removed": job.result.get("removed", []),
        "acl_removed": bool(job.result.get("acl_removed")),
        "finished_at": job.finished_at,
        "cancel_requested": job.cancel_requested,
    }


def load_context(job_id):
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        submission = db.scalar(select(m.BlacklistDelivery).where(m.BlacklistDelivery.job_id == job_id))
        if job.cancel_requested:
            raise ACLError("Gönderim durduruldu.")
        user = db.get(m.User, job.requested_by) if job.requested_by else None
        if not submission or not user or not user.is_active or not can_operate(user):
            raise ACLError("Gönderimi başlatan kullanıcının yetkisi artık geçerli değil.")
        device = db.scalar(eligible_inventory().where(m.Device.id == submission.device_id))
        if not device or not device_family(device) or endpoint(device) != submission.payload["endpoint"]:
            raise ACLError("Cihazın uygunluğu veya SSH hedefi değişti. Kaydı kontrol edip yeniden gönderin.")
        target = desired_target(db, device)
        if target["profile"] is None and not target["stale_profiles"]:
            raise ACLError("Cihazda kaldırılacak veya uygulanacak NETRIX ACL kaydı yok.")
        credential = connection_profile(db, device, "ssh")
        if not credential:
            raise ACLError("Cihazın kayıtlı SSH profili bulunamadı.")
        secret = secret_data(credential)
        db.expunge(device)
        return device, secret, target


def desired_target(db, device):
    item = state.desired_state(db, [device.id]).get(device.id) or state.Desired(device.id, device_family(device))
    if item.issue:
        raise ACLError(item.issue)
    family = device_family(device)
    if item.profile:
        # Reapply the complete family contract, including numeric ranges and identifier safety.
        GroupInput(name="validation", device_ids=[device.id], profiles={family: ACLProfile.model_validate(item.profile)})
    recorded = db.get(m.DeviceACLState, device.id)
    previous = recorded.profile if recorded else None
    attempted = (recorded.attempted or {}).get("profile") if recorded and recorded.status == "dirty" else None
    stale = []
    for profile in (previous, attempted):
        if profile and state.profile_key(profile) != state.profile_key(item.profile) and profile not in stale:
            stale.append(profile)
    return {
        "profile": item.profile,
        "addresses": sorted(item.addresses, key=ip_address),
        "group_ids": sorted(item.group_ids),
        "stale_profiles": stale,
    }


def mark_attempt(job_id, device_id, target):
    with session_factory()() as db:
        row = db.get(m.DeviceACLState, device_id)
        if row is None:
            row = m.DeviceACLState(device_id=device_id, profile=None, addresses=[], group_ids=[])
            db.add(row)
        previous = (row.attempted or {}) if row.status == "dirty" else {}
        row.status = "dirty"
        row.attempted = {
            "profile": target["profile"] or row.profile,
            "addresses": sorted(set(target["addresses"]) | set(previous.get("addresses", []))),
            "group_ids": sorted(set(target["group_ids"]) | set(previous.get("group_ids", []))),
        }
        db.commit()


def record_verified(job_id, device_id, target):
    with session_factory()() as db:
        row = db.get(m.DeviceACLState, device_id)
        if not target["addresses"]:
            if row is not None:
                db.delete(row)
        else:
            if row is None:
                row = m.DeviceACLState(device_id=device_id)
                db.add(row)
            row.profile = target["profile"]
            row.addresses = target["addresses"]
            row.group_ids = target["group_ids"]
            row.status, row.attempted, row.verified_at = "synced", None, now()
        db.flush()
        state.finalize_deletions(db)
        db.commit()


def current_target(job_id, device_id):
    with session_factory()() as db:
        device = db.scalar(eligible_inventory().where(m.Device.id == device_id))
        if not device:
            raise ACLError("Cihazın uygunluğu değişti.")
        return desired_target(db, device)


def progress(job_id, phase, **values):
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        job.result = {**job.result, "phase": phase, **values}
        db.commit()
    publish()


def check_cancel(job_id):
    with session_factory()() as db:
        if get(db, m.Job, job_id).cancel_requested:
            raise ACLError("Gönderim durduruldu.")


READS = {
    "aruba_5400": ("show running-config", "show interfaces brief", "show config"),
    "aruba_2900": ("show running-config", "show interfaces brief", "show config"),
    "aruba_6100": ("show running-config", "show interface brief", "show startup-config"),
    "aruba_7200": ("show running-config", "show interface", "show startup-config"),
    "hp_1950": ("display current-configuration", "display interface brief", "display saved-configuration"),
}


async def apply_plan(shell, job_id, plan):
    for command in plan.commands:
        await sql_quick(check_cancel, job_id)
        await shell.command(command)


async def reconcile(shell, job_id, device, target):
    """Remove stale NETRIX ACLs, then make the desired ACL exact. Returns the verified plans."""
    read_config, read_ports, read_saved = READS[device.adapter]
    log_host = settings().acl_log_host or settings().firmware_advertise_host or None
    plans = []
    config = await shell.command(read_config)
    stale = list(target["stale_profiles"])
    if not target["addresses"] and target["profile"]:
        stale.append(target["profile"])
    for profile in stale:
        plan = adapters.build_removal_plan(device.adapter, profile, config)
        if plan.commands:
            await sql_quick(progress, job_id, "removing", ports=plan.ports)
            await apply_plan(shell, job_id, plan)
            config = await shell.command(read_config)
        adapters.verify_removed(plan, config)
        plans.append(plan)
    ports = None
    if target["addresses"]:
        ports = await shell.command(read_ports)
        plan = adapters.build_sync_plan(
            device.adapter, target["profile"], set(target["addresses"]), config, ports,
            log_host=log_host, log_port=settings().acl_log_port,
        )
        await sql_quick(progress, job_id, "applying", ports=plan.physical_ports)
        await apply_plan(shell, job_id, plan)
        plans.append(plan)
    await sql_quick(progress, job_id, "verifying")
    current = await shell.command(read_config)
    current_ports = await shell.command(read_ports) if ports is not None else ""
    for plan in plans:
        adapters.verify(plan, current, current_ports)
    if device.adapter == "aruba_6100" and target["addresses"]:
        name = target["profile"]["name"]
        active = await shell.command("show access-list ip " + name)
        if (
            "IPv4" not in active
            or name not in active
            or re.search(r"does not match|not applied|insufficient|exceed|resource.*fail", active, re.I)
        ):
            raise ACLError("CX aktif ACL donanım uygulaması doğrulanamadı.")
    saved = await shell.command(read_saved)
    saved_ports = await shell.command(read_ports) if ports is not None else ""
    try:
        for plan in plans:
            adapters.verify(plan, saved, saved_ports)
    except ACLError:
        await sql_quick(progress, job_id, "saving")
        await sql_quick(check_cancel, job_id)
        await shell.command("save force" if device.adapter == "hp_1950" else "write memory", save=True)
        saved = await shell.command(read_saved)
        saved_ports = await shell.command(read_ports) if ports is not None else ""
        for plan in plans:
            adapters.verify(plan, saved, saved_ports)
    return plans


async def execute(job_id):
    async with device_slot(), asyncio.timeout(600):
        device, secret, target = await sql_quick(load_context, job_id)
        await sql_quick(progress, job_id, "preflight")
        await sql_quick(mark_attempt, job_id, device.id, target)
        added, removed, ports, acl_removed = set(), set(), [], False
        async with connect(device, secret) as shell:
            # Changes saved while this job runs are picked up by a bounded re-check.
            for _ in range(3):
                plans = await reconcile(shell, job_id, device, target)
                for plan in plans:
                    added |= set(plan.added)
                    removed |= set(plan.removed)
                    acl_removed = acl_removed or bool(plan.removal and plan.commands)
                    if not plan.removal:
                        ports = plan.physical_ports
                await sql_quick(record_verified, job_id, device.id, target)
                fresh = await sql_quick(current_target, job_id, device.id)
                if not fresh["addresses"] and not fresh["stale_profiles"] or (
                    (fresh["profile"], fresh["addresses"]) == (target["profile"], target["addresses"])
                ):
                    break
                target = fresh
                await sql_quick(mark_attempt, job_id, device.id, target)
        phase = "verified" if target["addresses"] else "removed"
        await sql_quick(progress, job_id, phase, ports=ports)
    return {
        "phase": phase,
        "ports": ports,
        "addresses": len(target["addresses"]),
        "added": sorted(added - removed, key=ip_address),
        "removed": sorted(removed - added, key=ip_address),
        "acl_removed": acl_removed,
        "acl_logging": bool(settings().acl_log_host or settings().firmware_advertise_host),
    }
