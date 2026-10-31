"""Cabinet elevation backed by central inventory and validated U placements."""

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..identity.security import audit
from ..services import get, publish, serialize
from .model_images import model_image


def detail(db, id):
    cabinet = get(db, m.Cabinet, id)
    rows = db.scalars(
        select(m.RackPlacement)
        .where(m.RackPlacement.cabinet_id == id)
        .order_by(m.RackPlacement.start_unit.desc())
    ).all()
    placements = []
    for row in rows:
        device = get(db, m.Device, row.device_id)
        placements.append(
            {
                **serialize(row),
                "device": {
                    k: getattr(device, k)
                    for k in ("id", "name", "management_ip", "vendor", "model", "reachability", "archived")
                },
                "image": model_image(db, device.vendor, device.model),
            }
        )
    return {**serialize(cabinet), "placements": placements}


def lock_cabinet(db, id):
    row = db.scalar(select(m.Cabinet).where(m.Cabinet.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "Kabinet bulunamadı")
    row.lock_version += 1
    db.flush()
    return row


def place(db, id, payload, user):
    cabinet = lock_cabinet(db, id)
    device = get(db, m.Device, payload.device_id)
    if device.archived:
        raise HTTPException(422, "Arşivlenen cihaz kabinete yerleştirilemez")
    end = payload.start_unit + payload.units - 1
    if end > cabinet.units:
        raise HTTPException(422, "Cihaz kabinet kapasitesini aşıyor")
    previous = db.scalar(select(m.RackPlacement).where(m.RackPlacement.device_id == device.id))
    if previous and previous.cabinet_id != id:
        raise HTTPException(409, "Cihaz başka bir kabinet içinde; önce mevcut yerleşimden çıkarın")
    for row in db.scalars(
        select(m.RackPlacement).where(
            m.RackPlacement.cabinet_id == id, m.RackPlacement.device_id != device.id
        )
    ):
        if payload.start_unit <= row.start_unit + row.units - 1 and end >= row.start_unit:
            raise HTTPException(409, "Seçilen U alanı başka bir cihaz tarafından kullanılıyor")
    row = previous or m.RackPlacement(cabinet_id=id, device_id=device.id)
    row.start_unit, row.units = payload.start_unit, payload.units
    db.add(row)
    db.flush()
    audit(db, user, "rack_place", "cabinets", id, f"{device.name}: {payload.start_unit}–{end} U")
    db.commit()
    publish()
    return detail(db, id)


def unplace(db, id, device_id, user):
    lock_cabinet(db, id)
    row = db.scalar(
        select(m.RackPlacement).where(
            m.RackPlacement.cabinet_id == id, m.RackPlacement.device_id == device_id
        )
    )
    if not row:
        raise HTTPException(404, "Yerleşim bulunamadı")
    db.delete(row)
    audit(db, user, "rack_unplace", "cabinets", id, "Cihaz yerleşimi kaldırıldı; envanter korundu")
    db.commit()
    publish()
