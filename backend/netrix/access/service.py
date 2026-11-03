"""Authorization is checked at admission, worker connection and throughout sessions."""

import json

from fastapi import HTTPException
from sqlalchemy import delete, select

from .. import models as m
from ..identity.security import audit, decrypt, encrypt
from .schemas import Preferences


def workspace(db, user):
    row = db.get(m.UserWorkspace, user.id)
    if row is None:
        row = m.UserWorkspace(user_id=user.id, preferences={})
        db.add(row)
    return row


def preferences(db, user):
    row = db.get(m.UserWorkspace, user.id)
    return Preferences.model_validate(row.preferences if row else {}).model_dump()


def ssh_profile(db, user, *, private=False):
    row = db.get(m.UserWorkspace, user.id)
    data = json.loads(decrypt(row.encrypted_ssh)) if row and row.encrypted_ssh else {}
    if private:
        return data
    return {
        **{k: v for k, v in data.items() if k not in ("password", "private_key", "passphrase")},
        "has_password": bool(data.get("password")),
        "has_private_key": bool(data.get("private_key")),
    }


def save_ssh(db, user, payload):
    data = ssh_profile(db, user, private=True)
    for name, value in payload.model_dump().items():
        if name in ("password", "private_key", "passphrase"):
            if value is not None:
                data[name] = value.get_secret_value()
        else:
            data[name] = value
    if not data.get("password") and not data.get("private_key"):
        raise HTTPException(422, "Parola veya özel SSH anahtarı gerekli")
    workspace(db, user).encrypted_ssh = encrypt(json.dumps(data))
    audit(db, user, "ssh_profile_saved", "user", user.id, "Kişisel SSH bağlantısı güncellendi")
    db.commit()
    return ssh_profile(db, user)


def commands(db, user):
    row = db.get(m.UserWorkspace, user.id)
    return json.loads(decrypt(row.encrypted_commands)) if row and row.encrypted_commands else []


def allowed_ids(db, user):
    return (
        select(m.AccessGroupDevice.device_id)
        .join(m.AccessGroup, m.AccessGroup.id == m.AccessGroupDevice.group_id)
        .join(m.AccessGroupUser, m.AccessGroupUser.group_id == m.AccessGroup.id)
        .where(m.AccessGroup.ssh_enabled.is_(True), m.AccessGroupUser.user_id == user.id)
    )


def authorize_device(db, user, device_id):
    device = db.get(m.Device, device_id)
    if not device or device.archived or not device.discovery_scope_id:
        raise HTTPException(404, "Envanter cihazı bulunamadı")
    if device.lifecycle_status not in ("active", "maintenance"):
        raise HTTPException(409, "Bu cihaz bağlantıya uygun durumda değil")
    if user.role != "admin" and not db.scalar(
        select(m.Device.id).where(m.Device.id == device_id, m.Device.id.in_(allowed_ids(db, user)))
    ):
        raise HTTPException(403, "Bu cihaz için SSH bağlantı yetkiniz yok")
    return device


def group_data(db, group):
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "owner_id": group.owner_id,
        "ssh_enabled": group.ssh_enabled,
        "device_ids": list(
            db.scalars(select(m.AccessGroupDevice.device_id).where(m.AccessGroupDevice.group_id == group.id))
        ),
        "user_ids": list(
            db.scalars(select(m.AccessGroupUser.user_id).where(m.AccessGroupUser.group_id == group.id))
        ),
    }


def list_groups(db, user):
    stmt = select(m.AccessGroup).order_by(m.AccessGroup.name)
    if user.role != "admin":
        stmt = stmt.where(m.AccessGroup.owner_id == user.id)
    groups = list(db.scalars(stmt.limit(200)))
    ids = [g.id for g in groups]
    members, users = {}, {}
    for group_id, device_id in db.execute(
        select(m.AccessGroupDevice.group_id, m.AccessGroupDevice.device_id).where(
            m.AccessGroupDevice.group_id.in_(ids)
        )
    ):
        members.setdefault(group_id, []).append(device_id)
    for group_id, user_id in db.execute(
        select(m.AccessGroupUser.group_id, m.AccessGroupUser.user_id).where(
            m.AccessGroupUser.group_id.in_(ids)
        )
    ):
        users.setdefault(group_id, []).append(user_id)
    return [
        {
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "owner_id": g.owner_id,
            "ssh_enabled": g.ssh_enabled,
            "device_ids": members.get(g.id, []),
            "user_ids": users.get(g.id, []),
        }
        for g in groups
    ]


def owned_group(db, user, id):
    group = db.get(m.AccessGroup, id)
    if not group or (user.role != "admin" and group.owner_id != user.id):
        raise HTTPException(404, "Grup bulunamadı")
    return group


def save_group(db, user, payload, id=None):
    group = owned_group(db, user, id) if id else m.AccessGroup(owner_id=user.id)
    if user.role != "admin":
        # A personal grouping must never create a new grant or broaden an existing one.
        if payload.user_ids or payload.ssh_enabled or (id and group.ssh_enabled):
            raise HTTPException(403, "SSH yetkilerini yalnız yönetici düzenleyebilir")
        for device_id in set(payload.device_ids):
            authorize_device(db, user, device_id)
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
    users = set(payload.user_ids)
    if set(db.scalars(select(m.User.id).where(m.User.id.in_(users), m.User.is_active.is_(True)))) != users:
        raise HTTPException(422, "Kullanıcı bulunamadı veya etkin değil")
    group.name, group.description, group.ssh_enabled = payload.name, payload.description, payload.ssh_enabled
    db.add(group)
    db.flush()
    for model in (m.AccessGroupDevice, m.AccessGroupUser):
        db.execute(delete(model).where(model.group_id == group.id))
    db.add_all(m.AccessGroupDevice(group_id=group.id, device_id=id) for id in ids)
    db.add_all(m.AccessGroupUser(group_id=group.id, user_id=id) for id in users)
    audit(
        db, user, "access_group_saved", "access_group", group.id, "Cihaz grubu ve SSH yetkileri güncellendi"
    )
    db.commit()
    return group_data(db, group)
