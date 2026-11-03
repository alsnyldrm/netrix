"""Bounded, secret-safe device transcripts and read-only grouped execution history."""

import asyncio
import re

from fastapi import HTTPException
from sqlalchemy import func, select

from .. import models as m
from ..configuration.diff import redact_config
from ..core import now, session_factory
from ..services import get, serialize
from .service import target_view

OUTPUT_LIMIT = 12000
COMMAND_LIMIT = 2000
EVENT_LIMIT = 1000
PHASES = {
    "preflight": "Ön kontrol başlatıldı",
    "backup": "Konfigürasyon yedeği başlatıldı",
    "transferring": "Dosya aktarımı ve yazım başlatıldı",
    "image_verifying": "Cihazın imaj bütünlüğü doğrulanıyor",
    "rebooting": "Yeniden başlatma başlatıldı",
    "verifying": "Açılış sonrası sürüm doğrulaması başlatıldı",
    "reconcile": "Sonuç yeniden doğrulanıyor",
}
RESULTS = {
    "succeeded": "Hedef sürüm doğrulandı",
    "checked": "Ön kontrol tamamlandı",
    "staged": "İmaj hazır; yeniden başlatma bekliyor",
    "failed": "İşlem başarısız",
    "attention": "Sonuç belirsiz; müdahale gerekiyor",
    "cancelled": "İşlem durduruldu",
}


def safe_text(value, secrets=(), limit=OUTPUT_LIMIT):
    # Mask complete secrets BEFORE trimming; otherwise a boundary can expose a prefix.
    text = str(value or "")
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        text = text.replace(secret, "[GİZLENDİ]")
    text = re.sub(r"(?i)\b(?:fw_[a-f0-9]{20}|netrix-fw-[a-f0-9]{48}\.(?:swi|ipe))\b", "[SÜRELİ ERİŞİM]", text)
    text = re.sub(r"(?i)(\b(?:scp|sftp|ftp|https?)://)[^\s/@]+@", r"\1[GİZLENDİ]@", text)
    text = redact_config(text).replace("\x00", "")
    return text[:limit], len(text) > limit


def add_event(db, target, *, kind, title, status="info", command="", response="", secrets=(), finished=False):
    # The DB allocates a monotonic event ID. Do not contend with target heartbeats
    # or require a read/modify/write counter merely to record a device response.
    sequence = db.scalar(
        select(func.count()).select_from(m.FirmwareEvent).where(m.FirmwareEvent.target_id == target.id)
    )
    if sequence > EVENT_LIMIT:
        return None
    if sequence == EVENT_LIMIT:
        kind, title, status, command, response = (
            "result",
            "Ayrıntılı kayıt sınırına ulaşıldı",
            "info",
            "",
            "Sonraki komut çıktıları saklanmadı. Cihazın nihai sonucu ayrıca gösterilir.",
        )
    command, a = safe_text(command, secrets, COMMAND_LIMIT)
    response, b = safe_text(response, secrets)
    row = m.FirmwareEvent(
        target_id=target.id,
        kind=kind,
        phase=target.phase,
        title=title,
        status=status,
        command=command,
        response=response,
        truncated=a or b,
        finished_at=now() if finished else None,
    )
    db.add(row)
    db.flush()
    return row


def command_title(command, action):
    descriptions = {
        "no page": "Komut çıktısında sayfalama kapatılıyor",
        "show version": "Çalışan sürüm ve aktif yazılım alanı okunuyor",
        "show images": "Yazılım alanlarının sürümü ve SHA-256 değeri okunuyor",
        "show flash": "Yazılım alanlarındaki imajlar okunuyor",
        "show logging -r": "Cihazın son olayları okunuyor",
        "summary": "Çalışan sürüm ve sonraki açılış bilgileri okunuyor",
        "configure terminal": "SFTP ayarı için yapılandırma moduna giriliyor",
        "ip ssh filetransfer": "Cihazda güvenli dosya erişimi açılıyor",
        "exit": "Yapılandırma modundan çıkılıyor",
    }
    if command in descriptions:
        return descriptions[command]
    return {
        "transfer": "Firmware dosyası cihaza aktarılıyor ve yazılıyor",
        "boot": "Cihazın seçilen imajla yeniden başlatılması isteniyor",
        "save": "Cihaz ayarı uygulanıyor",
    }.get(action, "Cihaz sorgusu")


class Recorder:
    def __init__(self, target_id, secrets=()):
        self.target_id, self.secrets = target_id, list(secrets)

    async def begin(self, command, action="read"):
        def write():
            with session_factory()() as db:
                target = db.get(m.FirmwareTarget, self.target_id)
                event = add_event(
                    db,
                    target,
                    kind="command",
                    title=command_title(command, action),
                    status="started",
                    command=command,
                    secrets=self.secrets,
                )
                db.commit()
                return event.id if event and event.kind == "command" else None

        return await asyncio.to_thread(write)

    async def end(self, event_id, output, status):
        if not event_id:
            return

        def write():
            with session_factory()() as db:
                event = db.get(m.FirmwareEvent, event_id)
                event.response, truncated = safe_text(output, self.secrets)
                event.truncated = event.truncated or truncated
                event.status, event.finished_at = status, now()
                db.commit()

        await asyncio.to_thread(write)

    async def note(self, title, response="", *, kind="transfer", status="info"):
        def write():
            with session_factory()() as db:
                target = db.get(m.FirmwareTarget, self.target_id)
                add_event(
                    db,
                    target,
                    kind=kind,
                    title=title,
                    response=response,
                    status=status,
                    secrets=self.secrets,
                    finished=True,
                )
                db.commit()

        await asyncio.to_thread(write)


