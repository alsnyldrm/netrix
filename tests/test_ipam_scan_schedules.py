"""Only configured VLANs are dispatched; calendar rules and durable limits survive restarts."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import make_vlan
from netrix import models as m
from netrix.core import now
from netrix.ipam import scan_schedules as service
from sqlalchemy import select


@pytest.fixture
def setup(env, inventory, admin_client):
    with env() as db:
        vlans = [
            make_vlan(vid=20 + i, cidr=f"192.0.{i + 2}.0/30", vrf_id=inventory["vrf"]["id"]) for i in range(2)
        ]
        db.add_all(vlans)
        db.commit()
        ids = [v.id for v in vlans]
    payload = dict(
        name="Sunucular",
        vlan_ids=ids,
        frequency="daily",
        repeat_every=1,
        start_at=(now() + timedelta(hours=1)).isoformat(),
        run_limit=2,
    )
    return admin_client, env, payload


def create(setup, **changes):
    c, sf, data = setup
    response = c.post("/api/v1/ipam/scan-groups", json={**data, **changes})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "frequency,repeat_every,start,at,expected",
    [
        ("daily", 2, "2026-11-03T06:00:00+00:00", "2026-11-05T06:00:00+00:00", "2026-11-07T06:00:00+00:00"),
        ("weekly", 2, "2026-11-03T06:00:00+00:00", "2026-11-04T06:00:00+00:00", "2026-11-17T06:00:00+00:00"),
        ("monthly", 1, "2028-01-31T06:00:00+00:00", "2028-02-01T06:00:00+00:00", "2028-02-29T06:00:00+00:00"),
        ("monthly", 1, "2028-01-31T06:00:00+00:00", "2028-02-29T06:00:00+00:00", "2028-03-31T06:00:00+00:00"),
        ("daily", 1, "2026-11-03T06:00:00+00:00", "2026-11-01T06:00:00+00:00", "2026-11-03T06:00:00+00:00"),
    ],
)
def test_calendar(frequency, repeat_every, start, at, expected):
    group = SimpleNamespace(
        frequency=frequency,
        repeat_every=repeat_every,
        start_at=datetime.fromisoformat(start),
        timezone="Europe/Istanbul",
    )
    assert service.next_after(group, datetime.fromisoformat(at)).isoformat() == expected


def test_dispatch_is_atomic_reuses_active_jobs_and_stops_after_limit(setup):
    c, sf, payload = setup
    group = create(setup)
    at = datetime.fromisoformat(group["start_at"])
    service.dispatch_due(at - timedelta(seconds=1))
    assert c.get(f"/api/v1/ipam/scan-groups/{group['id']}/runs").json()["items"] == []
    service.dispatch_due(at)
    service.dispatch_due(at)
    with sf() as db:
        jobs = list(db.scalars(select(m.Job).where(m.Job.kind == "ipam_discover")))
        assert len(jobs) == 2 and {j.target_id for j in jobs} == set(payload["vlan_ids"])
        assert db.get(m.IPAMScanGroup, group["id"]).run_count == 1
    # A second due slot while scans run reuses their durable active keys.
    service.dispatch_due(at + timedelta(days=1))
    service.dispatch_due(at + timedelta(days=30))
    with sf() as db:
        row = db.get(m.IPAMScanGroup, group["id"])
        assert row.run_count == 2 and row.next_run_at is None
        assert len(list(db.scalars(select(m.Job).where(m.Job.kind == "ipam_discover")))) == 2
    runs = c.get(f"/api/v1/ipam/scan-groups/{group['id']}/runs").json()["items"]
    assert len(runs) == 2 and all(j["status"] == "queued" for r in runs for j in r["jobs"])


def test_pause_edit_resume_and_calendar_change_preserve_history(setup):
    c, sf, payload = setup
    group = create(setup, enabled=False)
    at = datetime.fromisoformat(group["start_at"]) + timedelta(days=35)
    service.dispatch_due(at)
    assert c.get(f"/api/v1/ipam/scan-groups/{group['id']}/runs").json()["items"] == []
    url = f"/api/v1/ipam/scan-groups/{group['id']}"
    assert c.put(url, json=payload).status_code == 200
    service.dispatch_due(at)
    row = c.get("/api/v1/ipam/scan-groups").json()["items"][0]
    assert row["run_count"] == 1 and datetime.fromisoformat(row["next_run_at"]) > at
    # Editing only membership/description doesn't silently reset the counter.
    assert (
        c.put(url, json={**payload, "description": "Yeni not", "vlan_ids": payload["vlan_ids"][:1]}).json()[
            "run_count"
        ]
        == 1
    )
    assert c.put(url, json={**payload, "repeat_every": 2}).json()["run_count"] == 0
    service.dispatch_due(at)
    assert len(c.get(url + "/runs").json()["items"]) == 2


def test_membership_conflicts_invalid_targets_and_delete_keep_vlans_and_jobs(setup):
    c, sf, payload = setup
    group = create(setup)
    assert c.post("/api/v1/ipam/scan-groups", json={**payload, "name": "İkinci"}).status_code == 409
    for data in (
        {"vlan_ids": []},
        {"vlan_ids": ["missing"]},
        {"frequency": "hourly"},
        {"repeat_every": 0},
        {"run_limit": 0},
        {"start_at": "2026-11-03T12:00"},
        {"timezone": "Invalid/Zone"},
    ):
        assert c.post("/api/v1/ipam/scan-groups", json={**payload, **data}).status_code == 422
    service.dispatch_due(datetime.fromisoformat(group["start_at"]))
    assert c.delete(f"/api/v1/ipam/scan-groups/{group['id']}").status_code == 204
    with sf() as db:
        assert all(db.get(m.VLAN, id) for id in payload["vlan_ids"])
        assert len(list(db.scalars(select(m.Job).where(m.Job.kind == "ipam_discover")))) == 2
        assert not list(db.scalars(select(m.IPAMScanMember)))


def test_deleted_vlans_stop_empty_group_and_failed_targets_are_reported(setup):
    c, sf, payload = setup
    group = create(setup)
    with sf() as db:
        db.get(m.VLAN, payload["vlan_ids"][0]).cidr = None
        db.commit()
    at = datetime.fromisoformat(group["start_at"])
    service.dispatch_due(at)
    run = c.get(f"/api/v1/ipam/scan-groups/{group['id']}/runs").json()["items"][0]
    assert len(run["errors"]) == len(run["jobs"]) == 1
    with sf() as db:
        for id in payload["vlan_ids"]:
            db.delete(db.get(m.VLAN, id))
        db.commit()
    service.dispatch_due(at + timedelta(days=1))
    row = c.get("/api/v1/ipam/scan-groups").json()["items"][0]
    assert row["enabled"] is False and row["next_run_at"] is None


def test_scheduler_group_owns_full_scan_but_not_ping(setup, monkeypatch):
    from netrix import scheduler

    c, sf, payload = setup
    create(setup, vlan_ids=payload["vlan_ids"][:1], enabled=False)
    with sf() as db:
        for id in payload["vlan_ids"]:
            row = db.get(m.VLAN, id)
            row.discovery_enabled = row.ping_enabled = True
        db.commit()
    calls = []
    monkeypatch.setattr(scheduler, "enqueue", lambda db, kind, id, **kwargs: calls.append((kind, id)))
    scheduler.tick()
    assert ("ipam_discover", payload["vlan_ids"][0]) not in calls
    assert ("ipam_discover", payload["vlan_ids"][1]) not in calls
    assert all(("ipam_ping", id) in calls for id in payload["vlan_ids"])


def test_roles_can_read_but_only_operators_can_write(setup):
    c, sf, payload = setup
    group = create(setup)
    with sf() as db:
        db.scalar(select(m.User)).role = "viewer"
        db.commit()
    url = "/api/v1/ipam/scan-groups"
    assert c.get(url).status_code == 200
    assert c.get(url + f"/{group['id']}/runs").status_code == 200
    assert c.post(url, json=payload).status_code == 403
    assert c.put(url + f"/{group['id']}", json=payload).status_code == 403
    assert c.delete(url + f"/{group['id']}").status_code == 403
    with sf() as db:
        db.scalar(select(m.User)).role = "operator"
        db.commit()
    assert c.put(url + f"/{group['id']}", json=payload).status_code == 200
    assert c.delete(url + f"/{group['id']}").status_code == 403
