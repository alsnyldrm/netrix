"""Fast metadata endpoints and bounded streaming image uploads."""

import asyncio
import hashlib
import os
import re
import secrets
import shutil
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select

from .. import models as m
from ..core import db_session, now, settings
from ..identity.security import admin, audit, current_user, operator
from ..services import get, publish, serialize
from . import catalog, controls, grouping, history
from .service import (
    GroupInput,
    ImageInput,
    PlanInput,
    RecoveryInput,
    groups_view,
    image_path,
    new_plan,
    plan_candidates,
    service_info,
    start_plan,
    target_view,
    validate_device,
)

router = APIRouter(prefix="/api/v1/firmware", tags=["Firmware"])


@router.get("/overview")
def overview(db=Depends(db_session), user=Depends(current_user)):
    return {
        "images": db.scalar(
            select(func.count()).select_from(m.FirmwareImage).where(m.FirmwareImage.status == "ready")
        ),
        "groups": db.scalar(select(func.count()).select_from(m.FirmwareGroup)),
        "plans": dict(
            db.execute(
                select(m.FirmwarePlan.status, func.count())
                .where(m.FirmwarePlan.deleted_at.is_(None))
                .group_by(m.FirmwarePlan.status)
            ).all()
        ),
        "service": service_info(),
        "devices": catalog.counts(db, grouping.base_conditions()),
    }


