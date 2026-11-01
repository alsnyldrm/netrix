from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from .. import models as m
from .. import services as svc
from ..core import db_session
from ..identity.security import admin, audit, current_user, operator
from . import read_cache, service, table
from .schemas import (
    AddressBulkInput,
    IntegrationInput,
    IPPlacementInput,
    ModelImageInput,
    PlacementInput,
    RackAccessoryInput,
    VLANDeleteInput,
    VLANSelection,
    VLANSettings,
)

router = APIRouter(prefix="/api/v1")


@router.get("/ipam/vlans/{id}/addresses")
def addresses(
    request: Request,
    id: str,
    offset: str = "0",
    limit: int = Query(100, ge=1, le=200),
    allocated: bool = False,
    active_only: bool = False,
    q: str = Query("", max_length=200),
    filters: str = Query("[]", max_length=12000),
    user=Depends(current_user),
    db=Depends(db_session),
):
    if not offset.isdigit() or len(offset) > 40:
        raise HTTPException(422, "Geçersiz adres başlangıcı")
    return read_cache.json_response(
        ["vlan-addresses", id, offset, limit, allocated, active_only, q, filters],
        lambda: table.addresses(
            db,
            svc.get(db, m.VLAN, id),
            offset=int(offset),
            limit=limit,
            allocated=allocated,
            active_only=active_only,
            q=q,
            filters=filters,
        ),
        force="no-cache" in request.headers.get("cache-control", "").lower(),
    )


@router.post("/ipam/vlans/delete-preview")
def vlan_delete_preview(payload: VLANSelection, user=Depends(admin), db=Depends(db_session)):
    from .vlan_deletion import preview

    return preview(db, payload.ids)


@router.post("/ipam/vlans/bulk-delete")
def vlan_bulk_delete(payload: VLANDeleteInput, user=Depends(admin), db=Depends(db_session)):
    from .vlan_deletion import remove

    return remove(db, payload.ids, user, payload.confirmation)


@router.put("/ipam/vlans/{id}/settings")
def settings(id: str, payload: VLANSettings, user=Depends(operator), db=Depends(db_session)):
    return service.save_settings(db, id, payload, user)


@router.post("/ipam/vlans/{id}/{action}", status_code=202)
def scan(id: str, action: Literal["ping", "discover"], user=Depends(operator), db=Depends(db_session)):
    return svc.serialize(svc.enqueue(db, "ipam_" + action, id, user))


@router.get("/ipam/vlans/{id}/scan")
def scan_status(id: str, user=Depends(current_user), db=Depends(db_session)):
    svc.get(db, m.VLAN, id)
    job = db.scalar(
        select(m.Job)
        .where(m.Job.target_id == id, m.Job.kind == "ipam_discover")
        .order_by(m.Job.created_at.desc(), m.Job.id.desc())
        .limit(1)
    )
    return svc.serialize(job) if job else None


@router.post("/integrations", status_code=201)
def create(payload: IntegrationInput, user=Depends(admin), db=Depends(db_session)):
    return service.save_integration(db, payload, user)


@router.put("/integrations/{id}")
def update(id: str, payload: IntegrationInput, user=Depends(admin), db=Depends(db_session)):
    return service.save_integration(db, payload, user, id)


@router.delete("/integrations/{id}", status_code=204)
def remove(id: str, user=Depends(admin), db=Depends(db_session)):
    row = svc.get(db, m.Integration, id)
    if db.scalar(select(m.Job.id).where(m.Job.target_id == id, m.Job.active_key.is_not(None))):
        raise HTTPException(409, "Önce çalışan eşitleme görevini iptal edin")
    db.delete(row)
    audit(db, user, "delete", "integrations", id, "Entegrasyon silindi; IP gözlem geçmişi korundu")
    db.commit()
    svc.publish()


@router.post("/integrations/{id}/sync", status_code=202)
def sync(id: str, user=Depends(admin), db=Depends(db_session)):
    return svc.serialize(svc.enqueue(db, "integration", id, user))


@router.get("/ipam/addresses/{id}")
def detail(id: str, request: Request, user=Depends(current_user), db=Depends(db_session)):
    return read_cache.json_response(
        ["address-detail", id],
        lambda: service.enrich(db, [svc.get(db, m.IPAddress, id)], include_options=True)[0],
        force="no-cache" in request.headers.get("cache-control", "").lower(),
    )


@router.post("/ipam/addresses/bulk")
def address_bulk(payload: AddressBulkInput, user=Depends(operator), db=Depends(db_session)):
    return table.bulk(db, payload, user)


@router.get("/ipam/cabinets/{id}")
def cabinet_detail(id: str, user=Depends(current_user), db=Depends(db_session)):
    from .racks import detail

    return detail(db, id)


@router.put("/ipam/cabinets/{id}/placements")
def cabinet_place(id: str, payload: PlacementInput, user=Depends(operator), db=Depends(db_session)):
    from .racks import place

    return place(db, id, payload, user)


@router.delete("/ipam/cabinets/{id}/placements/{device_id}", status_code=204)
def cabinet_unplace(id: str, device_id: str, user=Depends(operator), db=Depends(db_session)):
    from .racks import unplace

    unplace(db, id, device_id, user)


@router.post("/ipam/cabinets/{id}/placements/from-ip")
def cabinet_place_from_ip(id: str, payload: IPPlacementInput, user=Depends(operator), db=Depends(db_session)):
    from .racks import place_from_ip

    return place_from_ip(db, id, payload, user)


@router.get("/ipam/devices/{id}/model-image")
def model_image_get(id: str, user=Depends(current_user), db=Depends(db_session)):
    from .model_images import model_image

    device = svc.get(db, m.Device, id)
    return model_image(db, device.vendor, device.model) or {"url": "", "source": ""}


@router.post("/ipam/cabinets/{id}/accessories", status_code=201)
def accessory_create(id: str, payload: RackAccessoryInput, user=Depends(operator), db=Depends(db_session)):
    from .racks import save_accessory

    return save_accessory(db, id, payload, user)


@router.put("/ipam/cabinets/{id}/accessories/{accessory_id}")
def accessory_update(
    id: str, accessory_id: str, payload: RackAccessoryInput, user=Depends(operator), db=Depends(db_session)
):
    from .racks import save_accessory

    return save_accessory(db, id, payload, user, accessory_id)


@router.delete("/ipam/cabinets/{id}/accessories/{accessory_id}", status_code=204)
def accessory_delete(id: str, accessory_id: str, user=Depends(operator), db=Depends(db_session)):
    from .racks import remove_accessory

    remove_accessory(db, id, accessory_id, user)


@router.put("/ipam/devices/{id}/model-image")
def model_image_save(id: str, payload: ModelImageInput, user=Depends(operator), db=Depends(db_session)):
    from .model_images import save_image

    return save_image(db, id, payload, user)
