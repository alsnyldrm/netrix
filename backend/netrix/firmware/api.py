"""Fast metadata endpoints and bounded streaming image uploads."""

import asyncio
import hashlib
import os
import re
import secrets
import shutil
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select

from .. import models as m
from ..core import db_session, now, settings
from ..identity.security import admin, audit, current_user, operator
from ..services import get, publish, serialize
from .service import (
    FAMILIES,
    GroupInput,
    ImageInput,
    PlanInput,
    RecoveryInput,
    compatible,
    groups_view,
    image_path,
    new_plan,
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
            db.execute(select(m.FirmwarePlan.status, func.count()).group_by(m.FirmwarePlan.status)).all()
        ),
        "service": service_info(),
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


def save_group(db, user, payload, row):
    ids = sorted(set(payload.device_ids))
    for id in ids:
        device = get(db, m.Device, id)
        if device.archived or not device.discovery_scope_id or device.adapter not in FAMILIES:
            raise HTTPException(422, "Yalnız desteklenen aktif envanter cihazları gruba eklenebilir")
    row.name, row.description = payload.name, payload.description
    db.add(row)
    db.flush()
    db.execute(delete(m.FirmwareMember).where(m.FirmwareMember.group_id == row.id))
    db.add_all(m.FirmwareMember(group_id=row.id, device_id=id) for id in ids)
    audit(db, user, "update", "firmware_groups", row.id, "Bağımsız firmware grubu ve üyeleri kaydedildi")
    db.commit()
    publish()
    return {**serialize(row), "device_ids": ids}


@router.post("/groups", status_code=201)
def create_group(payload: GroupInput, db=Depends(db_session), user=Depends(operator)):
    return save_group(db, user, payload, m.FirmwareGroup())


@router.put("/groups/{id}")
def update_group(id: str, payload: GroupInput, db=Depends(db_session), user=Depends(operator)):
    return save_group(db, user, payload, get(db, m.FirmwareGroup, id))


@router.delete("/groups/{id}", status_code=204)
def delete_group(id: str, db=Depends(db_session), user=Depends(admin)):
    row = get(db, m.FirmwareGroup, id)
    db.execute(delete(m.FirmwareMember).where(m.FirmwareMember.group_id == id))
    db.delete(row)
    audit(db, user, "delete", "firmware_groups", id, "Firmware grubu silindi; plan hedefleri korundu")
    db.commit()
    publish()


@router.get("/devices")
def devices(
    q: str = "",
    group_id: str | None = None,
    image_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    user=Depends(current_user),
):
    conditions = [
        m.Device.archived.is_(False),
        m.Device.discovery_scope_id.is_not(None),
        m.Device.adapter.in_(FAMILIES),
    ]
    if q:
        conditions.append(
            m.Device.name.contains(q) | m.Device.management_ip.contains(q) | m.Device.model.contains(q)
        )
    if group_id:
        conditions.append(
            m.Device.id.in_(select(m.FirmwareMember.device_id).where(m.FirmwareMember.group_id == group_id))
        )
    image = get(db, m.FirmwareImage, image_id) if image_id else None
    rows = list(
        db.scalars(
            select(m.Device)
            .where(*conditions)
            .order_by(m.Device.name, m.Device.id)
            .offset(offset)
            .limit(limit)
        )
    )
    return {
        "items": [
            {
                "id": d.id,
                "name": d.name,
                "management_ip": d.management_ip,
                "model": d.model,
                "software_version": d.software_version,
                "family": FAMILIES[d.adapter],
                "protocol": "tftp" if d.adapter == "hp_1950" else "sftp",
                "compatible": compatible(image, d) if image else None,
            }
            for d in rows
        ],
        "total": db.scalar(select(func.count()).select_from(m.Device).where(*conditions)),
    }


@router.get("/plans")
def plans(
    history: bool = False,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db=Depends(db_session),
    user=Depends(current_user),
):
    conditions = [m.FirmwarePlan.status.in_(("succeeded", "cancelled"))] if history else []
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


@router.post("/plans", status_code=201)
def create_plan(payload: PlanInput, db=Depends(db_session), user=Depends(admin)):
    return serialize(new_plan(db, payload, user))


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
    row = db.scalar(select(m.FirmwarePlan).where(m.FirmwarePlan.id == id).with_for_update())
    if not row:
        raise HTTPException(404, "Plan bulunamadı")
    row.cancel_requested = True
    running = False
    for target in db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == id)):
        if target.status == "running":
            running = True
        elif target.status not in ("succeeded", "attention"):
            target.status, target.active_device = "cancelled", None
            target.transfer_expires_at = now()
    if not running:
        row.status, row.finished_at = "cancelled", now()
    audit(
        db,
        user,
        "cancel",
        "firmware_plans",
        id,
        "Sonraki firmware işlemleri durduruldu; flash yazımı kesilmedi",
    )
    db.commit()
    publish()
    return serialize(row)


@router.post("/plans/{id}/activate")
def activate(id: str, db=Depends(db_session), user=Depends(admin)):
    row = db.scalar(select(m.FirmwarePlan).where(m.FirmwarePlan.id == id).with_for_update())
    if not row or row.status != "ready" or row.cancel_requested:
        raise HTTPException(409, "Yalnız hazırlanmış plan etkinleştirilebilir")
    for target in db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == id)):
        if target.status == "succeeded":
            continue
        if target.status != "staged":
            raise HTTPException(409, "Tüm hedefler hazırlanmış olmalı")
        validate_device(db, get(db, m.Device, target.device_id), get(db, m.FirmwareImage, target.image_id))
        target.status = "queued"
    row.mode, row.status, row.available_at = "activate", "queued", now()
    audit(db, user, "activate", "firmware_plans", id, "Hazırlanmış firmware için yeniden başlatma onaylandı")
    db.commit()
    publish()
    return serialize(row)


@router.post("/plans/{id}/retry")
def retry(id: str, db=Depends(db_session), user=Depends(admin)):
    row = get(db, m.FirmwarePlan, id)
    if row.status != "paused" or row.cancel_requested:
        raise HTTPException(409, "Plan yeniden denemeye uygun değil")
    targets = list(db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == id)))
    if any(t.status == "attention" for t in targets):
        raise HTTPException(409, "Yazma sonrası belirsizlik var; önce hedef sürümünü yeniden doğrulayın")
    for target in targets:
        if target.status == "failed":
            target.status, target.error, target.error_code = "queued", "", ""
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
    if target.status != "attention":
        raise HTTPException(409, "Yalnız sonucu belirsiz hedef yeniden doğrulanabilir")
    target.status, target.phase = "queued", "reconcile"
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
