import io
import json
from datetime import UTC, datetime, timedelta
from zipfile import ZipFile

import pytest
from netrix import models as m
from netrix.core import now
from netrix.job_archives import archive_jobs, midnight
from sqlalchemy import func, select


def job(**kwargs):
    return m.Job(kind="backup", target_id="missing-device", status="succeeded", **kwargs)


def test_archive_all_pages_zip_download_delete_and_no_secrets(admin_client, env):
    with env() as db:
        db.add_all([job(result={"password": "NEVER-EXPORT", "config": "SECRET-CONFIG"}) for _ in range(103)])
        active = m.Job(kind="backup", target_id="running", status="running", active_key="backup:running")
        queued = m.Job(kind="backup", target_id="queued", status="queued")
        ping = m.Job(kind="ipam_ping", target_id="vlan", status="succeeded")
        db.add_all([active, queued, ping])
        db.commit()
        active_id = active.id
    assert admin_client.get("/api/v1/jobs?limit=1").json()["total"] == 105
    result = admin_client.post("/api/v1/job-archives").json()
    assert result["archived_jobs"] == 103
    assert admin_client.get("/api/v1/jobs").json()["total"] == 2
    assert admin_client.post("/api/v1/job-archives").json()["archived_jobs"] == 0
    listing = admin_client.get("/api/v1/job-archives").json()
    assert listing["total"] == 1
    item = listing["items"][0]
    assert "content" not in item and item["job_count"] == 103 and item["source"] == "manual"
    response = admin_client.get(f"/api/v1/job-archives/{item['id']}/download")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    assert item["filename"] in response.headers["content-disposition"]
    with ZipFile(io.BytesIO(response.content)) as zipfile:
        assert zipfile.testzip() is None
        raw = zipfile.read("gorevler.json")
    assert b"NEVER-EXPORT" not in raw and b"SECRET-CONFIG" not in raw
    content = json.loads(raw)
    assert len(content["jobs"]) == 103 and content["timezone"] == "Europe/Istanbul"
    assert all(
        j["status"] == "succeeded" and j["title"] and j["description"] and "error" in j
        for j in content["jobs"]
    )
    response = admin_client.post("/api/v1/job-archives/delete", json={"ids": [item["id"], item["id"]]})
    assert response.json() == {"deleted": 1}
    assert admin_client.get("/api/v1/job-archives").json()["total"] == 0
    assert admin_client.get("/api/v1/jobs").json()["total"] == 2
    assert admin_client.get(f"/api/v1/job-archives/{item['id']}/download").status_code == 404
    with env() as db:
        assert db.get(m.Job, active_id).active_key == "backup:running"
        assert db.scalar(select(func.count()).select_from(m.Job)) == 106


def test_midnight_istanbul_and_catchup_are_idempotent(env):
    cutoff = midnight(datetime(2026, 11, 10, 21, 0, tzinfo=UTC))
    assert cutoff == datetime(2026, 11, 10, 21, 0, tzinfo=UTC)
    assert midnight(cutoff - timedelta(seconds=1)) == cutoff - timedelta(days=1)
    with env() as db:
        # A previous-day task which finishes after midnight belongs to the next export.
        db.add_all(
            [
                job(created_at=cutoff - timedelta(hours=1), finished_at=cutoff - timedelta(seconds=1)),
                job(created_at=cutoff - timedelta(hours=1), finished_at=cutoff + timedelta(seconds=1)),
                job(created_at=cutoff - timedelta(days=3)),  # Legacy task without finish timestamp.
                m.Job(
                    kind="backup", target_id="active", status="running", created_at=cutoff - timedelta(days=3)
                ),
            ]
        )
        db.commit()
        assert archive_jobs(db, cutoff=cutoff)["archived_jobs"] == 2
        db.commit()
        assert archive_jobs(db, cutoff=cutoff)["archived_jobs"] == 0
        assert archive_jobs(db, cutoff=cutoff + timedelta(days=1))["archived_jobs"] == 1
        db.commit()
        assert all(a.source == "scheduled" for a in db.scalars(select(m.JobArchive)))


def test_rollback_never_hides_unarchived_tasks(env):
    with env() as db:
        db.add(job())
        db.commit()
        assert archive_jobs(db)["archived_jobs"] == 1
        db.rollback()
        assert db.scalar(select(func.count()).select_from(m.JobArchive)) == 0
        assert db.scalar(select(m.Job)).archived_at is None


def test_multiple_zip_chunks_and_bulk_delete(admin_client, env):
    with env() as db:
        db.add_all([job() for _ in range(1001)])
        db.commit()
    result = admin_client.post("/api/v1/job-archives").json()
    assert result["archived_jobs"] == 1001 and len(result["archive_ids"]) == 2
    assert admin_client.post("/api/v1/job-archives/delete", json={"ids": result["archive_ids"]}).json() == {
        "deleted": 2
    }
    assert admin_client.get("/api/v1/jobs").json()["total"] == 0


@pytest.mark.parametrize("status", ["succeeded", "partial", "failed", "cancelled"])
def test_all_terminal_statuses_are_archived(env, status):
    with env() as db:
        db.add(m.Job(kind="discovery", target_id="missing", status=status))
        db.commit()
        assert archive_jobs(db)["archived_jobs"] == 1


def test_archive_permissions(admin_client, env):
    with env() as db:
        db.add(job())
        db.commit()
    archive_id = admin_client.post("/api/v1/job-archives").json()["archive_ids"][0]
    with env() as db:
        user = db.scalar(select(m.User))
        user.role = "viewer"
        db.commit()
    assert admin_client.get("/api/v1/job-archives").status_code == 200
    assert admin_client.get(f"/api/v1/job-archives/{archive_id}/download").status_code == 200
    assert admin_client.post("/api/v1/job-archives").status_code == 403
    assert admin_client.post("/api/v1/job-archives/delete", json={"ids": [archive_id]}).status_code == 403
    admin_client.cookies.clear()
    assert admin_client.get("/api/v1/job-archives").status_code == 401
    assert admin_client.get(f"/api/v1/job-archives/{archive_id}/download").status_code == 401


def test_scheduler_archives_without_a_browser(env, monkeypatch):
    from netrix import scheduler
    from netrix.ipam import scan_schedules

    monkeypatch.setattr(scan_schedules, "dispatch_due", lambda: None)
    monkeypatch.setattr(scheduler, "publish", lambda: None)
    with env() as db:
        db.add(job(created_at=now() - timedelta(days=2)))
        db.commit()
    scheduler.tick(include_ping=False)
    scheduler.tick(include_ping=False)
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.JobArchive)) == 1
        assert db.scalar(select(m.Job)).archived_at is not None
