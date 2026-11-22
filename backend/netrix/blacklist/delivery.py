"""Durable submissions and per-device worker execution for explicit send actions."""

import asyncio
import re
from ipaddress import ip_address

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..core import session_factory, settings
from ..identity.permissions import can_operate
from ..identity.security import audit, secret_data
from ..runtime_limits import device_slot, sql_quick
from ..services import connection_profile, get, publish
from . import adapters
from .cli import ACLError, connect
from .service import ACLProfile, GroupInput, device_family, eligible_inventory, entry_view, preview_entry


def endpoint(device):
    return [
        device.management_ip,
        device.adapter,
        device.config_port,
        device.config_credential_id,
        device.ssh_trust_host_key,
    ]


def submit(db, user, entry_id):
    entry = db.scalar(select(m.BlacklistEntry).where(m.BlacklistEntry.id == entry_id).with_for_update())
    if entry is None:
        raise HTTPException(404, "IP kaydı bulunamadı.")
    if ip_address(entry.address).version != 4:
        raise HTTPException(422, "Cihazlara gönderim şu anda IPv4 adreslerini destekliyor.")
    preview = preview_entry(db, entry.id)
    by_device = {}
    for target in preview["targets"]:
        if target["issue"]:
            raise HTTPException(422, target["issue"])
        by_device.setdefault(target["device_id"], []).append(target)
    if not by_device:
        raise HTTPException(422, "Gönderilecek cihaz bulunamadı.")
    jobs = []
    for device_id, targets in sorted(by_device.items()):
        if len(targets) != 1:
            raise HTTPException(
                422, "Aynı cihazın tüm portları için tek ACL seçin. Gruplardaki ACL kimlikleri çakışıyor."
            )
        device = db.scalar(select(m.Device).where(m.Device.id == device_id).with_for_update())
        if not device or not connection_profile(db, device, "ssh"):
            raise HTTPException(422, f"{targets[0]['name']} için SSH erişim profili gerekli.")
        if db.scalar(
            select(m.FirmwareTarget.id).where(
                m.FirmwareTarget.active_device == device_id,
                m.FirmwareTarget.status == "running",
            )
        ):
            raise HTTPException(409, "Cihazda firmware işlemi sürüyor.")
        payload = {
            "address": entry.address,
            "profile": targets[0]["profile"],
            "endpoint": endpoint(device),
            "group_ids": sorted(targets[0]["group_ids"]),
        }
        active = db.scalar(select(m.Job).where(m.Job.active_key == "blacklist_send:" + device_id))
        if active:
            prior = db.scalar(select(m.BlacklistDelivery).where(m.BlacklistDelivery.job_id == active.id))
            if not prior or prior.entry_id != entry.id or prior.payload != payload:
                raise HTTPException(409, f"{device.name} için başka Kara Liste gönderimi sürüyor.")
            jobs.append(active)
            continue
        job = m.Job(
            kind="blacklist_send",
            target_id=device_id,
            active_key="blacklist_send:" + device_id,
            requested_by=user.id,
            total=1,
            result={"address": entry.address, "phase": "queued"},
        )
        db.add(job)
        db.flush()
        db.add(m.BlacklistDelivery(entry_id=entry.id, device_id=device_id, job_id=job.id, payload=payload))
        audit(db, user, "enqueue", "jobs", job.id, f"Kara Liste gönderimi kuyruğa alındı · {device.name}")
        jobs.append(job)
    db.commit()
    publish()
    return {"job_ids": [job.id for job in jobs], "devices": len(jobs)}


def history(db, entry_ids):
    rows = db.execute(
        select(m.BlacklistDelivery, m.Job, m.Device.name)
        .join(m.Job, m.Job.id == m.BlacklistDelivery.job_id)
        .join(m.Device, m.Device.id == m.BlacklistDelivery.device_id)
        .where(m.BlacklistDelivery.entry_id.in_(entry_ids))
        .order_by(m.BlacklistDelivery.created_at.desc(), m.BlacklistDelivery.id)
    )
    result = {}
    seen = set()
    for delivery, job, name in rows:
        key = (delivery.entry_id, delivery.device_id)
        if key in seen:
            continue
        seen.add(key)
        result.setdefault(delivery.entry_id, []).append(
            {
                "job_id": job.id,
                "device_id": delivery.device_id,
                "name": name,
                "address": delivery.payload["address"],
                "group_ids": delivery.payload["group_ids"],
                "status": job.status,
                "phase": job.result.get("phase", ""),
                "error": job.error,
                "ports": job.result.get("ports", []),
                "finished_at": job.finished_at,
                "cancel_requested": job.cancel_requested,
            }
        )
    return result


