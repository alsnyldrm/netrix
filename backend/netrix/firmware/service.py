"""Firmware business rules; all network work belongs to firmware.runtime."""

import hashlib
import ipaddress
import re
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from .. import models as m
from ..core import now, settings
from ..identity.security import audit
from ..services import get, publish, serialize
from .adapters import ERRORS
from .versions import compare

FAMILIES = {"aruba_5400": "aos_s", "aruba_2900": "aos_s", "aruba_6100": "cx6100", "hp_1950": "hp1950"}
BUSY = ("running", "staged", "attention")


def transfer_protocol(family):
    return {"aos_s": "sftp", "cx6100": "scp", "hp1950": "tftp"}[family]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ImageInput(Input):
    name: str = Field(min_length=1, max_length=120)
    family: str = Field(pattern=r"^(aos_s|cx6100|hp1950)$")
    version: str = Field(min_length=3, max_length=120, pattern=r"^[\w., ()-]+$")
    models: list[str] = Field(min_length=1, max_length=50)
    original_name: str = Field(min_length=5, max_length=160, pattern=r"^[a-zA-Z0-9_.-]+$")
    expected_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    notes: str = Field(default="", max_length=8000)

    @field_validator("models")
    @classmethod
    def model_codes(cls, values):
        result = sorted(set(v.upper().strip() for v in values))
        if any(not re.fullmatch(r"[A-Z0-9][A-Z0-9_+ .()/:-]{2,99}", v) for v in result):
            raise ValueError("Tam ürün/SKU kodlarını girin; joker karakter kullanmayın")
        return result


