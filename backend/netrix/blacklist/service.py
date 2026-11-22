"""Inventory eligibility and validation for blacklist drafts."""

import re
from datetime import datetime
from ipaddress import ip_address
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import lazyload

from .. import models as m
from ..core import now
from ..firmware.families import model_branch
from ..identity.security import audit
from ..services import get

Family = Literal["aos_switch", "aos_cx", "aruba_os", "comware_1950"]
FAMILIES = {
    "aos_switch": {
        "label": "Aruba 5412 / 5406 / 2930",
        "types": {"standard": "Standart IPv4", "extended": "Genişletilmiş IPv4"},
    },
    "aos_cx": {"label": "Aruba 6100", "types": {"ipv4": "IPv4"}},
    "aruba_os": {"label": "Aruba 7205", "types": {"session": "Oturum ACL’si"}},
    "comware_1950": {"label": "HP 1950", "types": {"basic": "Temel IPv4", "advanced": "Gelişmiş IPv4"}},
}
ADAPTERS = {
    "aruba_5400": "aos_switch",
    "aruba_2900": "aos_switch",
    "aruba_6100": "aos_cx",
    "aruba_7200": "aruba_os",
    "hp_1950": "comware_1950",
}
NUMBER_RANGES = {
    ("aos_switch", "standard"): (1, 99),
    ("aos_switch", "extended"): (100, 199),
    ("comware_1950", "basic"): (2000, 2999),
    ("comware_1950", "advanced"): (3000, 3999),
}
ID = Annotated[str, StringConstraints(min_length=1, max_length=36)]
ACLName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ACLProfile(Input):
    type: str = Field(min_length=1, max_length=12)
    name: ACLName | None = None
    number: int | None = Field(default=None, strict=True)


class GroupInput(Input):
    name: str = Field(min_length=1, max_length=120)
    device_ids: list[ID] = Field(min_length=1, max_length=1000)
    profiles: dict[Family, ACLProfile] = Field(min_length=1, max_length=len(FAMILIES))

    @model_validator(mode="after")
    def validate_profiles(self):
        for family, profile in self.profiles.items():
            if profile.type not in FAMILIES[family]["types"]:
                raise ValueError(f"{FAMILIES[family]['label']} için ACL türü geçersiz.")
            number_range = NUMBER_RANGES.get((family, profile.type))
            if profile.number is not None and (
                number_range is None or not number_range[0] <= profile.number <= number_range[1]
            ):
                raise ValueError(f"{FAMILIES[family]['label']} için ACL numarası geçersiz.")
            if family == "comware_1950" and profile.number is None:
                raise ValueError("HP 1950 için ACL numarasını girin.")
            if profile.name is None and profile.number is None:
                raise ValueError(f"{FAMILIES[family]['label']} için ACL adı veya numarası girin.")
            if family == "aos_switch" and profile.name is not None and profile.number is not None:
                raise ValueError("ArubaOS-Switch için ACL adı veya numarasından birini girin.")
        return self


def canonical(address):
    if "%" in address:
        raise ValueError("Bir IPv4 veya IPv6 adresi girin.")
    try:
        return str(ip_address(address.strip()))
    except ValueError:
        raise ValueError("Bir IPv4 veya IPv6 adresi girin.") from None


def future(value):
    if value is not None:
        if value.tzinfo is None:
            raise ValueError("Bitiş zamanı saat dilimi içermelidir.")
        if value <= now():
            raise ValueError("Bitiş zamanı gelecekte olmalıdır.")
    return value


class EntryInput(Input):
    address: str = Field(min_length=1, max_length=45)
    description: str = Field(default="", max_length=300)
    group_ids: list[ID] = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None

    @field_validator("address")
    @classmethod
    def canonical_address(cls, value):
        return canonical(value)

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value):
        return future(value)


class BulkEntryInput(Input):
    addresses: list[Annotated[str, StringConstraints(min_length=1, max_length=45)]] = Field(
        min_length=1, max_length=500
    )
    description: str = Field(default="", max_length=300)
    group_ids: list[ID] = Field(min_length=1, max_length=100)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value):
        return future(value)


