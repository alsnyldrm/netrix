from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from .. import models as m
from .. import services as svc
from ..core import db_session, now
from ..identity.security import admin, audit, current_user, operator
from . import jobs, read_cache, service, table
from .schemas import (
    AddressBulkInput,
    IntegrationInput,
    LiveInput,
    ModelImageInput,
    PlacementInput,
    PrefixSettings,
)

router = APIRouter(prefix="/api/v1")


@router.get("/ipam/prefixes/{id}/addresses")
def addresses(
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
        ["prefix-addresses", id, offset, limit, allocated, active_only, q, filters],
        lambda: table.addresses(
            db,
            svc.get(db, m.Prefix, id),
            offset=int(offset),
            limit=limit,
            allocated=allocated,
            active_only=active_only,
            q=q,
            filters=filters,
        ),
    )


@router.put("/ipam/prefixes/{id}/settings")
def settings(id: str, payload: PrefixSettings, user=Depends(operator), db=Depends(db_session)):
    return service.save_settings(db, id, payload, user)


@router.post("/ipam/prefixes/{id}/{action}", status_code=202)
def scan(id: str, action: Literal["ping", "discover"], user=Depends(operator), db=Depends(db_session)):
    return svc.serialize(svc.enqueue(db, "ipam_" + action, id, user))


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
def detail(id: str, user=Depends(current_user), db=Depends(db_session)):
    row = svc.get(db, m.IPAddress, id)
    return {**service.enrich(db, [row])[0], **jobs.live_options(db, row)}


@router.get("/ipam/addresses/{id}/traffic")
def traffic(id: str, user=Depends(current_user), db=Depends(db_session)):
    svc.get(db, m.IPAddress, id)
    samples = db.scalars(
        select(m.IPTraffic)
        .where(m.IPTraffic.address_id == id, m.IPTraffic.sampled_at >= now() - timedelta(minutes=15))
        .order_by(m.IPTraffic.sampled_at.desc())
        .limit(180)
    ).all()
    return {"items": [svc.serialize(row) for row in reversed(samples)]}


@router.post("/ipam/addresses/{id}/live", status_code=202)
def live(id: str, payload: LiveInput, user=Depends(operator), db=Depends(db_session)):
    from ..discovery.interactive_tests import CAPACITY, interactive_condition

    row = svc.get(db, m.IPAddress, id)
    selection = payload.model_dump()
    if bool(payload.interface_id) == bool(payload.integration_id):
        raise HTTPException(422, "Tek bir trafik kaynağı seçin")
    try:
        jobs.live_target(db, row, selection)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # Same admission lock/capacity as interactive connection probes; never block scheduled work.
    from redis.exceptions import RedisError

    from ..discovery.interactive_tests import redis_client

    try:
        stamp = redis_client().get("netrix:tests:heartbeat")
        if not stamp or not -5 <= (now() - datetime.fromisoformat(stamp)).total_seconds() < 15:
            raise HTTPException(503, "Canlı izleme worker hizmeti hazır değil; yeniden deneyin")
        with redis_client().lock("netrix:tests:admission", timeout=30, blocking_timeout=0.5):
            job = svc.enqueue(db, "ipam_live", id, user, commit=False)
            if job.result:
                if any(job.result.get(k) != v for k, v in selection.items()):
                    raise HTTPException(409, "Bu IP için başka bir canlı izleme çalışıyor")
                return svc.serialize(job)
            active = db.scalars(
                select(m.Job).where(m.Job.active_key.is_not(None), interactive_condition()).with_for_update()
            ).all()
            if len(active) >= CAPACITY:
                raise HTTPException(429, "Canlı işlem kapasitesi dolu; kısa süre sonra tekrar deneyin")
            job.result = {**selection, "interactive": True}
            db.commit()
            svc.publish()
            return svc.serialize(job)
    except RedisError:
        raise HTTPException(503, "Canlı izleme hizmetine ulaşılamadı") from None


@router.get("/ipam/addresses")
def address_table(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    q: str = Query("", max_length=200),
    filters: str = Query("[]", max_length=12000),
    user=Depends(current_user),
    db=Depends(db_session),
):
    return read_cache.json_response(
        ["addresses", offset, limit, q, filters],
        lambda: table.addresses(db, offset=offset, limit=limit, q=q, filters=filters),
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


@router.get("/ipam/devices/{id}/model-image")
def model_image_get(id: str, user=Depends(current_user), db=Depends(db_session)):
    from .model_images import model_image

    device = svc.get(db, m.Device, id)
    return model_image(db, device.vendor, device.model) or {"url": "", "source": ""}


@router.put("/ipam/devices/{id}/model-image")
def model_image_save(id: str, payload: ModelImageInput, user=Depends(operator), db=Depends(db_session)):
    from .model_images import save_image

    return save_image(db, id, payload, user)
