"""Firmware candidate filters, bounded selection and exclusive group ownership."""

from typing import Literal

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import lazyload

from .. import models as m
from ..identity.security import audit
from ..services import get, publish, serialize
from . import catalog
from .service import FAMILIES, Input, compatible, transfer_protocol


class DeviceFilters(Input):
    q: str = Field(default="", max_length=120)
    family: Literal["", "aos_s", "cx6100", "hp1950"] = ""
    model: str = Field(default="", max_length=100)
    vendor: str = Field(default="", max_length=80)
    version: str = Field(default="", max_length=120)
    ip_prefix: str = Field(default="", max_length=45)
    scope_id: str = Field(default="", max_length=36)
    site_id: str = Field(default="", max_length=36)
    assignment: Literal["any", "available", "assigned"] = "any"
    editing_group_id: str = Field(default="", max_length=36)
    update_status: Literal["", "current", "outdated", "unknown", "no_image"] = ""


def base_conditions():
    return [
        m.Device.archived.is_(False),
        m.Device.discovery_scope_id.is_not(None),
        m.Device.adapter.in_(FAMILIES),
    ]


def selectable(group_id):
    membership = select(m.FirmwareMember.device_id).where(m.FirmwareMember.device_id == m.Device.id)
    if group_id:
        membership = membership.where(m.FirmwareMember.group_id != group_id)
    return ~membership.exists()


def conditions(db, filters, group_id=""):
    result = base_conditions()
    if filters.editing_group_id:
        get(db, m.FirmwareGroup, filters.editing_group_id)
    if filters.q:
        result.append(
            or_(
                *(
                    column.contains(filters.q, autoescape=True)
                    for column in (m.Device.name, m.Device.management_ip, m.Device.model, m.Device.vendor)
                )
            )
        )
    if filters.family:
        result.append(m.Device.adapter.in_([a for a, f in FAMILIES.items() if f == filters.family]))
    for value, column in (
        (filters.model, m.Device.model),
        (filters.vendor, m.Device.vendor),
        (filters.version, m.Device.software_version),
    ):
        if value:
            result.append(column.contains(value, autoescape=True))
    if filters.ip_prefix:
        result.append(m.Device.management_ip.startswith(filters.ip_prefix, autoescape=True))
    if filters.scope_id:
        result.append(m.Device.discovery_scope_id == filters.scope_id)
    if filters.site_id:
        result.append(m.Device.site_id == filters.site_id)
    if filters.assignment == "available":
        result.append(selectable(filters.editing_group_id))
    elif filters.assignment == "assigned":
        result.append(
            select(m.FirmwareMember.device_id).where(m.FirmwareMember.device_id == m.Device.id).exists()
        )
    if group_id:
        result.append(
            select(m.FirmwareMember.device_id)
            .where(m.FirmwareMember.device_id == m.Device.id, m.FirmwareMember.group_id == group_id)
            .exists()
        )
    return result


def candidates(db, filters, *, limit=50, offset=0, group_id="", image_id=None):
    where = conditions(db, filters, group_id)
    updates = catalog.statuses(db, where) if filters.update_status else None
    if filters.update_status:
        where.append(
            m.Device.id.in_(
                [id for id, value in updates.items() if value["update_status"] == filters.update_status]
            )
        )
    rows = list(
        db.scalars(
            select(m.Device)
            .options(lazyload(m.Device.device_type))
            .where(*where)
            .order_by(m.Device.name, m.Device.id)
            .limit(limit)
            .offset(offset)
        )
    )
    if updates is None:
        updates = catalog.statuses(db, [m.Device.id.in_([d.id for d in rows])])
    owners = dict(
        db.execute(
            select(m.FirmwareMember.device_id, m.FirmwareGroup)
            .join(m.FirmwareGroup, m.FirmwareGroup.id == m.FirmwareMember.group_id)
            .where(m.FirmwareMember.device_id.in_([d.id for d in rows]))
        ).all()
    )
    image = get(db, m.FirmwareImage, image_id) if image_id else None
    return {
        "items": [
            {
                "id": d.id,
                "name": d.name,
                "management_ip": d.management_ip,
                "model": d.model,
                "vendor": d.vendor,
                "software_version": d.software_version,
                "family": FAMILIES[d.adapter],
                "protocol": transfer_protocol(FAMILIES[d.adapter]),
                "compatible": compatible(image, d) if image else None,
                "firmware_group_id": owners[d.id].id if d.id in owners else None,
                "firmware_group_name": owners[d.id].name if d.id in owners else None,
                "selectable": d.id not in owners or owners[d.id].id == filters.editing_group_id,
                **updates[d.id],
            }
            for d in rows
        ],
        "total": db.scalar(select(func.count()).select_from(m.Device).where(*where)),
        "selectable_total": db.scalar(
            select(func.count()).select_from(m.Device).where(*where, selectable(filters.editing_group_id))
        ),
    }


