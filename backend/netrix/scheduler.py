import logging
import signal
import time
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select

from . import models as m
from .alerting.engine import evaluate
from .configuration.management import policy, prune
from .core import now, session_factory, settings
from .services import enqueue, publish
from .worker import heartbeat

stop = False
log = logging.getLogger("netrix.scheduler")


def tick():
    with session_factory()() as db:
        for scope in db.scalars(
            select(m.Scope).where(m.Scope.enabled.is_(True), m.Scope.interval_seconds > 0)
        ):
            if not scope.last_run_at or (now() - scope.last_run_at).total_seconds() >= scope.interval_seconds:
                enqueue(db, "discovery", scope.id)
        for device in db.scalars(select(m.Device).where(m.Device.lifecycle_status == "active")):
            if device.monitoring_enabled and (
                not device.last_monitor_at
                or (now() - device.last_monitor_at).total_seconds() >= device.monitor_interval
            ):
                try:
                    enqueue(db, "monitor", device.id)
                except HTTPException:
                    db.rollback()
            latest_backup_attempt = db.scalar(
                select(m.Job.created_at)
                .where(m.Job.kind == "backup", m.Job.target_id == device.id)
                .order_by(m.Job.created_at.desc())
                .limit(1)
            )
            backup_reference = max(
                [v for v in (device.last_backup_at, latest_backup_attempt) if v], default=None
            )
            interval, _ = policy(db, device)
            if interval and (not backup_reference or (now() - backup_reference).total_seconds() >= interval):
                try:
                    enqueue(db, "backup", device.id)
                except HTTPException:
                    db.rollback()
            db.scalar(select(m.Device).where(m.Device.id == device.id).with_for_update())
            prune(db, device)
            if device.monitoring_enabled:
                last = device.last_seen_at or device.created_at
                evaluate(db, device, "no_data", (now() - last).total_seconds())
        db.execute(
            delete(m.Sample).where(
                m.Sample.created_at < now() - timedelta(days=settings().sample_retention_days)
            )
        )
        db.execute(delete(m.AuthSession).where(m.AuthSession.expires_at < now()))
        db.commit()
    publish()


def request_stop(*args):
    global stop
    stop = True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    while not stop:
        heartbeat("scheduler")
        try:
            tick()
        except Exception as exc:
            log.warning("scheduler_cycle_failed error_class=%s", type(exc).__name__)
        for _ in range(15):
            if stop:
                break
            time.sleep(1)