def load_target(job_id):
    with session_factory()() as db:
        job = get(db, m.Job, job_id)
        delivery = db.scalar(select(m.BlacklistDelivery).where(m.BlacklistDelivery.job_id == job_id))
        if job.cancel_requested:
            raise ACLError("Gönderim durduruldu.")
        user = db.get(m.User, job.requested_by) if job.requested_by else None
        if not delivery or not user or not user.is_active or not can_operate(user):
            raise ACLError("Gönderimi başlatan kullanıcının yetkisi artık geçerli değil.")
        device = db.scalar(eligible_inventory().where(m.Device.id == delivery.device_id))
        if not device or not device_family(device) or endpoint(device) != delivery.payload["endpoint"]:
            raise ACLError("Cihazın uygunluğu veya SSH hedefi değişti. Kaydı kontrol edip yeniden gönderin.")
        profile = ACLProfile.model_validate(delivery.payload["profile"])
        # Reapply the complete family contract, including numeric ranges and identifier safety.
        family = device_family(device)
        GroupInput(name="validation", device_ids=[device.id], profiles={family: profile})
        credential = connection_profile(db, device, "ssh")
        if not credential:
            raise ACLError("Cihazın kayıtlı SSH profili bulunamadı.")
        secret = secret_data(credential)
        db.expunge(device)
        return device, secret, profile.model_dump(), delivery.payload["address"]


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


async def execute(job_id):
    async with device_slot(), asyncio.timeout(600):
        device, secret, profile, address = await sql_quick(load_target, job_id)
        await sql_quick(progress, job_id, "preflight")
        async with connect(device, secret) as shell:
            read_config, read_ports, read_saved = READS[device.adapter]
            config = await shell.command(read_config)
            ports = await shell.command(read_ports)
            plan = adapters.build_plan(
                device.adapter, profile, address, config, ports,
                log_host=settings().acl_log_host or settings().firmware_advertise_host or None,
                log_port=settings().acl_log_port,
            )
            await sql_quick(progress, job_id, "applying", ports=plan.physical_ports)
            for command in plan.commands:
                await sql_quick(check_cancel, job_id)
                await shell.command(command)
            await sql_quick(progress, job_id, "verifying")
            current = await shell.command(read_config)
            current_ports = await shell.command(read_ports)
            adapters.verify(plan, current, current_ports)
            if device.adapter == "aruba_6100":
                active = await shell.command("show access-list ip " + profile["name"])
                if (
                    "IPv4" not in active
                    or profile["name"] not in active
                    or re.search(
                        r"does not match|not applied|insufficient|exceed|resource.*fail", active, re.I
                    )
                ):
                    raise ACLError("CX aktif ACL donanım uygulaması doğrulanamadı.")
            await sql_quick(progress, job_id, "saving")
            await sql_quick(check_cancel, job_id)
            await shell.command("save force" if device.adapter == "hp_1950" else "write memory", save=True)
            saved = await shell.command(read_saved)
            saved_ports = await shell.command(read_ports)
            adapters.verify(plan, saved, saved_ports)
            await sql_quick(progress, job_id, "verified", ports=plan.physical_ports)
    return {"phase": "verified", "ports": plan.physical_ports, "address": address, "acl_logging": bool(plan.log_host)}


def entry_list(db):
    rows = list(
        db.scalars(select(m.BlacklistEntry).order_by(m.BlacklistEntry.updated_at.desc(), m.BlacklistEntry.id))
    )
    recent = history(db, [row.id for row in rows])
    groups = {group.id: group for group in db.scalars(select(m.ACLGroup))}
    devices = {}
    for group_id, device_id in db.execute(select(m.ACLGroupDevice.group_id, m.ACLGroupDevice.device_id)):
        devices.setdefault(group_id, set()).add(device_id)
    memberships = {}
    for entry_id, group_id in db.execute(
        select(m.BlacklistEntryGroup.entry_id, m.BlacklistEntryGroup.group_id)
    ):
        memberships.setdefault(entry_id, []).append(group_id)
    # A newer definition or newly added device must never appear as already applied.
    submissions = list(
        db.scalars(select(m.BlacklistDelivery).order_by(m.BlacklistDelivery.created_at.desc()))
    )
    latest_time = {}
    for submission in submissions:
        latest_time.setdefault((submission.entry_id, submission.device_id), submission.created_at)
    result = []
    for row in rows:
        ids = memberships.get(row.id, [])
        targets = set().union(*(devices.get(group_id, set()) for group_id in ids))
        completed = recent.get(row.id, [])
        changed = targets != {item["device_id"] for item in completed}
        for item in completed:
            submitted_at = latest_time[(row.id, item["device_id"])]
            changed = (
                changed
                or row.updated_at > submitted_at
                or any(groups[group_id].updated_at > submitted_at for group_id in ids)
            )
        result.append(
            {
                **entry_view(row, ids),
                "deliveries": completed,
                "needs_send": changed,
            }
        )
    return result
