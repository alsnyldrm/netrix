"""Cabinet elevation backed by central inventory and validated U placements."""

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..identity.security import audit
from ..services import get, publish, serialize
from .model_images import model_image


def address_cabinets(db, rows):
    """Resolve the endpoint's own rack, not the switch referenced by device_id."""
    if not rows:
        return {}
    return dict(
        db.execute(
            select(m.IPAddress.id, m.Cabinet.name)
            .join(
                m.Device,
                (m.Device.vrf_id == m.IPAddress.vrf_id) & (m.Device.management_ip == m.IPAddress.address),
            )
            .join(m.RackPlacement, m.RackPlacement.device_id == m.Device.id)
            .join(m.Cabinet, m.Cabinet.id == m.RackPlacement.cabinet_id)
            .where(m.IPAddress.id.in_([r.id for r in rows]), m.Device.archived.is_(False))
        ).all()
    )


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
    accessories = db.scalars(
        select(m.RackAccessory)
        .where(m.RackAccessory.cabinet_id == id)
        .order_by(m.RackAccessory.start_unit.desc())
    ).all()
    return {
        **serialize(cabinet),
        "placements": placements,
        "accessories": [serialize(a) for a in accessories],
    }


def lock_cabinet(db, id):
    row = db.scalar(select(m.Cabinet).where(m.Cabinet.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "Kabinet bulunamadı")
    row.lock_version += 1
    db.flush()
    return row


def check_space(db, cabinet, start, units, *, device_id=None, accessory_id=None):
    end = start + units - 1
    if end > cabinet.units:
        raise HTTPException(422, "Yerleşim kabinet kapasitesini aşıyor")
    for model, excluded, column in (
        (m.RackPlacement, device_id, m.RackPlacement.device_id),
        (m.RackAccessory, accessory_id, m.RackAccessory.id),
    ):
        stmt = select(model.id).where(
            model.cabinet_id == cabinet.id,
            model.start_unit <= end,
            model.start_unit + model.units - 1 >= start,
        )
        if excluded:
            stmt = stmt.where(column != excluded)
        if db.scalar(stmt.limit(1)):
            raise HTTPException(409, "Seçilen U alanı başka bir cihaz veya organizer tarafından kullanılıyor")


def place(db, id, payload, user):
    cabinet = lock_cabinet(db, id)
    device = get(db, m.Device, payload.device_id)
    if device.archived:
        raise HTTPException(422, "Arşivlenen cihaz kabinete yerleştirilemez")
    end = payload.start_unit + payload.units - 1
    previous = db.scalar(select(m.RackPlacement).where(m.RackPlacement.device_id == device.id))
    if previous and previous.cabinet_id != id:
        raise HTTPException(409, "Cihaz başka bir kabinet içinde; önce mevcut yerleşimden çıkarın")
    check_space(db, cabinet, payload.start_unit, payload.units, device_id=device.id)
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


def save_accessory(db, cabinet_id, payload, user, accessory_id=None):
    cabinet = lock_cabinet(db, cabinet_id)
    row = get(db, m.RackAccessory, accessory_id) if accessory_id else m.RackAccessory(cabinet_id=cabinet_id)
    if row.cabinet_id != cabinet_id:
        raise HTTPException(404, "Organizer bu kabinette bulunamadı")
    check_space(db, cabinet, payload.start_unit, payload.units, accessory_id=accessory_id)
    row.kind, row.start_unit, row.units = payload.kind, payload.start_unit, payload.units
    db.add(row)
    db.flush()
    audit(
        db,
        user,
        "rack_accessory_save",
        "cabinets",
        cabinet_id,
        f"Fırçalı organizer: {row.start_unit} U, {row.units} U yüksekliğinde",
    )
    db.commit()
    publish()
    return serialize(row)


def remove_accessory(db, cabinet_id, accessory_id, user):
    lock_cabinet(db, cabinet_id)
    row = get(db, m.RackAccessory, accessory_id)
    if row.cabinet_id != cabinet_id:
        raise HTTPException(404, "Organizer bu kabinette bulunamadı")
    db.delete(row)
    audit(db, user, "rack_accessory_remove", "cabinets", cabinet_id, "Fırçalı organizer kaldırıldı")
    db.commit()
    publish()