@router.get("/images")
def images(
    q: str = "",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    user=Depends(current_user),
):
    conditions = [m.FirmwareImage.name.contains(q)] if q else []
    return {
        "items": [
            serialize(i)
            for i in db.scalars(
                select(m.FirmwareImage)
                .where(*conditions)
                .order_by(m.FirmwareImage.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ],
        "total": db.scalar(select(func.count()).select_from(m.FirmwareImage).where(*conditions)),
    }


@router.get("/plan-images")
def plan_images(db=Depends(db_session), user=Depends(current_user)):
    # Compact choices include older uploaded releases as well as the newest.
    return {
        "items": [
            dict(row._mapping)
            for row in db.execute(
                select(
                    m.FirmwareImage.id, m.FirmwareImage.name, m.FirmwareImage.version, m.FirmwareImage.status
                )
                .where(m.FirmwareImage.status == "ready")
                .order_by(m.FirmwareImage.created_at.desc(), m.FirmwareImage.id)
            )
        ]
    }


@router.post("/images", status_code=201)
def create_image(payload: ImageInput, db=Depends(db_session), user=Depends(admin)):
    patterns = {
        "aos_s": r"(?:K|KB|WB|WC)\.\d{2}\.\d{2}\.\d{4}",
        "cx6100": r"PL\.10\.\d{2}\.\d{4}",
        "hp1950": r"R\d{4}(?:P\d+)?",
    }
    if not re.fullmatch(patterns[payload.family], payload.version, re.I):
        raise HTTPException(422, "Tam sürümü aile önekiyle girin: WC.16.11.0026, PL.10.13.1000 veya R3507P10")
    payload.version = payload.version.upper()
    if payload.family == "hp1950":
        branches = {"JH295A" in model or "1950-12XGT" in model for model in payload.models}
        if len(branches) != 1:
            raise HTTPException(422, "JH295A/1950-12XGT ve diğer 1950 modelleri aynı imajda birleştirilemez")
        is_jh295 = branches.pop()
        if is_jh295 != payload.version.startswith("R51"):
            raise HTTPException(422, "JH295A ve diğer 1950 modellerinin yazılım serileri farklıdır")
    suffix = ".ipe" if payload.family == "hp1950" else ".swi"
    if not payload.original_name.lower().endswith(suffix):
        raise HTTPException(422, f"Bu aile için {suffix} dosyası gerekli")
    if (
        db.scalar(
            select(func.count()).select_from(m.FirmwareImage).where(m.FirmwareImage.status == "uploading")
        )
        >= 20
    ):
        raise HTTPException(409, "Tamamlanmamış dosyaları silin veya yüklemeyi tamamlayın")
    row = m.FirmwareImage(**payload.model_dump(), uploaded_by=user.id)
    row.expected_sha256 = row.expected_sha256.lower()
    db.add(row)
    db.flush()
    audit(db, user, "create", "firmware_images", row.id, "Firmware dosyası yükleme kaydı açıldı")
    db.commit()
    return serialize(row)


@router.put("/images/{id}/content")
async def upload_image(id: str, request: Request, db=Depends(db_session), user=Depends(admin)):
    row = get(db, m.FirmwareImage, id)
    if row.status != "uploading":
        raise HTTPException(409, "Hazır imaj değiştirilemez; yeni dosya kaydı oluşturun")
    destination = image_path(row)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        length = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise HTTPException(400, "Dosya uzunluğu geçersiz") from None
    if length < 0:
        raise HTTPException(400, "Dosya uzunluğu geçersiz")
    if length > settings().firmware_max_bytes:
        raise HTTPException(413, "Firmware dosyası boyut sınırını aşıyor")
    # Release the authentication read snapshot before reserving disk space.
    db.commit()
    stored = db.scalar(select(func.coalesce(func.sum(m.FirmwareImage.size_bytes), 0)))
    if stored + max(1, length) > settings().firmware_repository_bytes:
        raise HTTPException(409, "Firmware deposu kapasitesi doldu")
    slot = None
    for index in range(4):
        candidate = destination.parent / f"upload-{index}.slot"
        try:
            if candidate.exists() and time.time() - candidate.stat().st_mtime > 4 * 3600:
                candidate.unlink(missing_ok=True)
            fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as reservation:
                reservation.write(str(length or settings().firmware_max_bytes))
            slot = candidate
            break
        except FileExistsError:
            continue
    if slot is None:
        raise HTTPException(429, "Dört dosya yüklemesi sürüyor; tamamlanmasını bekleyin")
    lock = destination.with_suffix(".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        slot.unlink(missing_ok=True)
        raise HTTPException(409, "Bu dosyanın yüklemesi sürüyor") from None
    temp = destination.with_suffix("." + secrets.token_hex(8) + ".part")
    try:
        # The lock file prevents writers, while this current read prevents a stale
        # upload request from replacing an image another request just finalized.
        row = db.scalar(
            select(m.FirmwareImage)
            .where(m.FirmwareImage.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not row or row.status != "uploading":
            raise HTTPException(409, "Hazır imaj değiştirilemez")
        db.commit()
        reserved = 0
        for reservation in destination.parent.glob("upload-*.slot"):
            try:
                reserved += int(reservation.read_text())
            except FileNotFoundError:
                continue
            except ValueError:
                reserved += settings().firmware_max_bytes
        if stored + reserved > settings().firmware_repository_bytes:
            raise HTTPException(409, "Firmware deposu kapasitesi diğer yüklemeler için ayrılmış")
        size, digest = 0, hashlib.sha256()
        with temp.open("xb") as output:
            os.chmod(temp, 0o600)
            async with asyncio.timeout(3600):
                async for chunk in request.stream():
                    size += len(chunk)
                    if (
                        stored + size > settings().firmware_repository_bytes
                        or shutil.disk_usage(destination.parent).free < 1024**3
                    ):
                        raise HTTPException(409, "Firmware deposunda yeterli boş alan yok")
                    if size > settings().firmware_max_bytes:
                        raise HTTPException(413, "Firmware dosyası boyut sınırını aşıyor")
                    digest.update(chunk)
                    await asyncio.to_thread(output.write, chunk)
            await asyncio.to_thread(output.flush)
            await asyncio.to_thread(os.fsync, output.fileno())
        if not size or digest.hexdigest() != row.expected_sha256:
            raise HTTPException(422, "Dosya boş veya üreticinin SHA-256 değeriyle eşleşmiyor")
        os.replace(temp, destination)
        row.size_bytes, row.sha256, row.status = size, digest.hexdigest(), "ready"
        audit(
            db,
            user,
            "upload",
            "firmware_images",
            row.id,
            "Firmware dosyası SHA-256 doğrulamasıyla kaydedildi",
        )
        db.commit()
        publish()
        return serialize(row)
    except TimeoutError:
        raise HTTPException(408, "Dosya yüklemesi bir saat içinde tamamlanamadı") from None
    finally:
        temp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
        slot.unlink(missing_ok=True)


@router.get("/images/{id}/content")
def download_image(id: str, db=Depends(db_session), user=Depends(admin)):
    row = get(db, m.FirmwareImage, id)
    if row.status != "ready" or not image_path(row).is_file():
        raise HTTPException(404, "Firmware dosyası bulunamadı")
    return FileResponse(image_path(row), filename=row.original_name, media_type="application/octet-stream")


@router.delete("/images/{id}", status_code=204)
def delete_image(id: str, db=Depends(db_session), user=Depends(admin)):
    row = get(db, m.FirmwareImage, id)
    destination = image_path(row)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = destination.with_suffix(".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        raise HTTPException(409, "Yükleme sürerken dosya silinemez") from None
    try:
        if db.scalar(select(m.FirmwareTarget.id).where(m.FirmwareTarget.image_id == id).limit(1)):
            raise HTTPException(409, "Plan geçmişindeki firmware dosyası silinemez")
        audit(db, user, "delete", "firmware_images", row.id, "Kullanılmayan firmware dosyası silindi")
        db.delete(row)
        db.commit()
        destination.unlink(missing_ok=True)
        publish()
    finally:
        lock.unlink(missing_ok=True)


@router.get("/groups")
def groups(db=Depends(db_session), user=Depends(current_user)):
    return {"items": groups_view(db)}


@router.get("/groups/{id}")
def group(id: str, db=Depends(db_session), user=Depends(current_user)):
    row = get(db, m.FirmwareGroup, id)
    return {
        **serialize(row),
        "device_ids": list(
            db.scalars(select(m.FirmwareMember.device_id).where(m.FirmwareMember.group_id == id))
        ),
    }


@router.post("/groups", status_code=201)
def create_group(payload: GroupInput, db=Depends(db_session), user=Depends(operator)):
    return grouping.save_group(db, user, payload, m.FirmwareGroup())


@router.put("/groups/{id}")
def update_group(id: str, payload: GroupInput, db=Depends(db_session), user=Depends(operator)):
    return grouping.save_group(db, user, payload, get(db, m.FirmwareGroup, id))


@router.delete("/groups/{id}", status_code=204)
def delete_group(id: str, db=Depends(db_session), user=Depends(admin)):
    row = get(db, m.FirmwareGroup, id)
    db.execute(delete(m.FirmwareMember).where(m.FirmwareMember.group_id == id))
    db.delete(row)
    audit(db, user, "delete", "firmware_groups", id, "Firmware grubu silindi; plan hedefleri korundu")
    db.commit()
    publish()


@router.get("/device-filters")
def device_filters(db=Depends(db_session), user=Depends(current_user)):
    return grouping.filter_options(db)


@router.get("/devices/selection")
def device_selection(
    filters: grouping.DeviceFilters = Depends(), db=Depends(db_session), user=Depends(current_user)
):
    return grouping.selection(db, filters)


@router.get("/devices")
def devices(
    filters: grouping.DeviceFilters = Depends(),
    group_id: str = "",
    image_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    user=Depends(current_user),
):
    return grouping.candidates(db, filters, limit=limit, offset=offset, group_id=group_id, image_id=image_id)


@router.get("/plans")
def plans(
    history: bool = False,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    user=Depends(current_user),
):
    conditions = [m.FirmwarePlan.deleted_at.is_(None)]
    if history:
        conditions.append(m.FirmwarePlan.status.in_(("succeeded", "cancelled")))
    rows = list(
        db.scalars(
            select(m.FirmwarePlan)
            .where(*conditions)
            .order_by(m.FirmwarePlan.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    counts = {}
    if rows:
        for plan_id, status, count in db.execute(
            select(m.FirmwareTarget.plan_id, m.FirmwareTarget.status, func.count())
            .where(m.FirmwareTarget.plan_id.in_([r.id for r in rows]))
            .group_by(m.FirmwareTarget.plan_id, m.FirmwareTarget.status)
        ):
            counts.setdefault(plan_id, {})[status] = count
    return {
        "items": [{**serialize(r), "counts": counts.get(r.id, {})} for r in rows],
        "total": db.scalar(select(func.count()).select_from(m.FirmwarePlan).where(*conditions)),
    }


@router.get("/outdated-groups")
def outdated_groups(
    q: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    db=Depends(db_session),
    user=Depends(current_user),
):
    return catalog.outdated_groups(
        db, grouping.conditions(db, grouping.DeviceFilters(q=q)), offset=offset, limit=limit
    )


@router.post("/plans/prepare")
def prepare_plan(payload: catalog.SelectionInput, db=Depends(db_session), user=Depends(admin)):
    return catalog.prepare_selection(db, payload, grouping.base_conditions())


@router.post("/plans", status_code=201)
def create_plan(payload: PlanInput, db=Depends(db_session), user=Depends(admin)):
    return serialize(new_plan(db, payload, user))


@router.post("/plans/preview")
def preview_plan(payload: PlanInput, db=Depends(db_session), user=Depends(admin)):
    steps, targets = plan_candidates(db, payload)
    return {"steps": steps, "target_total": len(targets)}


@router.get("/plans/{id}")
def plan(
    id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    user=Depends(current_user),
):
    row = get(db, m.FirmwarePlan, id)
    return {
        **serialize(row),
        "target_total": db.scalar(
            select(func.count()).select_from(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == id)
        ),
        "targets": [
            target_view(t)
            for t in db.scalars(
                select(m.FirmwareTarget)
                .where(m.FirmwareTarget.plan_id == id)
                .order_by(m.FirmwareTarget.stage, m.FirmwareTarget.id)
                .offset(offset)
                .limit(limit)
            )
        ],
    }


@router.post("/plans/{id}/start")
def start(id: str, db=Depends(db_session), user=Depends(admin)):
    return serialize(start_plan(db, get(db, m.FirmwarePlan, id), user))


@router.post("/plans/{id}/cancel")
def cancel(id: str, db=Depends(db_session), user=Depends(admin)):
    return serialize(controls.stop_plan(db, id, user))


@router.post("/plans/{id}/force-stop")
def force_stop(id: str, payload: controls.ForceStopInput, db=Depends(db_session), user=Depends(admin)):
    return serialize(controls.stop_plan(db, id, user, force=True, confirmation=payload))


@router.patch("/plans/{id}/concurrency")
def concurrency(id: str, payload: controls.ConcurrencyInput, db=Depends(db_session), user=Depends(admin)):
    return serialize(controls.set_concurrency(db, id, payload.concurrency, user))


@router.delete("/plans/{id}", status_code=204)
def delete_plan(id: str, db=Depends(db_session), user=Depends(admin)):
    controls.remove_plan(db, id, user)


@router.post("/plans/{id}/activate")
def activate(id: str, db=Depends(db_session), user=Depends(admin)):
    row = controls.locked_plan(db, id)
    if row.status != "ready" or row.cancel_requested:
        raise HTTPException(409, "Yalnız hazırlanmış plan etkinleştirilebilir")
    for target in db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == id)):
        if target.status == "succeeded":
            continue
        if target.status != "staged":
            raise HTTPException(409, "Tüm hedefler hazırlanmış olmalı")
        validate_device(db, get(db, m.Device, target.device_id), get(db, m.FirmwareImage, target.image_id))
        target.status = "queued"
        history.add_event(
            db, target, kind="phase", title="Yönetici hazır imajı etkinleştirmeyi onayladı", finished=True
        )
    row.mode, row.status, row.available_at = "activate", "queued", now()
    audit(db, user, "activate", "firmware_plans", id, "Hazırlanmış firmware için yeniden başlatma onaylandı")
    db.commit()
    publish()
    return serialize(row)


@router.post("/plans/{id}/retry")
def retry(id: str, db=Depends(db_session), user=Depends(admin)):
    row = controls.locked_plan(db, id)
    if row.status != "paused" or row.cancel_requested:
        raise HTTPException(409, "Plan yeniden denemeye uygun değil")
    targets = list(db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == id)))
    if any(t.status == "attention" for t in targets):
        raise HTTPException(409, "Yazma sonrası belirsizlik var; önce hedef sürümünü yeniden doğrulayın")
    for target in targets:
        if target.status == "failed":
            target.status, target.error, target.error_code = "queued", "", ""
            history.add_event(
                db, target, kind="phase", title="Yönetici güvenli hedefi yeniden kuyruğa aldı", finished=True
            )
    row.status = "queued"
    audit(
        db, user, "retry", "firmware_plans", id, "Yazma başlamamış firmware hedefleri yeniden kuyruğa alındı"
    )
    db.commit()
    publish()
    return serialize(row)


@router.post("/targets/{id}/verify")
def verify(id: str, db=Depends(db_session), user=Depends(admin)):
    target = get(db, m.FirmwareTarget, id)
    # Serialize with the claimant, then refresh the target after acquiring the
    # plan lock. A read-only verification must never resume later device writes.
    plan = db.scalar(select(m.FirmwarePlan).where(m.FirmwarePlan.id == target.plan_id).with_for_update())
    target = db.scalar(
        select(m.FirmwareTarget)
        .where(m.FirmwareTarget.id == id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if target.status != "attention":
        raise HTTPException(409, "Yalnız sonucu belirsiz hedef yeniden doğrulanabilir")
    if target.phase != "reconcile" and target.error_code:
        target.evidence = {
            **target.evidence,
            "operation_error": {
                "code": target.error_code,
                "phase": target.phase,
                "at": (target.finished_at or now()).isoformat(),
            },
        }
    target.status, target.phase = "queued", "reconcile"
    target.evidence = {**target.evidence, "force_stop_requested": False}
    history.add_event(
        db, target, kind="phase", title="Yönetici salt okunur sürüm doğrulaması istedi", finished=True
    )
    if plan.status != "cancelled":
        plan.status = "paused"
    audit(
        db, user, "verify", "firmware_targets", id, "Firmware sonucu salt okunur yeniden doğrulamaya alındı"
    )
    db.commit()
    publish()
    return target_view(target)


@router.post("/targets/{id}/release")
def release(id: str, payload: RecoveryInput, db=Depends(db_session), user=Depends(admin)):
    target = db.scalar(select(m.FirmwareTarget).where(m.FirmwareTarget.id == id).with_for_update())
    if not target or target.status != "attention":
        raise HTTPException(409, "Yalnız müdahale bekleyen hedef serbest bırakılabilir")
    device = get(db, m.Device, target.device_id)
    if not payload.confirmed_recovery or payload.device_name != device.name:
        raise HTTPException(422, "Kurtarmayı tamamlayıp cihazın tam adını doğrulayın")
    target.status, target.phase, target.active_device = "failed", "recovered", None
    target.error_code = "manual_recovery"
    target.error = "Yönetici cihazın kurtarıldığını doğruladı; firmware kurulumu başarılı sayılmadı."
    target.transfer_expires_at = now()
    history.add_event(
        db,
        target,
        kind="result",
        title="Manuel kurtarma yönetici tarafından doğrulandı",
        response=target.error,
        finished=True,
    )
    audit(
        db,
        user,
        "manual_recovery",
        "firmware_targets",
        id,
        "Manuel kurtarma doğrulandı; cihaz kilidi serbest bırakıldı",
    )
    db.commit()
    publish()
    return target_view(target)


@router.get("/history")
def execution_history(
    q: str = Query("", max_length=120),
    status: Literal["", "queued", "running", "paused", "ready", "succeeded", "cancelled"] = "",
    mode: Literal["", "check", "stage", "upgrade", "activate", "verify"] = "",
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    user=Depends(current_user),
):
    return history.listing(db, q, status, mode, limit, offset)


@router.get("/history/targets/{id}")
def execution_transcript(
    id: str,
    limit: int = Query(40, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    user=Depends(current_user),
):
    return history.transcript(db, id, limit, offset)


@router.get("/history/{id}")
def execution_operation(id: str, db=Depends(db_session), user=Depends(current_user)):
    return history.operation(db, id)


@router.get("/history/{id}/targets")
def execution_targets(
    id: str,
    stage: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    user=Depends(current_user),
):
    return history.targets(db, id, stage, limit, offset)