class GroupInput(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    device_ids: list[str] = Field(default_factory=list, max_length=1000)


class StepInput(Input):
    group_id: str | None = None
    image_id: str
    device_ids: list[str] | None = Field(default=None, min_length=1, max_length=1000)


class PlanInput(Input):
    name: str = Field(min_length=1, max_length=120)
    mode: str = Field(default="check", pattern=r"^(check|stage|upgrade)$")
    steps: list[StepInput] = Field(min_length=1, max_length=50)
    concurrency: int = Field(default=1, ge=1, le=4)
    available_at: str | None = None
    allow_enable_sftp: bool = False
    acknowledge_outage: bool = False
    acknowledge_upgrade_path: bool = False


def image_path(image):
    suffix = ".ipe" if image.family == "hp1950" else ".swi"
    # Paths never contain a user-controlled filename.
    return Path(settings().firmware_directory) / (image.id + suffix)


def compatible(image, device):
    if FAMILIES.get(device.adapter) != image.family:
        return False
    tokens = set(re.findall(r"[A-Z0-9]+", device.model.upper()))
    return any(code in tokens or code == device.model.upper() for code in image.models)


def validate_device(db, device, image=None):
    if device.archived or device.lifecycle_status != "active" or not device.discovery_scope_id:
        raise HTTPException(422, "Firmware hedefi aktif cihaz envanterinde olmalı")
    if device.adapter not in FAMILIES:
        raise HTTPException(422, "Firmware için 5400/2930/2920, 6100 veya HP 1950 adaptörü gerekli")
    profile = db.get(m.Credential, device.config_credential_id)
    if not profile or profile.protocol != "ssh":
        raise HTTPException(422, "Cihaza SSH erişim profili atanmalı")
    if image and (image.status != "ready" or not compatible(image, device)):
        raise HTTPException(422, f"{device.name}: imajın ürün kodu/aile uyumluluğu doğrulanamadı")
    # Firmware is independent from discovery scan scope; inventory ownership is required.
    return profile


def connection_stamp(device, profile):
    return hashlib.sha256(
        repr(
            (
                device.management_ip,
                device.config_port,
                device.config_credential_id,
                profile.updated_at,
                device.adapter,
                device.model,
                device.ssh_trust_host_key,
            )
        ).encode()
    ).hexdigest()


def plan_candidates(db, payload):
    """Freeze only older, compatible targets; explicit selections never expand."""
    seen, steps, targets = set(), [], []
    for item in payload.steps:
        group = get(db, m.FirmwareGroup, item.group_id) if item.group_id else None
        image = get(db, m.FirmwareImage, item.image_id)
        if not group and not item.device_ids:
            raise HTTPException(422, "Bir firmware grubu veya cihaz seçimi gerekli")
        query = select(m.Device).order_by(m.Device.id)
        if group:
            query = query.join(m.FirmwareMember, m.FirmwareMember.device_id == m.Device.id).where(
                m.FirmwareMember.group_id == group.id
            )
        if item.device_ids is not None:
            query = query.where(m.Device.id.in_(item.device_ids))
        devices = list(db.scalars(query.limit(1001)))
        if item.device_ids is not None and {d.id for d in devices} != set(item.device_ids):
            raise HTTPException(
                422, "Seçilen cihaz artık bu grupta veya envanterde bulunmuyor; seçimi yenileyin"
            )
        if not devices:
            raise HTTPException(422, f"{group.name if group else 'Seçim'}: cihaz bulunamadı")
        skipped = {"current": 0, "newer": 0, "unknown": 0}
        included = 0
        for device in devices:
            if device.id in seen:
                raise HTTPException(422, "Aynı cihaz planda yalnızca bir kez bulunabilir")
            seen.add(device.id)
            if len(seen) > 1000:
                raise HTTPException(422, "Bir plan en fazla 1000 cihaz içerebilir")
            if image.status != "ready" or not compatible(image, device):
                raise HTTPException(422, f"{device.name}: imajın ürün kodu/aile uyumluluğu doğrulanamadı")
            relation = compare(device.software_version, image.version)
            if payload.mode != "check" and relation != -1:
                skipped["unknown" if relation is None else "current" if relation == 0 else "newer"] += 1
                continue
            profile = validate_device(db, device, image)
            targets.append((len(steps), device, image, profile))
            included += 1
        steps.append(
            {
                "group_id": group.id if group else None,
                "group_name": group.name if group else "Seçilen cihazlar",
                "image_id": image.id,
                "image_name": image.name,
                "version": image.version,
                "count": included,
                "selected_count": len(devices),
                "excluded": skipped,
                "allow_enable_sftp": payload.allow_enable_sftp,
            }
        )
    return steps, targets


def new_plan(db, payload, user):
    if payload.mode != "check" and not payload.acknowledge_upgrade_path:
        raise HTTPException(422, "Üreticinin sürüm geçişi ve BootROM gereksinimlerini doğrulayın")
    if payload.mode == "upgrade" and not payload.acknowledge_outage:
        raise HTTPException(422, "Yeniden başlatma ve hizmet kesintisini onaylayın")
    available = now()
    if payload.available_at:
        from datetime import datetime

        try:
            available = datetime.fromisoformat(payload.available_at.replace("Z", "+00:00"))
            if available.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Zamanlama saat dilimi içermeli") from None
    steps, candidates = plan_candidates(db, payload)
    targets = [
        m.FirmwareTarget(
            device_id=device.id,
            image_id=image.id,
            stage=stage,
            evidence={
                "history_version": 1,
                "connection_stamp": connection_stamp(device, profile),
                "device_name": device.name,
                "management_ip": device.management_ip,
                "expected_version": image.version,
            },
        )
        for stage, device, image, profile in candidates
    ]
    if not targets:
        raise HTTPException(
            422,
            "Güncellenecek cihaz yok. Aynı veya daha yeni sürümler ve karşılaştırılamayan sürümler plana alınmadı.",
        )
    plan = m.FirmwarePlan(
        name=payload.name,
        mode=payload.mode,
        steps=steps,
        concurrency=payload.concurrency,
        available_at=available,
        requested_by=user.id,
    )
    db.add(plan)
    db.flush()
    for target in targets:
        target.plan_id = plan.id
        db.add(target)
    audit(db, user, "create", "firmware_plans", plan.id, "Firmware planı ve hedefleri sabitlendi")
    db.commit()
    publish()
    return plan


def start_plan(db, plan, user):
    try:
        return _start_plan(db, plan, user)
    except OperationalError as exc:
        # MariaDB snapshot conflicts (1020), deadlocks and lock timeouts are
        # competing reservations, never permission to replay a device operation.
        db.rollback()
        if getattr(exc, "orig", None) and exc.orig.args[0] in (1020, 1205, 1213):
            raise HTTPException(409, "Cihaz rezervasyonu değişti; planı yeniden başlatın") from None
        raise


def _start_plan(db, plan, user):
    plan = db.scalar(
        select(m.FirmwarePlan)
        .where(m.FirmwarePlan.id == plan.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if plan.status in ("queued", "running"):
        return plan
    if plan.mode != "check" and not service_info()["configured"]:
        raise HTTPException(422, "Dosya sunucusu adresi yapılandırılmalı")
    if plan.status != "draft":
        raise HTTPException(409, "Plan yalnız taslak durumunda başlatılabilir")
    targets = list(db.scalars(select(m.FirmwareTarget).where(m.FirmwareTarget.plan_id == plan.id)))
    # Global device row ordering serializes concurrent plans on MariaDB/Galera.
    for target in sorted(targets, key=lambda t: t.device_id):
        device = db.scalar(select(m.Device).where(m.Device.id == target.device_id).with_for_update())
        profile = validate_device(db, device, get(db, m.FirmwareImage, target.image_id))
        if target.evidence["connection_stamp"] != connection_stamp(device, profile):
            raise HTTPException(409, "Cihaz bağlantısı değişti; yeni plan oluşturun")
        if db.scalar(
            select(m.FirmwareTarget.id).where(m.FirmwareTarget.active_device == device.id).with_for_update()
        ):
            raise HTTPException(409, f"{device.name}: başka firmware planında ayrılmış")
        if plan.mode != "check":
            target.active_device = device.id
    plan.status = "queued"
    audit(db, user, "start", "firmware_plans", plan.id, "Firmware planı açık kullanıcı isteğiyle başlatıldı")
    db.commit()
    publish()
    return plan


def target_view(row):
    data = serialize(row)
    # Render current terminology for historical records without rewriting them.
    if row.error_code in ERRORS:
        data["error"] = ERRORS[row.error_code]
    for key in (
        "transfer_username",
        "transfer_secret_hash",
        "transfer_name",
        "transfer_expires_at",
        "active_device",
    ):
        data.pop(key, None)
    return data


def service_info():
    host = settings().firmware_advertise_host
    try:
        address = ipaddress.ip_address(host)
        configured = not (address.is_loopback or address.is_unspecified or address.is_multicast)
    except ValueError:
        configured = False
    return {
        "configured": configured,
        "host": host,
        "sftp_port": settings().firmware_sftp_port,
        "tftp_port": 69,
        "protocols": ["scp", "sftp", "tftp"],
        "max_bytes": settings().firmware_max_bytes,
    }


def groups_view(db):
    counts = dict(
        db.execute(select(m.FirmwareMember.group_id, func.count()).group_by(m.FirmwareMember.group_id)).all()
    )
    return [
        {**serialize(g), "device_count": counts.get(g.id, 0)}
        for g in db.scalars(select(m.FirmwareGroup).order_by(m.FirmwareGroup.name))
    ]


class RecoveryInput(Input):
    device_name: str = Field(min_length=1, max_length=120)
    confirmed_recovery: bool


def cleanup_uploads():
    """The single API process has restarted; no previous upload can still run."""
    directory = Path(settings().firmware_directory)
    if directory.is_dir():
        for path in directory.iterdir():
            if path.is_file() and path.suffix in (".part", ".lock", ".slot"):
                path.unlink(missing_ok=True)