def selection(db, filters):
    where = conditions(db, filters)
    if filters.update_status:
        updates = catalog.statuses(db, where)
        where.append(
            m.Device.id.in_(
                [id for id, row in updates.items() if row["update_status"] == filters.update_status]
            )
        )
    ids = list(
        db.scalars(
            select(m.Device.id)
            .where(*where, selectable(filters.editing_group_id))
            .order_by(m.Device.name, m.Device.id)
            .limit(1001)
        )
    )
    if len(ids) > 1000:
        raise HTTPException(422, "Bir firmware grubuna en fazla 1000 cihaz seçilebilir. Filtreyi daraltın.")
    return {"device_ids": ids, "total": len(ids)}


def filter_options(db):
    base = base_conditions()
    result = {
        name: list(
            db.scalars(select(column).where(*base, column != "").distinct().order_by(column).limit(500))
        )
        for name, column in (
            ("models", m.Device.model),
            ("vendors", m.Device.vendor),
            ("versions", m.Device.software_version),
        )
    }
    result["scopes"] = [
        {"id": s.id, "name": s.name, "vid": s.vlan_vid, "cidr": s.cidr}
        for s in db.scalars(
            select(m.Scope)
            .where(m.Scope.id.in_(select(m.Device.discovery_scope_id).where(*base)))
            .order_by(m.Scope.name)
        )
    ]
    result["sites"] = [
        {"id": s.id, "name": s.name, "code": s.code}
        for s in db.scalars(
            select(m.Site).where(m.Site.id.in_(select(m.Device.site_id).where(*base))).order_by(m.Site.name)
        )
    ]
    return result


def save_group(db, user, payload, row):
    try:
        if row.id:
            row = db.scalar(
                select(m.FirmwareGroup)
                .where(m.FirmwareGroup.id == row.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise HTTPException(404, "Firmware grubu bulunamadı")
        ids = sorted(set(payload.device_ids))
        devices = list(
            db.scalars(
                select(m.Device)
                .options(lazyload(m.Device.device_type))
                .where(m.Device.id.in_(ids))
                .order_by(m.Device.id)
                .with_for_update()
            )
        )
        if len(devices) != len(ids):
            raise HTTPException(404, "Seçilen cihazlardan biri artık envanterde bulunmuyor")
        if any(d.archived or not d.discovery_scope_id or d.adapter not in FAMILIES for d in devices):
            raise HTTPException(422, "Yalnız desteklenen aktif envanter cihazları gruba eklenebilir")
        conflict = db.execute(
            select(m.FirmwareMember.device_id, m.FirmwareMember.group_id)
            .where(m.FirmwareMember.device_id.in_(ids), m.FirmwareMember.group_id != row.id)
            .with_for_update()
        ).first()
        if conflict:
            device = next(d for d in devices if d.id == conflict.device_id)
            # A competing owner can have committed after the consistent-read
            # snapshot. Ownership came from a locking read; a missing display
            # name still means a conflict, not a missing device/group.
            owner = db.scalar(select(m.FirmwareGroup.name).where(m.FirmwareGroup.id == conflict.group_id))
            message = (
                f"{device.name}, ‘{owner}’ grubuna ait."
                if owner
                else f"{device.name} zaten başka bir firmware grubuna ait."
            )
            raise HTTPException(409, message + " Önce mevcut grubundan çıkarın.")
        row.name, row.description = payload.name, payload.description
        db.add(row)
        db.flush()
        db.execute(delete(m.FirmwareMember).where(m.FirmwareMember.group_id == row.id))
        db.add_all(m.FirmwareMember(group_id=row.id, device_id=id) for id in ids)
        audit(
            db,
            user,
            "update",
            "firmware_groups",
            row.id,
            "Firmware grubu ve tekil cihaz üyelikleri kaydedildi",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "Grup adı veya cihaz üyeliği başka bir işlemde değişti. Güncel listeyi kontrol edin."
        ) from None
    except OperationalError as exc:
        db.rollback()
        if getattr(exc.orig, "args", (None,))[0] not in (1020, 1205, 1213):
            raise
        raise HTTPException(
            409, "Cihaz üyeliği eşzamanlı bir işlemde değişti. Güncel listeyi kontrol edin."
        ) from None
    except HTTPException:
        db.rollback()
        raise
    publish()
    return {**serialize(row), "device_ids": ids}
