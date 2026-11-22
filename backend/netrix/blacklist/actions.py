"""Explicit blacklist actions and SQL-only list views.

Every action changes desired state in SQL first, then queues device sync jobs
for the affected devices. Reads never contact devices.
"""

import logging
from ipaddress import ip_address

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..core import now, session_factory
from ..identity.permissions import can_operate
from ..identity.security import audit
from ..services import get, publish
from . import delivery, state
from .service import ADAPTERS, BulkEntryInput, EntryInput, canonical, entry_view, group_view, save_entry

log = logging.getLogger("netrix.blacklist")


def memberships(db):
    groups_by_entry, devices_by_group = {}, {}
    for entry_id, group_id in db.execute(select(m.BlacklistEntryGroup.entry_id, m.BlacklistEntryGroup.group_id)):
        groups_by_entry.setdefault(entry_id, set()).add(group_id)
    for group_id, device_id in db.execute(select(m.ACLGroupDevice.group_id, m.ACLGroupDevice.device_id)):
        devices_by_group.setdefault(group_id, set()).add(device_id)
    return groups_by_entry, devices_by_group


def entry_targets(db, entry, groups_by_entry=None, devices_by_group=None):
    """Devices that should hold the entry plus devices that may still hold it."""
    if groups_by_entry is None:
        groups_by_entry, devices_by_group = memberships(db)
    active = set(db.scalars(select(m.ACLGroup.id).where(m.ACLGroup.status == "active")))
    wanted = set()
    for group_id in groups_by_entry.get(entry.id, set()) & active:
        wanted |= devices_by_group.get(group_id, set())
    return wanted | state.devices_holding(db, address=entry.address)


def bulk_create(db, user, payload: BulkEntryInput):
    seen, invalid, addresses = set(), [], []
    for raw in payload.addresses:
        try:
            address = canonical(raw)
        except ValueError:
            invalid.append(raw.strip())
            continue
        if address not in seen:
            seen.add(address)
            addresses.append(address)
    if invalid:
        raise HTTPException(422, "Geçersiz adresler: " + ", ".join(invalid[:10]))
    existing = set(db.scalars(select(m.BlacklistEntry.address).where(m.BlacklistEntry.address.in_(addresses))))
    created = []
    for address in addresses:
        if address in existing:
            continue
        item = EntryInput(
            address=address,
            description=payload.description,
            group_ids=payload.group_ids,
            expires_at=payload.expires_at,
        )
        created.append(save_entry(db, user, item, commit=False))
    db.commit()
    return {"created": len(created), "skipped": sorted(existing, key=ip_address), "items": created}


def entry_action(db, user, action, entry_ids):
    entries = list(
        db.scalars(
            select(m.BlacklistEntry).where(m.BlacklistEntry.id.in_(set(entry_ids))).with_for_update()
        )
    )
    if len(entries) != len(set(entry_ids)):
        raise HTTPException(404, "IP kayıtlarından biri bulunamadı.")
    groups_by_entry, devices_by_group = memberships(db)
    active_groups = set(db.scalars(select(m.ACLGroup.id).where(m.ACLGroup.status == "active")))
    devices = set()
    for entry in entries:
        if action == "send":
            if ip_address(entry.address).version != 4:
                raise HTTPException(422, "Cihazlara gönderim şu anda IPv4 adreslerini destekliyor.")
            if not groups_by_entry.get(entry.id, set()) & active_groups:
                raise HTTPException(422, f"{entry.address} için etkin bir ACL grubu seçin.")
            if entry.expires_at and entry.expires_at <= now():
                raise HTTPException(422, f"{entry.address} kaydının bitiş zamanı geçmiş. Kaydı düzenleyin.")
        entry.status = {"send": "active", "remove": "disabled", "delete": "deleting"}[action]
        entry.updated_by, entry.updated_at = user.id, now()
        devices |= (entry_targets(db, entry, groups_by_entry, devices_by_group)
                    if action == "send" else state.devices_holding(db, address=entry.address))
    db.flush()
    result = delivery.enqueue(
        db,
        user,
        devices,
        entry_id=entries[0].id if len(entries) == 1 else None,
        reason={"send": "entry", "remove": "entry_remove", "delete": "entry_delete"}[action],
        strict=action == "send",
    )
    if action == "send" and not result["job_ids"]:
        raise HTTPException(422, "Gönderilecek cihaz bulunamadı.")
    deleted = state.finalize_deletions(db) if action == "delete" else 0
    label = {"send": "gönderildi", "remove": "kaldırılıyor", "delete": "siliniyor"}[action]
    for entry in entries:
        audit(db, user, action, "blacklist_entries", entry.id, f"Kara Liste IP kaydı {label} · {entry.address}")
    db.commit()
    publish()
    return {**result, "entries": len(entries), "deleted": deleted}


