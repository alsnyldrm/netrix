"""Atomic ZIP exports of finished task history; operational job references survive."""

import io
import json
from datetime import UTC
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import delete, func, select, text

from . import models as m
from . import schemas as s
from .core import db_session, now
from .identity.security import audit, current_user, operator
from .job_details import DESCRIPTIONS, summaries
from .services import get, publish

router = APIRouter(prefix="/api/v1/job-archives", tags=["Görev Arşivi"])
TERMINAL = ("succeeded", "partial", "failed", "cancelled")


def midnight(at):
    return (
        at.astimezone(ZoneInfo("Europe/Istanbul"))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )


def archive_jobs(db, *, user=None, cutoff=None):
    """Caller commits ZIPs and visibility together. Serialize manual/timer races."""
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(72613480)"))
    stamp = now()
    conditions = [m.Job.archived_at.is_(None), m.Job.kind != "ipam_ping", m.Job.status.in_(TERMINAL)]
    if cutoff is not None:
        conditions.append(func.coalesce(m.Job.finished_at, m.Job.created_at) < cutoff)
    count, archives = 0, []
    while True:
        jobs = list(
            db.scalars(select(m.Job).where(*conditions).order_by(m.Job.created_at, m.Job.id).limit(1000))
        )
        if not jobs:
            break
        # Export only the same public summary fields as the task center, never
        # arbitrary result JSON, credentials, commands or configuration content.
        records = [
            dict(
                summary,
                id=job.id,
                kind=job.kind,
                target_id=job.target_id,
                status=job.status,
                description=DESCRIPTIONS.get(job.kind, ("Geçmiş görev", ""))[1],
                error=job.error,
                attempts=job.attempts,
                progress=job.progress,
                total=job.total,
                created_at=job.created_at.isoformat(),
                finished_at=job.finished_at.isoformat() if job.finished_at else None,
            )
            for job, summary in zip(jobs, summaries(db, jobs))
        ]
        archive = m.JobArchive(
            id=m.uid(),
            job_count=len(jobs),
            source="scheduled" if cutoff else "manual",
            created_at=stamp,
            updated_at=stamp,
        )
        archive.filename = f"netrix-gorevler-{stamp.astimezone(ZoneInfo('Europe/Istanbul')):%Y%m%d-%H%M%S}-{archive.id[:8]}.zip"
        buffer = io.BytesIO()
        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as output:
            output.writestr(
                "gorevler.json",
                json.dumps(
                    {
                        "format_version": 1,
                        "archived_at": stamp.isoformat(),
                        "timezone": "Europe/Istanbul",
                        "source": archive.source,
                        "jobs": records,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        archive.content = buffer.getvalue()
        archive.size_bytes = len(archive.content)
        db.add(archive)
        for job in jobs:
            job.archived_at = stamp
        db.flush()
        count += len(jobs)
        archives.append(archive.id)
    if count:
        audit(db, user, "archive_jobs", "job_archives", None, f"{count} görev ZIP arşivine taşındı")
    return {"archived_jobs": count, "archive_ids": archives}


@router.post("", status_code=201)
def create(user=Depends(operator), db=Depends(db_session)):
    result = archive_jobs(db, user=user)
    db.commit()
    publish()
    return result


@router.get("")
def listing(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(current_user),
    db=Depends(db_session),
):
    rows = db.scalars(
        select(m.JobArchive)
        .order_by(m.JobArchive.created_at.desc(), m.JobArchive.id)
        .offset(offset)
        .limit(limit)
    )
    return {
        "total": db.scalar(select(func.count()).select_from(m.JobArchive)),
        "items": [
            {
                "id": row.id,
                "filename": row.filename,
                "job_count": row.job_count,
                "size_bytes": row.size_bytes,
                "source": row.source,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/{id}/download")
def download(id: str, user=Depends(current_user), db=Depends(db_session)):
    row = get(db, m.JobArchive, id)
    audit(db, user, "download", "job_archives", id, "Görev ZIP arşivi indirildi")
    content, filename = row.content, row.filename
    db.commit()
    return Response(
        content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/delete")
def remove(payload: s.SelectionInput, user=Depends(operator), db=Depends(db_session)):
    ids = list(dict.fromkeys(payload.ids))
    deleted = db.execute(delete(m.JobArchive).where(m.JobArchive.id.in_(ids))).rowcount
    audit(db, user, "delete", "job_archives", None, f"{deleted} görev ZIP arşivi silindi")
    db.commit()
    publish()
    return {"deleted": deleted}
