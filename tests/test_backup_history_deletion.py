import pytest
from netrix import models as m
from netrix.core import now
from sqlalchemy import select
from test_vlan_configuration import device, snapshot

PATH = "/api/v1/configuration/backups/delete"


@pytest.fixture
def histories(admin_client, env):
    vrf = admin_client.get("/api/v1/vrfs").json()["items"][0]["id"]
    with env() as db:
        ids = []
        for suffix in ("1", "2", "3"):
            row = device(db, vrf, suffix)
            base = snapshot(db, row, "hostname " + suffix, -2)
            latest = snapshot(db, row, "hostname updated-" + suffix, -1)
            row.base_snapshot_id = base.id
            row.approved_config_hash = latest.fingerprint
            row.config_approved_at = row.last_backup_at = now()
            db.add(m.Interface(device_id=row.id, name="port1"))
            ids.append((row.id, base.id, latest.id))
        db.commit()
    return ids


@pytest.mark.parametrize("count", [1, 2])
def test_clear_backup_histories_preserves_inventory(admin_client, env, histories, count):
    targets = [id for id, _, _ in histories[:count]]
    response = admin_client.post(PATH, json={"device_ids": targets})
    assert response.status_code == 200
    assert response.json() == {"deleted_count": 2 * count}
    with env() as db:
        for index, (id, base, latest) in enumerate(histories):
            row = db.get(m.Device, id)
            assert row is not None and not row.archived and row.name == f"Device {index + 1}"
            assert db.scalar(select(m.Interface.id).where(m.Interface.device_id == id))
            assert row.last_backup_at is not None
            if id in targets:
                assert row.base_snapshot_id is None
                assert row.approved_config_hash == "" and row.config_approved_at is None
                assert db.get(m.Snapshot, base) is None and db.get(m.Snapshot, latest) is None
                from netrix.configuration.baselines import base as select_base

                fresh = snapshot(db, row, "hostname new")
                assert select_base(db, row).id == fresh.id
            else:
                assert row.base_snapshot_id == base and db.get(m.Snapshot, latest) is not None
    items = admin_client.get("/api/v1/inventory/backup-devices").json()["items"]
    assert {row["id"] for row in items} == {id for id, _, _ in histories[count:]}


@pytest.mark.parametrize("reason", ["comparison", "firmware", "missing"])
def test_clear_is_atomic_when_any_target_is_blocked(admin_client, env, histories, reason):
    first, second = histories[:2]
    targets = [first[0], second[0]]
    with env() as db:
        if reason == "comparison":
            db.add(
                m.Job(
                    kind="compare",
                    target_id=second[0],
                    status="running",
                    result={"base_snapshot_id": second[2]},
                )
            )
        elif reason == "firmware":
            image = m.FirmwareImage(
                name="fixture",
                family="hp1950",
                version="1",
                models=[],
                original_name="fixture.bin",
                expected_sha256="0" * 64,
            )
            plan = m.FirmwarePlan(name="fixture", steps=[])
            db.add_all([image, plan])
            db.flush()
            db.add(
                m.FirmwareTarget(
                    plan_id=plan.id, device_id=second[0], image_id=image.id, stage=1, snapshot_id=second[2]
                )
            )
        else:
            targets.append("missing")
        db.commit()
    response = admin_client.post(PATH, json={"device_ids": targets})
    assert response.status_code == (404 if reason == "missing" else 409)
    with env() as db:
        for id, base, latest in histories:
            assert db.get(m.Device, id).base_snapshot_id == base
            assert db.get(m.Snapshot, base) and db.get(m.Snapshot, latest)


def test_operator_cannot_clear_backup_history(admin_client, env, histories):
    with env() as db:
        from netrix.identity.security import hasher

        db.add(
            m.User(
                email="operator@example.test",
                display_name="Operator",
                role="operator",
                password_hash=hasher.hash("fixture-only-password"),
            )
        )
        db.commit()
    assert (
        admin_client.post(
            "/api/v1/auth/login", json={"email": "operator@example.test", "password": "fixture-only-password"}
        ).status_code
        == 200
    )
    assert admin_client.post(PATH, json={"device_ids": [histories[0][0]]}).status_code == 403