def delete_group(db, user, group_id):
    group = db.scalar(select(m.ACLGroup).where(m.ACLGroup.id == group_id).with_for_update())
    if group is None:
        raise HTTPException(404, "ACL grubu bulunamadı.")
    members = set(db.scalars(select(m.ACLGroupDevice.device_id).where(m.ACLGroupDevice.group_id == group.id)))
    # SQL may have no verified state even though the ACL exists on a device.
    # Keep a pending removal obligation for every current member until SSH verifies it.
    for device in db.scalars(select(m.Device).where(m.Device.id.in_(members))):
        if db.get(m.DeviceACLState, device.id) is None:
            profile = group.profiles.get(ADAPTERS.get(device.adapter))
            db.add(m.DeviceACLState(
                device_id=device.id, profile=None, addresses=[], group_ids=[], status="dirty",
                attempted={"profile": profile, "addresses": [], "group_ids": [group.id]},
            ))
    group.status, group.updated_at = "deleting", now()
    db.flush()
    devices = members | state.devices_holding(db, group_id=group.id)
    result = delivery.enqueue(db, user, devices, reason="group_delete", strict=False)
    deleted = state.finalize_deletions(db)
    audit(db, user, "delete", "acl_groups", group.id, f"Kara Liste ACL grubu siliniyor · {group.name}")
    db.commit()
    publish()
    return {**result, "deleted": deleted}


def sync_group(db, user, group_id):
    group = get(db, m.ACLGroup, group_id)
    members = set(db.scalars(select(m.ACLGroupDevice.device_id).where(m.ACLGroupDevice.group_id == group.id)))
    result = delivery.enqueue(
        db, user, members | state.devices_holding(db, group_id=group.id), reason="group", strict=False
    )
    db.commit()
    publish()
    return result


def sync_devices(db, user, device_ids):
    result = delivery.enqueue(db, user, device_ids, reason="device", strict=False)
    db.commit()
    publish()
    return result


def forget_device(db, user, device_id):
    row = db.get(m.DeviceACLState, device_id)
    if row is None:
        raise HTTPException(404, "Cihaz için kayıtlı Kara Liste durumu yok.")
    if db.scalar(select(m.Job.id).where(m.Job.active_key == delivery.ACTIVE_KEY + device_id)):
        raise HTTPException(409, "Cihazda devam eden Kara Liste işi var.")
    device = db.get(m.Device, device_id)
    db.delete(row)
    db.flush()
    state.finalize_deletions(db)
    audit(
        db, user, "delete", "device_acl_states", device_id,
        f"Kara Liste cihaz durumu unutuldu · {device.name if device else device_id}",
    )
    db.commit()
    publish()
    return {"ok": True}


