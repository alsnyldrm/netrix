"""Cabinet elevation backed by central inventory and validated U placements."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from .. import models as m
from ..identity.security import audit
from ..services import get, publish, serialize
from .model_images import model_images


def address_cabinets(db, rows):
    """Resolve the endpoint's own rack, not the switch referenced by device_id."""
    if not rows:
        return {}
    placements = db.execute(
        select(
            m.IPAddress.id,
            m.Site.floor_number,
            m.Site.department_name,
            m.Cabinet.name,
            m.RackPlacement.start_unit,
        )
        .join(
            m.Device,
            (m.Device.vrf_id == m.IPAddress.vrf_id) & (m.Device.management_ip == m.IPAddress.address),
        )
        .join(m.RackPlacement, m.RackPlacement.device_id == m.Device.id)
        .join(m.Cabinet, m.Cabinet.id == m.RackPlacement.cabinet_id)
        .outerjoin(m.Site, m.Site.id == m.Cabinet.sub_site_id)
        .where(m.IPAddress.id.in_([r.id for r in rows]), m.Device.archived.is_(False))
    ).all()
    return {
        address_id: f"{floor or '—'}/{department or '—'}/{cabinet}/{unit}U"
        for address_id, floor, department, cabinet, unit in placements
    }


def detail(db, id):
    cabinet = get(db, m.Cabinet, id)
    rows = db.scalars(
        select(m.RackPlacement)
        .where(m.RackPlacement.cabinet_id == id)
        .order_by(m.RackPlacement.start_unit.desc())
    ).all()
    devices = {
        d.id: d for d in db.scalars(select(m.Device).where(m.Device.id.in_({r.device_id for r in rows})))
    }
    images = model_images(db, list(devices.values()))
    placements = []
    for row in rows:
        device = devices[row.device_id]
        placements.append(
            {
                **serialize(row),
                "device": {
                    k: getattr(device, k)
                    for k in (
                        "id",
                        "name",
                        "management_ip",
                        "vrf_id",
                        "kind",
                        "vendor",
                        "model",
                        "reachability",
                        "archived",
                    )
                },
                "image": images[device.id],
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
        "patch_panels": [
            serialize(p)
            for p in db.scalars(
                select(m.PatchPanel)
                .where(m.PatchPanel.cabinet_id == id)
                .order_by(m.PatchPanel.start_unit.desc())
            )
        ],
    }


def lock_cabinet(db, id):
    row = db.scalar(select(m.Cabinet).where(m.Cabinet.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "Kabinet bulunamadı")
    row.lock_version += 1
    db.flush()
    return row


def check_space(db, cabinet, start, units, *, device_id=None, accessory_id=None, panel_id=None):
    end = start + units - 1
    if end > cabinet.units:
        raise HTTPException(422, "Yerleşim kabinet kapasitesini aşıyor")
    for model, excluded, column in (
        (m.RackPlacement, device_id, m.RackPlacement.device_id),
        (m.RackAccessory, accessory_id, m.RackAccessory.id),
        (m.PatchPanel, panel_id, m.PatchPanel.id),
    ):
        stmt = select(model.id).where(
            model.cabinet_id == cabinet.id,
            model.start_unit <= end,
            model.start_unit + model.units - 1 >= start,
        )
        if excluded:
            stmt = stmt.where(column != excluded)
        if db.scalar(stmt.limit(1).with_for_update()):
            raise HTTPException(
                409, "Seçilen U alanı başka bir cihaz, organizer veya patch panel tarafından kullanılıyor"
            )


def place(db, id, payload, user):
    cabinet = lock_cabinet(db, id)
    device = get(db, m.Device, payload.device_id)
    if device.archived:
        raise HTTPException(422, "Arşivlenen cihaz kabinete yerleştirilemez")
    end = payload.start_unit + payload.units - 1
    previous = db.scalar(
        select(m.RackPlacement).where(m.RackPlacement.device_id == device.id).with_for_update()
    )
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


def place_from_ip(db, cabinet_id, payload, user):
    # MariaDB/Galera can reject a snapshot read after another placement commits.
    # Retry the entire idempotent transaction once, never just its final write.
    for attempt in range(2):
        try:
            return _place_from_ip(db, cabinet_id, payload, user)
        except OperationalError as exc:
            if not exc.orig.args or exc.orig.args[0] not in (1020, 1205, 1213):
                raise
            db.rollback()
            if attempt:
                raise HTTPException(409, "Eşzamanlı yerleşim değişikliği oldu; yeniden deneyin") from None


def _place_from_ip(db, cabinet_id, payload, user):
    from ..schemas import DeviceInput
    from ..services import lock_vrf
    from .schemas import PlacementInput
    from .service import observations, virtual_connections

    address = get(db, m.IPAddress, payload.address_id)
    # Serialize creation by VRF; an upstream switch in address.device_id is not the endpoint.
    lock_vrf(db, address.vrf_id)
    cabinet = lock_cabinet(db, cabinet_id)
    if virtual_connections(observations(db, [address])[address.id]):
        raise HTTPException(422, "Sanal makine yerine fiziksel sunucunun yönetim IP adresini seçin")
    device = db.scalar(
        select(m.Device)
        .where(m.Device.vrf_id == address.vrf_id, m.Device.management_ip == address.address)
        .with_for_update()
    )
    if not device:
        # Validate the same identity/IP constraints as central inventory, without starting scans.
        try:
            values = DeviceInput(
                name=payload.name,
                kind=payload.kind,
                management_ip=address.address,
                vrf_id=address.vrf_id,
                site_id=cabinet.site_id,
                vendor=payload.vendor,
                model=payload.model,
            )
        except ValueError:
            raise HTTPException(422, "Fiziksel cihaz için geçerli bir yönetim IP adresi gerekli") from None
        if not db.scalar(select(m.DeviceType.id).where(m.DeviceType.code == values.kind)):
            raise HTTPException(422, "Geçerli bir cihaz türü seçin")
        check_space(db, cabinet, payload.start_unit, payload.units)
        device = m.Device(**values.model_dump(), manual_identity_fields=["name", "kind", "vendor", "model"])
        db.add(device)
        db.flush()
        audit(
            db,
            user,
            "create_from_ip",
            "devices",
            device.id,
            f"IPAM üzerinden kabinet cihazı oluşturuldu: {address.address}",
        )
    result = place(
        db,
        cabinet_id,
        PlacementInput(device_id=device.id, start_unit=payload.start_unit, units=payload.units),
        user,
    )
    return {**result, "selected_device_id": device.id}


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
