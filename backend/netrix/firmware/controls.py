"""Plan controls preserve results and device reservations after unsafe boundaries."""

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select

from .. import models as m
from ..core import now
from ..identity.security import audit
from ..services import publish
from . import history
from .limits import MAX_CONCURRENCY
from .service import Input


class ConcurrencyInput(Input):
    concurrency: int = Field(ge=1, le=MAX_CONCURRENCY)


class ForceStopInput(Input):
    plan_name: str = Field(min_length=1, max_length=120)
    confirmed: bool = False


def locked_plan(db, id):
    plan = db.scalar(
        select(m.FirmwarePlan)
        .where(m.FirmwarePlan.id == id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not plan or plan.deleted_at:
        raise HTTPException(404, "Plan bulunamadı")
    return plan


def set_concurrency(db, id, value, user):
    plan = locked_plan(db, id)
    if plan.status in ("succeeded", "cancelled") or plan.cancel_requested:
        raise HTTPException(409, "Tamamlanmış veya durdurulmuş planın eşzamanlılığı değiştirilemez")
    old = plan.concurrency
    plan.concurrency = ConcurrencyInput(concurrency=value).concurrency
    audit(
        db,
        user,
        "concurrency",
        "firmware_plans",
        id,
        f"Eşzamanlı cihaz sayısı {old} → {value}; devam eden cihaz işlemleri kesilmedi",
    )
    db.commit()
    publish()
    return plan


def stop_plan(db, id, user, *, force=False, confirmation=None):
    plan = locked_plan(db, id)
    if force and (not confirmation or not confirmation.confirmed or confirmation.plan_name != plan.name):
        raise HTTPException(422, "Planın tam adını yazıp zorla durdurmayı onaylayın")
    if plan.status == "succeeded":
        raise HTTPException(409, "Tamamlanmış plan durdurulamaz")
    if plan.force_stop_requested or plan.cancel_requested and not force:
        return plan
    plan.cancel_requested = True
    plan.force_stop_requested = force
    targets = list(
        db.scalars(
            select(m.FirmwareTarget)
            .where(m.FirmwareTarget.plan_id == id)
            .order_by(m.FirmwareTarget.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    running = False
    for target in targets:
        if target.status == "running":
            running = True
            if force:
                target.evidence = {**target.evidence, "force_stop_requested": True}
            # The owning worker cancels its own task and classifies uncertainty.
        elif target.status == "queued":
            if target.phase == "reconcile":
                target.status = "attention"
            else:
                target.status, target.active_device = "cancelled", None
        elif target.status != "attention":
            target.active_device = None
        if target.status != "running" or force:
            target.transfer_expires_at = now()
        history.add_event(
            db,
            target,
            kind="phase",
            title="Yönetici zorla durdurma istedi" if force else "Yönetici sonraki işlemleri durdurdu",
            response="NETRIX oturumları kapatılacak. Cihazda başlamış yazımın durduğu varsayılmaz; belirsiz hedefler doğrulama bekler."
            if force
            else "Devam eden dosya yazımı kesilmedi; sonraki işler durduruldu.",
            finished=True,
        )
    if running:
        plan.status = "running"
    else:
        plan.status, plan.finished_at = "cancelled", now()
    audit(
        db,
        user,
        "force_stop" if force else "cancel",
        "firmware_plans",
        id,
        "Zorla durdurma istendi; yazım sonrası belirsiz hedeflerin kilidi korunacak"
        if force
        else "Sonraki firmware işlemleri durduruldu; devam eden yazım kesilmedi",
    )
    db.commit()
    publish()
    return plan


def remove_plan(db, id, user):
    plan = locked_plan(db, id)
    if plan.status in ("queued", "running") or db.scalar(
        select(m.FirmwareTarget.id)
        .where(
            m.FirmwareTarget.plan_id == id,
            (
                m.FirmwareTarget.status.in_(("queued", "running"))
                if plan.status != "draft"
                else m.FirmwareTarget.status == "running"
            )
            | m.FirmwareTarget.active_device.is_not(None),
        )
        .limit(1)
    ):
        raise HTTPException(
            409,
            "Önce planı durdurun ve belirsiz cihaz sonuçlarını doğrulayın; etkin veya ayrılmış hedef içeren plan silinemez",
        )
    plan.deleted_at = now()
    audit(
        db,
        user,
        "delete",
        "firmware_plans",
        id,
        "Plan listeden kaldırıldı; cihaz sonuçları, komut geçmişi ve yedekler korundu",
    )
    db.commit()
    publish()