def listing(db, q="", status="", mode="", limit=20, offset=0):
    conditions = [m.FirmwarePlan.status != "draft"]
    if q:
        conditions.append(m.FirmwarePlan.name.contains(q, autoescape=True))
    if status:
        conditions.append(m.FirmwarePlan.status == status)
    if mode:
        conditions.append(m.FirmwarePlan.mode == mode)
    plans = list(
        db.scalars(
            select(m.FirmwarePlan)
            .where(*conditions)
            .order_by(m.FirmwarePlan.created_at.desc(), m.FirmwarePlan.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    counts = {}
    if plans:
        for plan_id, state, count in db.execute(
            select(m.FirmwareTarget.plan_id, m.FirmwareTarget.status, func.count())
            .where(m.FirmwareTarget.plan_id.in_([p.id for p in plans]))
            .group_by(m.FirmwareTarget.plan_id, m.FirmwareTarget.status)
        ):
            counts.setdefault(plan_id, {})[state] = count
    return {
        "items": [{**serialize(p), "counts": counts.get(p.id, {})} for p in plans],
        "total": db.scalar(select(func.count()).select_from(m.FirmwarePlan).where(*conditions)),
    }


def operation(db, id):
    plan = get(db, m.FirmwarePlan, id)
    counts = {}
    for stage, state, count in db.execute(
        select(m.FirmwareTarget.stage, m.FirmwareTarget.status, func.count())
        .where(m.FirmwareTarget.plan_id == id)
        .group_by(m.FirmwareTarget.stage, m.FirmwareTarget.status)
    ):
        counts.setdefault(stage, {})[state] = count
    return {
        **serialize(plan),
        "groups": [
            {**step, "stage": stage, "counts": counts.get(stage, {})} for stage, step in enumerate(plan.steps)
        ],
    }


def targets(db, id, stage, limit, offset):
    plan = get(db, m.FirmwarePlan, id)
    if stage >= len(plan.steps):
        raise HTTPException(404, "İşlem grubu bulunamadı")
    conditions = [m.FirmwareTarget.plan_id == id, m.FirmwareTarget.stage == stage]
    return {
        "items": [
            public_target(t)
            for t in db.scalars(
                select(m.FirmwareTarget)
                .where(*conditions)
                .order_by(m.FirmwareTarget.created_at, m.FirmwareTarget.id)
                .offset(offset)
                .limit(limit)
            )
        ],
        "total": db.scalar(select(func.count()).select_from(m.FirmwareTarget).where(*conditions)),
    }


def legacy(target):
    events = [
        {
            "id": "created",
            "kind": "evidence",
            "title": "Plan hedefi kaydedildi",
            "created_at": target.created_at.isoformat(),
            "response": "Komut veya cihaz yanıtı kaydı bu işlem için tutulmamış.",
        }
    ]
    for key, title in (("preflight_at", "Ön kontrol kaydı"), ("staged_at", "İmaj hazır kaydı")):
        if target.evidence.get(key):
            events.append(
                {
                    "id": key,
                    "kind": "evidence",
                    "title": title,
                    "created_at": target.evidence[key],
                    "response": "Kayıtlı işlem bilgisi; komut çıktısı bulunmuyor.",
                }
            )
    if target.finished_at:
        events.append(
            {
                "id": "finished",
                "kind": "evidence",
                "title": RESULTS.get(target.status, "Sonuç kaydı"),
                "created_at": target.finished_at.isoformat(),
                "response": target.error
                or (
                    "Doğrulanan sürüm: " + target.verified_version
                    if target.verified_version
                    else "İşlem durumu: " + target.status
                ),
            }
        )
    return events


def public_target(target):
    value = target_view(target)
    value["evidence"] = {key: item for key, item in value["evidence"].items() if key != "connection_stamp"}
    return value


def transcript(db, id, limit=40, offset=0):
    target = get(db, m.FirmwareTarget, id)
    image = db.get(m.FirmwareImage, target.image_id)
    total = db.scalar(
        select(func.count()).select_from(m.FirmwareEvent).where(m.FirmwareEvent.target_id == id)
    )
    old = legacy(target) if not total and not target.evidence.get("history_version") else []
    events = (
        [
            serialize(e)
            for e in db.scalars(
                select(m.FirmwareEvent)
                .where(m.FirmwareEvent.target_id == id)
                .order_by(m.FirmwareEvent.id)
                .offset(offset)
                .limit(limit)
            )
        ]
        if total
        else old[offset : offset + limit]
    )
    return {
        "target": public_target(target),
        "image": {
            "name": image.name,
            "original_name": image.original_name,
            "version": image.version,
            "sha256": image.sha256,
            "size_bytes": image.size_bytes,
            "family": image.family,
        },
        "items": events,
        "total": total or len(old),
        "legacy": not total and not target.evidence.get("history_version"),
    }
