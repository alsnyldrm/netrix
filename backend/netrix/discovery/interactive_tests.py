"""Admission for interactive probes/comparisons, independent of scheduled/bulk work."""

from datetime import datetime

from fastapi import HTTPException
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from .. import models as m
from ..core import now, redis_client

CAPACITY = 4
POLL_SECONDS = 0.25


def interactive_condition():
    return func.coalesce(m.Job.result["interactive"].as_boolean(), False).is_(True)


def start(db, kind, device_id, user, *, prepare=None):
    from .. import services as svc

    client = redis_client()
    try:
        stamp = client.get("netrix:tests:heartbeat")
        age = (now() - datetime.fromisoformat(stamp)).total_seconds() if stamp else 999
        if not -5 <= age < 15:
            raise HTTPException(
                503, "Etkileşimli işlem hizmeti hazır değil. İstek sıraya alınmadı; yeniden deneyin."
            )
        # Redis serializes admissions across API processes/Galera nodes. Locking
        # reads below see committed rows even when authentication began an old view.
        with client.lock("netrix:tests:admission", timeout=60, blocking_timeout=0.5):
            for attempt in range(2):
                try:
                    job = _admit(db, kind, device_id, user, prepare=prepare)
                    break
                except OperationalError as exc:
                    if attempt or exc.orig.args[0] not in (1020, 1213):
                        raise
                    # Retry the DB transaction once, not the device probe. No
                    # request is left waiting in a network work queue.
                    db.rollback()
        svc.publish()
        return svc.serialize(job)
    except (RedisError, ValueError, TypeError):
        raise HTTPException(503, "Etkileşimli işlem hizmetine ulaşılamadı. Yeniden deneyin.") from None


def _admit(db, kind, device_id, user, *, prepare=None):
    from .. import services as svc

    job = svc.enqueue(db, kind, device_id, user, commit=False)
    if prepare is not None:
        prepare(job)
    if job.status == "running" or job.result.get("interactive"):
        return job
    active = list(
        db.scalars(
            select(m.Job)
            .where(m.Job.status.in_(("queued", "running")), interactive_condition())
            .with_for_update()
        )
    )
    if len(active) >= CAPACITY:
        raise HTTPException(
            429,
            "Dört etkileşimli işlem çalışıyor. İstek sıraya alınmadı; bir işlem tamamlanınca yeniden deneyin.",
        )
    job.result = {**job.result, "interactive": True}
    # Promote an existing pending bulk probe too; never wait for its backoff.
    job.available_at = now()
    db.commit()
    return job
