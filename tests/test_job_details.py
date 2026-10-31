from datetime import timedelta

from netrix import models as m
from netrix.core import now
from netrix.job_details import DESCRIPTIONS
from netrix.services import CONNECTION_TESTS


def test_scope_details_are_readable_and_do_not_expose_raw_results(admin_client, inventory, env):
    with env() as db:
        job = m.Job(
            kind="discovery",
            target_id=inventory["scope"]["id"],
            status="partial",
            progress=1,
            total=2,
            result={
                "reachable": 1,
                "unresponsive": 1,
                "private_secret": "NEVER-SHOW",
                "started_at": now().isoformat(),
            },
            created_at=now() - timedelta(seconds=10),
            finished_at=now(),
        )
        db.add(job)
        db.commit()
        id = job.id
    response = admin_client.get(f"/api/v1/jobs/{id}/details")
    assert response.status_code == 200
    detail = response.json()
    assert detail["title"] == "SNMP ağ keşfi"
    assert inventory["scope"]["cidr"] in detail["target_label"]
    assert all(isinstance(p, str) for p in detail["paragraphs"])
    assert any("SNMP" in p and "LLDP/CDP" in p for p in detail["paragraphs"])
    assert any("Yanıt veren: 1" in p for p in detail["paragraphs"])
    assert detail["queue_seconds"] >= 9
    assert "NEVER-SHOW" not in response.text and "private_secret" not in response.text
    items = admin_client.get("/api/v1/jobs").json()["items"]
    assert items[0]["title"] == detail["title"] and items[0]["target_label"] == detail["target_label"]


def test_missing_target_and_old_timestamp_do_not_break_history(admin_client, env):
    with env() as db:
        row = m.Job(kind="backup", target_id="deleted", status="failed")
        db.add(row)
        db.commit()
        id = row.id
    detail = admin_client.get(f"/api/v1/jobs/{id}/details").json()
    assert "artık mevcut değil" in detail["target_label"]
    assert detail["started_at"] is None and detail["queue_seconds"] is None
    assert admin_client.get("/api/v1/jobs/missing/details").status_code == 404


def test_all_supported_connection_tests_have_descriptions():
    assert all(kind in DESCRIPTIONS for kind in CONNECTION_TESTS)
