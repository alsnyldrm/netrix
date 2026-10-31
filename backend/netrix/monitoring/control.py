"""Temporary global pause without changing per-device monitoring preferences."""

from sqlalchemy import update

from .. import models as m
from ..core import now, settings

PAUSED_MESSAGE = "İzleme görevleri geçici olarak kapalı; kuyruğa alınmadı."


def cancel_paused_jobs(db):
    if settings().monitor_jobs_enabled:
        return
    db.execute(
        update(m.Job)
        .where(m.Job.kind == "monitor", m.Job.status == "queued")
        .values(
            status="cancelled",
            cancel_requested=True,
            active_key=None,
            finished_at=now(),
            error="İzleme görevleri geçici olarak kapatıldığı için iptal edildi.",
        )
    )
    db.execute(
        update(m.Job)
        .where(m.Job.kind == "monitor", m.Job.status == "running", m.Job.cancel_requested.is_(False))
        .values(cancel_requested=True)
    )
