"""Manual passive cabling records and reverse inventory references; no network I/O."""

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import aliased

from .. import models as m
from ..identity.security import audit
from ..services import get, publish, serialize
from .racks import check_space, lock_cabinet

CABLES = {"cat": {"Cat5", "Cat6", "Cat7"}, "fiber": {"OM3", "OM4", "Multimode MM", "Singlemode SM"}}


def panel_in(db, cabinet_id, panel_id, *, lock=False):
    panel = db.scalar(
        select(m.PatchPanel)
        .where(m.PatchPanel.id == panel_id, m.PatchPanel.cabinet_id == cabinet_id)
        .with_for_update()
        if lock
        else select(m.PatchPanel).where(m.PatchPanel.id == panel_id, m.PatchPanel.cabinet_id == cabinet_id)
    )
    if not panel:
        raise HTTPException(404, "Patch panel bu kabinette bulunamadı")
    return panel


def save_panel(db, cabinet_id, payload, user, panel_id=None):
    cabinet = lock_cabinet(db, cabinet_id)
    panel = panel_in(db, cabinet_id, panel_id, lock=True) if panel_id else m.PatchPanel(cabinet_id=cabinet_id)
    check_space(db, cabinet, payload.start_unit, payload.units, panel_id=panel_id)
    duplicate = select(m.PatchPanel.id).where(
        m.PatchPanel.cabinet_id == cabinet_id, func.lower(m.PatchPanel.name) == payload.name.lower()
    )
    if panel_id:
        duplicate = duplicate.where(m.PatchPanel.id != panel_id)
    if db.scalar(duplicate.limit(1)):
        raise HTTPException(409, "Bu kabinette aynı adlı patch panel var")
    ports = list(db.scalars(select(m.PatchPort).where(m.PatchPort.panel_id == panel_id))) if panel_id else []
    for port in ports:
        if port.cable_model and port.cable_model not in CABLES[payload.kind]:
            raise HTTPException(409, "Panel türünü değiştirmeden önce uyumsuz kablo kayıtlarını düzenleyin")
        if port.position > payload.port_count and (
            port.device_name or port.port_name or port.cable_model or port.number != str(port.position)
        ):
            raise HTTPException(
                409, "Port sayısını azaltmadan önce kaldırılacak portların bilgilerini temizleyin"
            )
    for key, value in payload.model_dump().items():
        setattr(panel, key, value)
    db.add(panel)
    db.flush()
    for port in ports:
        if port.position > payload.port_count:
            db.delete(port)
    # A renamed number can collide with a new sequential port; reject atomically.
    existing = {p.number.casefold() for p in ports if p.position <= payload.port_count}
    for position in range(len(ports) + 1, payload.port_count + 1):
        if str(position).casefold() in existing:
            raise HTTPException(409, "Yeni port numarası mevcut bir port etiketiyle çakışıyor")
        db.add(m.PatchPort(panel_id=panel.id, position=position, number=str(position)))
    audit(
        db,
        user,
        "patch_panel_save",
        "cabinets",
        cabinet_id,
        f"{panel.name}: {panel.start_unit} U, {panel.port_count} port",
    )
    db.commit()
    publish()
    return serialize(panel)


def port_query():
    interface = aliased(m.Interface)
    return (
        select(m.PatchPort, m.Device.name.label("linked_device"), interface.name.label("linked_port"))
        .outerjoin(m.Device, m.Device.id == m.PatchPort.device_id)
        .outerjoin(interface, interface.id == m.PatchPort.interface_id)
    )


def port_item(row):
    port, device_name, port_name = row
    return {
        **serialize(port),
        "device_name": device_name or port.device_name,
        "port_name": port_name or port.port_name,
    }


def ports(db, cabinet_id, panel_id):
    panel = panel_in(db, cabinet_id, panel_id)
    return {
        "panel": serialize(panel),
        "items": [
            port_item(r)
            for r in db.execute(
                port_query().where(m.PatchPort.panel_id == panel_id).order_by(m.PatchPort.position)
            )
        ],
    }


