import logging
import signal
import time

from fastapi import HTTPException
from sqlalchemy import delete, select

from . import models as m
from .configuration.management import policy, prune
from .core import now, session_factory
from .services import enqueue, publish
from .worker import heartbeat

stop = False
log = logging.getLogger("netrix.scheduler")


def dispatch_pings(at=None):
    """An independent ICMP clock; no client page can dispatch this work."""
    at = at or now()
    with session_factory()() as db:
        for vlan in db.scalars(select(m.VLAN).where(m.VLAN.cidr.is_not(None), m.VLAN.ping_enabled.is_(True))):
            if not vlan.last_ping_at or (at - vlan.last_ping_at).total_seconds() >= vlan.ping_interval:
                try:
                    enqueue(db, "ipam_ping", vlan.id, ipam_origin="ping_timer")
                except HTTPException:
                    db.rollback()


def tick(*, include_ping=True):
    from .ipam.scan_schedules import dispatch_due
    from .job_archives import archive_jobs, midnight

    if include_ping:
        dispatch_pings()
    dispatch_due()
    with session_factory()() as db:
        archive_jobs(db, cutoff=midnight(now()))
        db.commit()
        for scope in db.scalars(
            select(m.Scope).where(m.Scope.enabled.is_(True), m.Scope.interval_seconds > 0)
        ):
            if not scope.last_run_at or (now() - scope.last_run_at).total_seconds() >= scope.interval_seconds:
                enqueue(db, "discovery", scope.id)
        for device in db.scalars(select(m.Device).where(m.Device.lifecycle_status == "active")):
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
    next_maintenance = 0.0
    while not stop:
        heartbeat("scheduler")
        try:
            dispatch_pings()
            if time.monotonic() >= next_maintenance:
                tick(include_ping=False)
                next_maintenance = time.monotonic() + 15
        except Exception as exc:
            log.warning("scheduler_cycle_failed error_class=%s", type(exc).__name__)
        for _ in range(5):
            if stop:
                break
            time.sleep(1)
