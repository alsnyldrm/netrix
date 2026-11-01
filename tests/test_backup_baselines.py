import hashlib
from datetime import timedelta

import pytest
from netrix import models as m
from netrix import worker
from netrix.core import now
from netrix.identity.security import encrypt
from sqlalchemy import func, select

ERROR = "SSH command execution is not supported.\r\n"
CONFIG = "hostname switch\ninterface 1\n description original\n"


@pytest.fixture
def device(admin_client, inventory):
    profile = admin_client.post(
        "/api/v1/credentials",
        json={
            "name": "SSH baseline",
            "protocol": "ssh",
            "secret": {"username": "fixture", "password": "fixture-password"},
        },
    ).json()
    response = admin_client.post(
        "/api/v1/devices",
        json={
            "name": "Baseline switch",
            "management_ip": "192.0.2.1",
            "vrf_id": inventory["vrf"]["id"],
            "adapter": "ios",
            "config_credential_id": profile["id"],
        },
    )
    assert response.status_code == 201
    return response.json()


def add_snapshot(db, device_id, content, offset, changed=False):
    job = m.Job(kind="backup", target_id=device_id, status="succeeded")
    db.add(job)
    db.flush()
    row = m.Snapshot(
        device_id=device_id,
        job_id=job.id,
        encrypted_content=encrypt(content),
        size_bytes=len(content.encode()),
        fingerprint=hashlib.sha256(content.encode()).hexdigest(),
        changed=changed,
        created_at=now() + timedelta(minutes=offset),
    )
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize(
    "older,current,expected",
    [
        (None, CONFIG, False),
        (CONFIG, CONFIG, False),
        (CONFIG, CONFIG.replace("original", "updated"), True),
        (CONFIG, CONFIG.replace("original", "updated") + "password PRIVATE-SECRET\n", True),
    ],
)
async def test_worker_skips_error_baseline_and_only_reports_real_changes(
    admin_client, device, env, monkeypatch, older, current, expected
):
    with env() as db:
        if older:
            add_snapshot(db, device["id"], older, -3)
        add_snapshot(db, device["id"], ERROR, -2)
        db.commit()

    async def fetch(*args):
        return current

    monkeypatch.setattr(worker, "fetch_config", fetch)
    job_id = device["backup"]["job_id"]
    await worker.execute(job_id)
    with env() as db:
        row = db.scalar(select(m.Snapshot).where(m.Snapshot.job_id == job_id))
        assert row is not None and row.changed is expected
        assert db.scalar(
            select(func.count()).select_from(m.Event).where(m.Event.kind == "config_change")
        ) == int(expected)
        snapshot_id = row.id
    changes = admin_client.get("/api/v1/inventory/snapshots", params={"changed_only": True}).json()
    assert changes["total"] == int(expected)
    response = admin_client.get(f"/api/v1/snapshots/{snapshot_id}/diff")
    assert response.status_code == 200, response.text
    assert "PRIVATE-SECRET" not in response.text and "SSH command execution" not in response.text
    if older is None:
        assert response.json()["previous_id"] == snapshot_id
        assert response.json()["diff"] == ""
    else:
        assert bool(response.json()["diff"]) is expected


def test_diff_skips_invalid_same_timestamp_and_other_device(admin_client, device, inventory, env):
    with env() as db:
        first = add_snapshot(db, device["id"], CONFIG, -3)
        bad = add_snapshot(db, device["id"], ERROR, -2)
        current = add_snapshot(db, device["id"], CONFIG.replace("original", "updated"), -1)
        first.created_at = bad.created_at = current.created_at
        first.id, bad.id, current.id = "0001", "0002", "0003"
        other = m.Device(name="Other", management_ip="192.0.2.2", vrf_id=inventory["vrf"]["id"])
        db.add(other)
        db.flush()
        foreign = add_snapshot(db, other.id, CONFIG, -1)
        db.commit()
        foreign_id = foreign.id
    result = admin_client.get("/api/v1/snapshots/0003/diff")
    assert result.status_code == 200 and result.json()["previous_id"] == "0001"
    assert "+ description updated" in result.json()["diff"]
    assert (
        admin_client.get("/api/v1/snapshots/0003/diff", params={"previous_id": foreign_id}).status_code == 422
    )
    assert admin_client.get("/api/v1/snapshots/0003/diff", params={"previous_id": "0002"}).status_code == 422


def test_repair_preserves_backups_and_real_changes_and_is_idempotent(admin_client, device, env):
    from netrix.configuration.history import repair_change_flags

    with env() as db:
        rows = [
            add_snapshot(db, device["id"], text, i - 5, changed)
            for i, (text, changed) in enumerate(
                [(ERROR, True), (CONFIG, True), (CONFIG, True), (CONFIG + "vlan 10\n", True)]
            )
        ]
        ids = [r.id for r in rows]
        db.commit()
        preview = repair_change_flags(db, device["id"])
        assert [item["snapshot_id"] for item in preview] == ids[:3]
        assert all(db.get(m.Snapshot, id).changed for id in ids)
        assert repair_change_flags(db, device["id"], apply=True) == preview
        db.commit()
        assert [db.get(m.Snapshot, id).changed for id in ids] == [False, False, False, True]
        assert repair_change_flags(db, device["id"], apply=True) == []
        assert (
            db.scalar(select(func.count()).select_from(m.Audit).where(m.Audit.action == "repair_change_flag"))
            == 3
        )
    result = admin_client.get("/api/v1/inventory/snapshots", params={"changed_only": True}).json()
    assert [s["id"] for s in result["items"]] == [ids[-1]]


def test_repair_selects_first_surviving_config_as_base(admin_client, device, env):
    from netrix.configuration.history import repair_change_flags

    with env() as db:
        first = add_snapshot(db, device["id"], CONFIG, -2, True)
        db.commit()
        assert len(repair_change_flags(db, device["id"], apply=True)) == 1
        assert not first.changed
        assert db.get(m.Device, device["id"]).base_snapshot_id == first.id
