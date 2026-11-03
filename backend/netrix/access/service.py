"""Authorization is checked at admission, worker connection and throughout sessions."""

import json

from fastapi import HTTPException
from sqlalchemy import delete, select, update

from .. import models as m
from ..identity.permissions import can_ssh
from ..identity.security import audit, decrypt, encrypt
from .schemas import DEFAULT_IDLE_TIMEOUT_MINUTES, Preferences


def workspace(db, user):
    row = db.get(m.UserWorkspace, user.id)
    if row is None:
        row = m.UserWorkspace(user_id=user.id, preferences={})
        db.add(row)
    return row


def preferences(db, user):
    row = db.get(m.UserWorkspace, user.id)
    return Preferences.model_validate(row.preferences if row else {}).model_dump()


def lock_owner(db, user):
    # These entry points own their transaction (and commit it below). Authentication
    # may already have opened a repeatable-read snapshot before waiting for this
    # lock. End that read-only snapshot, then lock BEFORE the first consistent read.
    # Reject unflushed writes; callers must supply a read-only entry transaction.
    user_id = user.id
    if db.new or db.dirty or db.deleted:
        raise RuntimeError("Workspace writes require a clean transaction")
    db.rollback()
    db.scalar(select(m.User.id).where(m.User.id == user_id).with_for_update())