def save_port(db, cabinet_id, panel_id, port_id, payload, user):
    lock_cabinet(db, cabinet_id)
    panel = panel_in(db, cabinet_id, panel_id, lock=True)
    port = db.scalar(
        select(m.PatchPort)
        .where(m.PatchPort.id == port_id, m.PatchPort.panel_id == panel_id)
        .with_for_update()
    )
    if not port:
        raise HTTPException(404, "Port bu patch panelde bulunamadı")
    if payload.cable_model and payload.cable_model not in CABLES[panel.kind]:
        raise HTTPException(422, "Kablo modeli panel türüne uygun değil")
    if db.scalar(
        select(m.PatchPort.id)
        .where(
            m.PatchPort.panel_id == panel_id,
            m.PatchPort.id != port_id,
            func.lower(m.PatchPort.number) == payload.number.lower(),
        )
        .limit(1)
    ):
        raise HTTPException(409, "Bu panelde aynı port numarası var")
    device = get(db, m.Device, payload.device_id) if payload.device_id else None
    if not device and payload.device_name:
        matches = list(
            db.scalars(
                select(m.Device)
                .where(
                    m.Device.archived.is_(False),
                    m.Device.discovery_scope_id.is_not(None),
                    or_(
                        func.lower(m.Device.name) == payload.device_name.lower(),
                        m.Device.management_ip == payload.device_name,
                    ),
                )
                .limit(2)
            )
        )
        if len(matches) == 1:
            device = matches[0]
    if device and (device.archived or not device.discovery_scope_id):
        raise HTTPException(422, "Aktif cihaz envanterinden bir cihaz seçin")
    interface = get(db, m.Interface, payload.interface_id) if payload.interface_id else None
    if interface and (not device or interface.device_id != device.id or interface.is_deleted):
        raise HTTPException(422, "Port seçilen cihaza ait ve aktif olmalı")
    if device and not interface and payload.port_name:
        interface = db.scalar(
            select(m.Interface)
            .where(
                m.Interface.device_id == device.id,
                m.Interface.is_deleted.is_(False),
                func.lower(m.Interface.name) == payload.port_name.lower(),
            )
            .limit(1)
        )
    if (interface or payload.port_name) and not (device or payload.device_name):
        raise HTTPException(422, "Port bilgisi için bağlı cihazı da girin")
    port.number = payload.number
    port.device_id = device.id if device else None
    port.interface_id = interface.id if interface else None
    port.device_name = device.name if device else payload.device_name
    port.port_name = interface.name if interface else payload.port_name
    port.cable_model = payload.cable_model
    audit(
        db,
        user,
        "patch_port_save",
        "cabinets",
        cabinet_id,
        f"{panel.name} / {port.number}: manuel bağlantı kaydı",
    )
    db.commit()
    publish()
    return port_item(db.execute(port_query().where(m.PatchPort.id == port_id)).one())


def remove_panel(db, cabinet_id, panel_id, user):
    lock_cabinet(db, cabinet_id)
    panel = panel_in(db, cabinet_id, panel_id, lock=True)
    db.execute(delete(m.PatchPort).where(m.PatchPort.panel_id == panel_id))
    db.delete(panel)
    audit(
        db, user, "patch_panel_delete", "cabinets", cabinet_id, "Patch panel ve port bağlantıları kaldırıldı"
    )
    db.commit()
    publish()


def device_ports(db, device_id):
    get(db, m.Device, device_id)
    rows = db.execute(
        select(m.PatchPort, m.PatchPanel, m.Cabinet)
        .join(m.PatchPanel, m.PatchPort.panel_id == m.PatchPanel.id)
        .join(m.Cabinet, m.Cabinet.id == m.PatchPanel.cabinet_id)
        .where(m.PatchPort.device_id == device_id)
        .order_by(m.Cabinet.name, m.PatchPanel.start_unit.desc(), m.PatchPort.position)
    ).all()
    interfaces = (
        dict(
            db.execute(
                select(m.Interface.id, m.Interface.name).where(
                    m.Interface.id.in_({p.interface_id for p, _, _ in rows if p.interface_id})
                )
            ).all()
        )
        if rows
        else {}
    )
    return {
        "items": [
            {
                "id": p.id,
                "cabinet_id": c.id,
                "cabinet_name": c.name,
                "panel_id": panel.id,
                "panel_name": panel.name,
                "kind": panel.kind,
                "start_unit": panel.start_unit,
                "units": panel.units,
                "number": p.number,
                "port_name": interfaces.get(p.interface_id, p.port_name),
                "cable_model": p.cable_model,
            }
            for p, panel, c in rows
        ]
    }