def expire_due(at=None):
    """Disable expired active entries and queue their removal as the user who set the expiry."""
    at = at or now()
    with session_factory()() as db:
        expired = list(
            db.scalars(
                select(m.BlacklistEntry)
                .where(
                    m.BlacklistEntry.status == "active",
                    m.BlacklistEntry.expires_at.is_not(None),
                    m.BlacklistEntry.expires_at <= at,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for entry in expired:
            entry.status, entry.updated_at = "disabled", at
            user = db.get(m.User, entry.updated_by) if entry.updated_by else None
            db.flush()
            if user and user.is_active and can_operate(user):
                devices = entry_targets(db, entry)
                result = delivery.enqueue(db, user, devices, entry_id=entry.id, reason="expired", strict=False)
                for item in result["skipped"]:
                    log.warning("Süresi dolan Kara Liste kaydı kaldırılamadı: %s", item["reason"])
            audit(db, user, "expire", "blacklist_entries", entry.id, f"Kara Liste süresi doldu · {entry.address}")
        db.commit()
    if expired:
        publish()
    return len(expired)


ACTIVE_STATES = ("queued", "running")


def entry_list(db):
    rows = list(db.scalars(select(m.BlacklistEntry).order_by(m.BlacklistEntry.updated_at.desc(), m.BlacklistEntry.id)))
    groups_by_entry, devices_by_group = memberships(db)
    groups = {group.id: group for group in db.scalars(select(m.ACLGroup))}
    recorded = state.states(db)
    jobs = delivery.latest_jobs(db)
    names = dict(db.execute(select(m.Device.id, m.Device.name)).all())
    result = []
    for row in rows:
        ids = groups_by_entry.get(row.id, set())
        wanted = set()
        if row.status == "active":
            for group_id in ids:
                if groups[group_id].status == "active":
                    wanted |= devices_by_group.get(group_id, set())
        devices = []
        relevant = set(wanted)
        for device_id, item in recorded.items():
            if row.address in state.held(item)[0]:
                relevant.add(device_id)
        for device_id in sorted(relevant, key=lambda value: (names.get(value, ""), value)):
            item = recorded.get(device_id)
            applied = None
            if item is None:
                applied = False
            elif row.address in (item.addresses or []):
                applied = True if item.status == "synced" else None
            elif item.status == "dirty" and row.address in (item.attempted or {}).get("addresses", []):
                applied = None
            else:
                applied = False
            devices.append({
                "device_id": device_id,
                "name": names.get(device_id, ""),
                "desired": device_id in wanted,
                "applied": applied,
                "job": delivery.job_view(jobs.get(device_id)),
            })
        result.append({**entry_view(row, ids), "devices": devices, "state": entry_state(row, devices)})
    return result


def entry_state(row, devices):
    if any(device["job"] and device["job"]["status"] in ACTIVE_STATES for device in devices):
        return "running" if any(d["job"] and d["job"]["status"] == "running" for d in devices) else "queued"
    mismatched = [device for device in devices if device["desired"] is not device["applied"]]
    failed = any(device["job"] and device["job"]["status"] == "failed" for device in mismatched)
    if row.status == "deleting":
        return "delete_failed" if failed else "deleting"
    if row.status == "draft":
        return "draft"
    if row.status == "disabled":
        if not mismatched:
            return "disabled"
        return "failed" if failed else "remove_pending"
    if not devices:
        return "no_target"
    if not mismatched:
        return "blocked"
    if failed:
        return "failed"
    if any(device["applied"] for device in devices):
        return "partial"
    return "pending"


def group_list(db):
    members = {}
    for group_id, device_id in db.execute(select(m.ACLGroupDevice.group_id, m.ACLGroupDevice.device_id)):
        members.setdefault(group_id, []).append(device_id)
    recorded = state.states(db)
    desired = state.desired_state(db)
    entry_counts = {}
    for (group_id,) in db.execute(
        select(m.BlacklistEntryGroup.group_id)
        .join(m.BlacklistEntry, m.BlacklistEntry.id == m.BlacklistEntryGroup.entry_id)
        .where(m.BlacklistEntry.status == "active")
    ):
        entry_counts[group_id] = entry_counts.get(group_id, 0) + 1
    result = []
    for row in db.scalars(select(m.ACLGroup).order_by(m.ACLGroup.name, m.ACLGroup.id)):
        ids = members.get(row.id, [])
        holding = {device_id for device_id, item in recorded.items() if row.id in state.held(item)[1]}
        relevant = set(ids) | holding
        pending = sum(
            1 for device_id in relevant
            if device_id in desired and not state.in_sync(desired[device_id], recorded.get(device_id))
        )
        result.append({
            **group_view(row, ids),
            "active_entries": entry_counts.get(row.id, 0),
            "applied_devices": len(holding),
            "pending_devices": pending,
        })
    return result


def acl_text(profile):
    if not profile:
        return None
    return " · ".join(
        str(value) for value in (profile.get("name"), f"#{profile['number']}" if profile.get("number") else None)
        if value
    )


def device_list(db):
    desired = state.desired_state(db)
    recorded = state.states(db)
    jobs = delivery.latest_jobs(db)
    devices = {
        device.id: device
        for device in db.scalars(select(m.Device).where(m.Device.id.in_(set(desired) | set(recorded))))
    }
    group_names = dict(db.execute(select(m.ACLGroup.id, m.ACLGroup.name)).all())
    result = []
    for device_id, item in desired.items():
        device = devices.get(device_id)
        row = recorded.get(device_id)
        job = delivery.job_view(jobs.get(device_id))
        if job and job["status"] in ACTIVE_STATES:
            status = job["status"]
        elif item.issue:
            status = "issue"
        elif state.in_sync(item, row):
            status = "synced"
        elif row and row.status == "dirty" and job and job["status"] in ("failed", "cancelled", "partial"):
            status = "failed"
        else:
            status = "pending"
        result.append({
            "device_id": device_id,
            "name": device.name if device else "",
            "management_ip": device.management_ip if device else "",
            "model": device.model if device else "",
            "family": item.family,
            "groups": sorted(group_names.get(group_id, "") for group_id in item.group_ids),
            "desired_acl": acl_text(item.profile),
            "desired_count": len(item.addresses),
            "applied_acl": acl_text(row.profile) if row else None,
            "applied_count": len(row.addresses or []) if row else 0,
            "verified_at": row.verified_at if row else None,
            "recorded": row is not None,
            "status": status,
            "issue": item.issue,
            "will_remove_acl": bool(row and row.profile and item.profile is None),
            "job": job,
        })
    result.sort(key=lambda value: (value["name"], value["device_id"]))
    return result