def owned_profile(db, user, id):
    row = db.scalar(
        select(m.UserSSHProfile)
        .where(m.UserSSHProfile.id == id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row or row.owner_id != user.id:
        raise HTTPException(404, "SSH bağlantısı bulunamadı")
    return row


def public_profile(row, groups):
    data = json.loads(decrypt(row.encrypted_ssh))
    return {
        "id": row.id,
        "name": row.name,
        "group_ids": groups,
        **{k: v for k, v in data.items() if k not in ("password", "private_key", "passphrase")},
        "idle_timeout_minutes": data.get("idle_timeout_minutes", DEFAULT_IDLE_TIMEOUT_MINUTES),
        "has_password": bool(data.get("password")),
        "has_private_key": bool(data.get("private_key")),
    }


def list_profiles(db, user):
    profiles = list(
        db.scalars(
            select(m.UserSSHProfile)
            .where(m.UserSSHProfile.owner_id == user.id)
            .order_by(m.UserSSHProfile.name)
        )
    )
    assigned = {}
    for group_id, profile_id in db.execute(
        select(m.AccessGroup.id, m.AccessGroup.ssh_profile_id).where(
            m.AccessGroup.owner_id == user.id, m.AccessGroup.ssh_profile_id.is_not(None)
        )
    ):
        assigned.setdefault(profile_id, []).append(group_id)
    return [public_profile(row, assigned.get(row.id, [])) for row in profiles]


def save_ssh(db, user, payload, id=None):
    lock_owner(db, user)
    row = owned_profile(db, user, id) if id else m.UserSSHProfile(owner_id=user.id)
    data = json.loads(decrypt(row.encrypted_ssh)) if id else {}
    group_ids = set(payload.group_ids)
    groups = list(
        db.scalars(
            select(m.AccessGroup)
            .where(m.AccessGroup.id.in_(group_ids), m.AccessGroup.owner_id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if len(groups) != len(group_ids):
        raise HTTPException(422, "Yalnız kendi cihaz gruplarınızı seçebilirsiniz")
    if any(g.ssh_profile_id and g.ssh_profile_id != id for g in groups):
        raise HTTPException(
            409, "Seçilen grup başka bir SSH bağlantısına atanmış; önce mevcut atamayı kaldırın"
        )
    for name, value in payload.model_dump(exclude={"name", "group_ids"}).items():
        if name in ("password", "private_key", "passphrase"):
            if value is not None:
                data[name] = value.get_secret_value()
        else:
            data[name] = value
    if not data.get("password") and not data.get("private_key"):
        raise HTTPException(422, "Parola veya özel SSH anahtarı gerekli")
    row.name, row.encrypted_ssh = payload.name, encrypt(json.dumps(data))
    db.add(row)
    db.flush()
    db.execute(
        update(m.AccessGroup)
        .where(m.AccessGroup.owner_id == user.id, m.AccessGroup.ssh_profile_id == row.id)
        .values(ssh_profile_id=None)
    )
    for group in groups:
        group.ssh_profile_id = row.id
    audit(
        db,
        user,
        "ssh_profile_saved",
        "user_ssh_profile",
        row.id,
        "Kişisel SSH bağlantısı ve grup atamaları güncellendi",
    )
    db.commit()
    return public_profile(row, sorted(group_ids))


def delete_profile(db, user, id):
    lock_owner(db, user)
    row = owned_profile(db, user, id)
    db.execute(
        update(m.AccessGroup)
        .where(m.AccessGroup.owner_id == user.id, m.AccessGroup.ssh_profile_id == id)
        .values(ssh_profile_id=None)
    )
    db.delete(row)
    audit(db, user, "ssh_profile_deleted", "user_ssh_profile", id, "Kişisel SSH bağlantısı kaldırıldı")
    db.commit()


def resolve_profile(db, user, device_id, expected_id=None):
    row = db.scalar(
        select(m.UserSSHProfile)
        .join(m.AccessGroup, m.AccessGroup.ssh_profile_id == m.UserSSHProfile.id)
        .join(m.AccessGroupDevice, m.AccessGroupDevice.group_id == m.AccessGroup.id)
        .where(
            m.AccessGroup.owner_id == user.id,
            m.UserSSHProfile.owner_id == user.id,
            m.AccessGroupDevice.device_id == device_id,
        )
    )
    if not row:
        raise HTTPException(
            409, "Profil → Cihaz yetkisi bölümünde cihazı bir gruba ekleyin ve gruba SSH bağlantısı atayın"
        )
    if expected_id and row.id != expected_id:
        raise HTTPException(409, "Cihazın SSH bağlantısı değişti; oturumu yeniden açın")
    return row.id, json.loads(decrypt(row.encrypted_ssh))


def commands(db, user):
    row = db.get(m.UserWorkspace, user.id)
    return json.loads(decrypt(row.encrypted_commands)) if row and row.encrypted_commands else []


def batch_targets(db, user, device_ids):
    targets = []
    for id in dict.fromkeys(device_ids):
        device = authorize_device(db, user, id)
        profile_id, _ = resolve_profile(db, user, id)
        targets.append(
            {
                "device_id": id,
                "ssh_profile_id": profile_id,
                "name": device.name,
                "management_ip": device.management_ip,
                "status": "queued",
                "output": "",
            }
        )
    return targets


def authorize_device(db, user, device_id):
    device = db.get(m.Device, device_id)
    if not device or device.archived or not device.discovery_scope_id:
        raise HTTPException(404, "Envanter cihazı bulunamadı")
    if device.lifecycle_status not in ("active", "maintenance"):
        raise HTTPException(409, "Bu cihaz bağlantıya uygun durumda değil")
    if not can_ssh(user):
        raise HTTPException(
            403, "SSH bağlantısı rolünüz yok; yöneticiniz Ekip & yetkiler bölümünden atayabilir"
        )
    return device


def group_data(db, group):
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "owner_id": group.owner_id,
        "ssh_profile_id": group.ssh_profile_id,
        "device_ids": list(
            db.scalars(select(m.AccessGroupDevice.device_id).where(m.AccessGroupDevice.group_id == group.id))
        ),
    }


def list_groups(db, user):
    stmt = select(m.AccessGroup).where(m.AccessGroup.owner_id == user.id).order_by(m.AccessGroup.name)
    groups = list(db.scalars(stmt))
    ids = [g.id for g in groups]
    members = {}
    for group_id, device_id in db.execute(
        select(m.AccessGroupDevice.group_id, m.AccessGroupDevice.device_id).where(
            m.AccessGroupDevice.group_id.in_(ids)
        )
    ):
        members.setdefault(group_id, []).append(device_id)
    return [
        {
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "owner_id": g.owner_id,
            "ssh_profile_id": g.ssh_profile_id,
            "device_ids": members.get(g.id, []),
        }
        for g in groups
    ]


def owned_group(db, user, id):
    group = db.scalar(
        select(m.AccessGroup)
        .where(m.AccessGroup.id == id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not group or group.owner_id != user.id:
        raise HTTPException(404, "Grup bulunamadı")
    return group


def save_group(db, user, payload, id=None):
    lock_owner(db, user)
    group = owned_group(db, user, id) if id else m.AccessGroup(owner_id=user.id)
    ids = set(payload.device_ids)
    actual = set(
        db.scalars(
            select(m.Device.id).where(
                m.Device.id.in_(ids), m.Device.archived.is_(False), m.Device.discovery_scope_id.is_not(None)
            )
        )
    )
    if actual != ids:
        raise HTTPException(422, "Grup yalnız mevcut envanter cihazlarını içerebilir")
    conflict = db.scalar(
        select(m.AccessGroup.name)
        .join(m.AccessGroupDevice, m.AccessGroupDevice.group_id == m.AccessGroup.id)
        .where(
            m.AccessGroupDevice.owner_id == user.id,
            m.AccessGroupDevice.device_id.in_(ids),
            m.AccessGroup.id != (id or ""),
        )
        .with_for_update()
    )
    if conflict:
        raise HTTPException(409, f"Seçilen cihaz başka bir grupta: {conflict}. Önce o gruptan çıkarın")
    group.name, group.description = payload.name, payload.description
    db.add(group)
    db.flush()
    existing = set(
        db.scalars(
            select(m.AccessGroupDevice.device_id)
            .where(m.AccessGroupDevice.group_id == group.id)
            .with_for_update()
        )
    )
    removed = existing - ids
    if removed:
        db.execute(
            delete(m.AccessGroupDevice).where(
                m.AccessGroupDevice.group_id == group.id, m.AccessGroupDevice.device_id.in_(removed)
            )
        )
    db.add_all(
        m.AccessGroupDevice(group_id=group.id, owner_id=user.id, device_id=device_id)
        for device_id in ids - existing
    )
    audit(db, user, "access_group_saved", "access_group", group.id, "Kişisel cihaz grubu güncellendi")
    db.commit()
    return group_data(db, group)
