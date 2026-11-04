from netrix import models as m
from netrix import worker
from sqlalchemy.exc import OperationalError


async def test_worker_records_numeric_database_error_without_sensitive_output(
    admin_client, inventory, env, monkeypatch, caplog
):
    async def fail(*args):
        raise OperationalError(
            "SQL-MUST-NOT-LEAK", {"secret": "PARAMETER-MUST-NOT-LEAK"}, Exception(1213, "RAW-MUST-NOT-LEAK")
        )

    monkeypatch.setattr(worker, "discover", fail)
    job = admin_client.post(
        "/api/v1/jobs", json={"kind": "discovery", "target_id": inventory["scope"]["id"]}
    ).json()
    assert worker.claim() == job["id"]
    await worker.execute(job["id"], object())
    with env() as db:
        saved = db.get(m.Job, job["id"])
        assert saved.status == "queued"
        assert saved.result["database_error_code"] == 1213
        assert "MUST-NOT-LEAK" not in saved.error + str(saved.result)
    assert "error_class=OperationalError db_code=1213" in caplog.text
    assert "MUST-NOT-LEAK" not in caplog.text
