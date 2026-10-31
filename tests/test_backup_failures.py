import asyncssh
import pytest
from netrix.configuration.failures import backup_failure
from netrix.configuration.validation import BackupError


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TimeoutError("PRIVATE-RESPONSE"), "ssh_timeout"),
        (asyncssh.PermissionDenied("PRIVATE-RESPONSE"), "ssh_authentication_failed"),
        (asyncssh.HostKeyNotVerifiable("PRIVATE-RESPONSE"), "ssh_host_key_failed"),
        (OSError("PRIVATE-RESPONSE"), "ssh_connection_failed"),
        (BackupError("aruba_incomplete"), "aruba_incomplete"),
        (ValueError("PRIVATE-RESPONSE"), "backup_failed"),
    ],
)
def test_backup_errors_are_specific_and_do_not_expose_remote_text(error, code):
    actual, message = backup_failure(error)
    assert actual == code
    assert "PRIVATE-RESPONSE" not in message


@pytest.mark.parametrize("attempts", [1, 3])
async def test_worker_preserves_retry_policy_and_records_safe_backup_timeout(env, monkeypatch, attempts):
    from netrix import models as m
    from netrix import worker
    from netrix.core import now
    from sqlalchemy import func, select

    with env() as db:
        job = m.Job(
            kind="backup",
            target_id="fixture",
            status="running",
            attempts=attempts,
            active_key="backup:fixture",
            heartbeat_at=now(),
        )
        db.add(job)
        db.commit()
        job_id = job.id

    async def fail(*args):
        raise TimeoutError("PRIVATE-RESPONSE")

    monkeypatch.setattr(worker, "collect_backup", fail)
    await worker.execute(job_id)
    with env() as db:
        job = db.get(m.Job, job_id)
        assert job.status == ("queued" if attempts == 1 else "failed")
        assert job.result["error_code"] == "ssh_timeout"
        assert "zaman aşımına" in job.error and "PRIVATE-RESPONSE" not in job.error
        assert (job.active_key is not None) == (attempts == 1)
        assert db.scalar(select(func.count()).select_from(m.Snapshot)) == 0