class EntryAction(Input):
    action: Literal["send", "remove", "delete"]
    entry_ids: list[ID] = Field(min_length=1, max_length=500)


class DeviceSync(Input):
    device_ids: list[ID] = Field(min_length=1, max_length=1000)


def catalog():
    return {
        family: {
            "label": data["label"],
            "types": [
                {"id": kind, "label": label, "number_range": NUMBER_RANGES.get((family, kind))}
                for kind, label in data["types"].items()
            ],
        }
        for family, data in FAMILIES.items()
    }


def eligible_inventory():
    return (
        select(m.Device)
        .options(lazyload(m.Device.device_type))
        .where(
            m.Device.adapter.in_(ADAPTERS),
            m.Device.kind.not_in(("firewall", "router")),
            m.Device.is_gateway.is_(False),
            m.Device.is_vip.is_(False),
            m.Device.archived.is_(False),
            m.Device.lifecycle_status == "active",
        )
    )


def device_family(device):
    if device.adapter == "aruba_7200" and not re.search(r"\b7205\b", device.model, re.I):
        return None
    if device.adapter == "aruba_2900" and model_branch(device) != "WC":
        return None
    if device.adapter == "aruba_5400" and not (
        model_branch(device) in ("K", "KB") or re.search(r"\b54(?:06|12)(?:R|ZL2?)?\b", device.model, re.I)
    ):
        return None
    if device.adapter == "aruba_6100" and not (
        model_branch(device) == "PL" or re.search(r"\b6100\b", device.model, re.I)
    ):
        return None
    if device.adapter == "hp_1950" and not (
        model_branch(device) in ("R35", "R51") or re.search(r"\b1950\b", device.model, re.I)
    ):
        return None
    return ADAPTERS.get(device.adapter)


def inventory_choices(db):
    devices = db.scalars(eligible_inventory().order_by(m.Device.name, m.Device.id))
    return [
        {
            "id": device.id,
            "name": device.name,
            "management_ip": device.management_ip,
            "model": device.model,
            "family": family,
        }
        for device in devices
        if (family := device_family(device)) is not None
    ]


def group_view(row, ids):
    return {
        "id": row.id,
        "name": row.name,
        "profiles": row.profiles,
        "device_ids": sorted(ids),
        "status": row.status or "active",
    }


def entry_view(row, ids):
    return {
        "id": row.id,
        "address": row.address,
        "description": row.description,
        "group_ids": sorted(ids),
        "status": row.status or "draft",
        "expires_at": row.expires_at,
        "updated_at": row.updated_at,
    }


def save_group(db, user, payload, group_id=None):
    row = get(db, m.ACLGroup, group_id) if group_id else m.ACLGroup(status="active")
    if row.status == "deleting":
        raise HTTPException(409, "Silinmekte olan grup düzenlenemez.")
    device_ids = set(payload.device_ids)
    selected = db.scalars(eligible_inventory().where(m.Device.id.in_(device_ids)))
    families = {device.id: device_family(device) for device in selected}
    if families.keys() != device_ids or not all(families.values()):
        raise HTTPException(422, "Seçim yalnızca uygun ve aktif envanter cihazlarını içerebilir.")
    if set(families.values()) != payload.profiles.keys():
        raise HTTPException(422, "Seçili her cihaz ailesi için ACL bilgisi girin.")
    if db.scalar(
        select(m.ACLGroup.id).where(m.ACLGroup.name == payload.name, m.ACLGroup.id != (group_id or ""))
    ):
        raise HTTPException(409, "Bu grup adı zaten kullanılıyor.")

    row.name = payload.name
    row.profiles = {family: profile.model_dump() for family, profile in payload.profiles.items()}
    row.updated_at = now()
    db.add(row)
    db.flush()
    db.execute(delete(m.ACLGroupDevice).where(m.ACLGroupDevice.group_id == row.id))
    db.add_all(m.ACLGroupDevice(group_id=row.id, device_id=device_id) for device_id in sorted(device_ids))
    audit(
        db, user, "update" if group_id else "create", "acl_groups", row.id, "Kara Liste ACL grubu kaydedildi"
    )
    db.commit()
    return group_view(row, device_ids)


