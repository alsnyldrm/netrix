from datetime import timedelta

import pytest
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


@pytest.mark.parametrize("status", ["queued", "running", "succeeded", "partial", "failed", "cancelled"])
def test_ping_jobs_are_excluded_before_pagination_and_search(admin_client, env, status):
    with env() as db:
        visible = [
            m.Job(kind="ipam_discover", target_id="vlan", created_at=now() - timedelta(minutes=2)),
            m.Job(kind="backup", target_id="device", created_at=now() - timedelta(minutes=1)),
        ]
        ping = m.Job(kind="ipam_ping", target_id="vlan", status=status)
        db.add_all([*visible, ping])
        db.commit()
        expected = [row.id for row in reversed(visible)]
        ping_id = ping.id
    for offset, id in enumerate(expected):
        response = admin_client.get("/api/v1/jobs", params={"limit": 1, "offset": offset})
        assert response.status_code == 200
        assert response.json()["total"] == 2
        assert [row["id"] for row in response.json()["items"]] == [id]
    result = admin_client.get("/api/v1/jobs", params={"q": "ipam"}).json()
    assert result["total"] == 1 and result["items"][0]["kind"] == "ipam_discover"
    assert admin_client.get("/api/v1/jobs", params={"q": "ipam_ping"}).json()["total"] == 0
    # Operational state remains available to the worker; hiding is not deletion.
    with env() as db:
        assert db.get(m.Job, ping_id).status == status


def test_running_job_badge_excludes_background_ping(admin_client, env):
    with env() as db:
        db.add_all(
            [
                m.Job(kind="ipam_ping", target_id="vlan", status="queued"),
                m.Job(kind="ipam_ping", target_id="vlan", status="running"),
                m.Job(kind="backup", target_id="device", status="running"),
                m.Job(kind="ipam_discover", target_id="vlan", status="queued"),
                m.Job(kind="backup", target_id="device", status="succeeded"),
            ]
        )
        db.commit()
    result = admin_client.get("/api/v1/dashboard", headers={"Cache-Control": "no-cache"})
    assert result.status_code == 200
    assert result.json()["counts"]["running_jobs"] == 2