def save_entry(db, user, payload, entry_id=None, *, commit=True):
    from .state import devices_holding

    row = get(db, m.BlacklistEntry, entry_id) if entry_id else m.BlacklistEntry(status="draft")
    if row.status == "deleting":
        raise HTTPException(409, "Silinmekte olan IP kaydı düzenlenemez.")
    group_ids = set(payload.group_ids)
    found = set(
        db.scalars(
            select(m.ACLGroup.id).where(m.ACLGroup.id.in_(group_ids), m.ACLGroup.status == "active")
        )
    )
    if found != group_ids:
        raise HTTPException(422, "Seçili ACL gruplarından biri bulunamadı veya silinmekte.")
    if db.scalar(
        select(m.BlacklistEntry.id).where(
            m.BlacklistEntry.address == payload.address,
            m.BlacklistEntry.id != (entry_id or ""),
        )
    ):
        raise HTTPException(409, "Bu IP için bir kayıt var. Grup seçimini mevcut kayıttan düzenleyin.")
    if row.id and row.address != payload.address and (
        row.status == "active" or devices_holding(db, address=row.address)
    ):
        raise HTTPException(
            409, "Cihazlara uygulanmış IP değiştirilemez. Önce kaldırın veya yeni adres için ayrı kayıt oluşturun."
        )
    row.address = payload.address
    row.description = payload.description
    row.expires_at = payload.expires_at
    row.updated_by = user.id
    row.updated_at = now()
    db.add(row)
    db.flush()
    db.execute(delete(m.BlacklistEntryGroup).where(m.BlacklistEntryGroup.entry_id == row.id))
    db.add_all(m.BlacklistEntryGroup(entry_id=row.id, group_id=group_id) for group_id in sorted(group_ids))
    audit(
        db,
        user,
        "update" if entry_id else "create",
        "blacklist_entries",
        row.id,
        "Kara Liste IP kaydı kaydedildi",
    )
    if commit:
        db.commit()
    return entry_view(row, group_ids)


def preview_entry(db, entry_id):
    entry = get(db, m.BlacklistEntry, entry_id)
    groups = db.scalars(
        select(m.ACLGroup)
        .join(m.BlacklistEntryGroup)
        .where(m.BlacklistEntryGroup.entry_id == entry.id, m.ACLGroup.status == "active")
        .order_by(m.ACLGroup.name, m.ACLGroup.id)
    ).all()
    group_ids = [group.id for group in groups]
    members = db.execute(
        select(m.ACLGroupDevice.group_id, m.Device.id, m.Device.name, m.Device.management_ip, m.Device.model)
        .join(m.Device, m.Device.id == m.ACLGroupDevice.device_id)
        .where(m.ACLGroupDevice.group_id.in_(group_ids))
        .order_by(m.Device.name, m.Device.id)
    ).all()
    devices = {
        device.id: device_family(device)
        for device in db.scalars(eligible_inventory().where(m.Device.id.in_({row.id for row in members})))
    }
    profiles = {group.id: group.profiles for group in groups}
    targets = {}
    for member in members:
        family = devices.get(member.id)
        profile = profiles[member.group_id].get(family) if family else None
        acl_key = (profile["type"], profile["name"], profile["number"]) if profile else None
        issue = ""
        if not family:
            issue = "Cihaz artık aktif ve uygun bir hedef değil."
        elif not profile:
            issue = "Cihaz ailesinin ACL bilgisi eksik."
        elif ":" in entry.address:
            issue = "IPv6 için ayrı ACL profili gerekir."
        target = targets.setdefault(
            (member.id, acl_key),
            {
                "device_id": member.id,
                "name": member.name,
                "management_ip": member.management_ip,
                "model": member.model,
                "profile": profile,
                "group_ids": [],
                "issue": issue,
            },
        )
        target["group_ids"].append(member.group_id)
    return {
        "address": entry.address,
        "action": "deny",
        "groups": [{"id": group.id, "name": group.name} for group in groups],
        "targets": list(targets.values()),
    }
