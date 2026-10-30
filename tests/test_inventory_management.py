import json
from datetime import timedelta

import pytest
from netrix import models as m
from netrix.core import now
from netrix.identity.security import encrypt
from netrix.worker import execute, sync_interfaces
from sqlalchemy import func, select


@pytest.fixture
def records(env, inventory):
    with env() as db:
        site = m.Site(name="Kuzey kampüs", code="N")
        db.add(site)
        db.flush()
        devices = [
            m.Device(
                name=f"Device {i}",
                management_ip=f"192.0.2.{i + 1}",
                vrf_id=inventory["vrf"]["id"],
                site_id=site.id,
                kind="firewall" if i == 0 else "switch",
                vendor="Acme",
                model="M7",
            )
            for i in range(2)
        ]
        db.add_all(devices)
        db.flush()
        ports = [
            m.Interface(device_id=d.id, name="port1", if_index=7, speed_bps=1000000000, oper_status="up")
            for d in devices
        ]
        db.add_all(ports)
        db.commit()
        return {"devices": [d.id for d in devices], "ports": [p.id for p in ports]}


@pytest.mark.parametrize("q", ["Kuzey", "Aktif", "Acme", "M7", "Global"])
def test_search_all_fields_and_relations(admin_client, records, q):
    d = admin_client.get("/api/v1/inventory/devices", params={"q": q, "limit": 1}).json()
    assert d["total"] == 2 and len(d["items"]) == 1
    assert "encrypted_secret" not in str(d)


def test_filters_left_associative_and_guarded(admin_client, records):
    filters = [
        {"field": "kind", "op": "eq", "value": "firewall"},
        {"field": "name", "op": "contains", "value": "Device 1", "join": "or"},
        {"field": "model", "op": "eq", "value": "missing", "join": "and"},
    ]
    assert (
        admin_client.get("/api/v1/inventory/devices", params={"filters": json.dumps(filters)}).json()["total"]
        == 0
    )
    filters.pop()
    assert (
        admin_client.get("/api/v1/inventory/devices", params={"filters": json.dumps(filters)}).json()["total"]
        == 2
    )
    for bad in (
        [{"field": "encrypted_content", "value": "x"}],
        [{"field": "name", "op": "gt", "value": "1"}],
        [{}] * 21,
    ):
        assert (
            admin_client.get("/api/v1/inventory/devices", params={"filters": json.dumps(bad)}).status_code
            == 422
        )
    assert admin_client.get("/api/v1/inventory/devices", params={"q": "%"}).json()["total"] == 0


def test_interface_selection_is_device_scoped_and_preserved(admin_client, records, env):
    c = admin_client
    device = records["devices"][0]
    port = records["ports"][0]
    assert c.get("/api/v1/inventory/interfaces").json()["total"] == 0
    assert (
        c.get("/api/v1/inventory/interfaces", params={"device_id": device, "candidates": True}).json()[
            "total"
        ]
        == 1
    )
    assert (
        c.put(f"/api/v1/devices/{device}/interfaces", json={"ids": [records["ports"][1]]}).status_code == 422
    )
    assert c.put(f"/api/v1/devices/{device}/interfaces", json={"ids": [port]}).status_code == 200
    row = c.get("/api/v1/inventory/interfaces", params={"q": "Firewall"}).json()["items"][0]
    assert row["device_kind"] == "firewall" and row["if_index"] == 7
    for q in ("7", "1 Gbps", "Açık"):
        assert c.get("/api/v1/inventory/interfaces", params={"q": q}).json()["total"] == 1
    assert (
        c.post("/api/v1/inventory/interfaces/bulk", json={"ids": [port], "action": "disable"}).status_code
        == 200
    )
    assert c.get("/api/v1/interfaces/" + port).json()["monitoring_enabled"] is False
    assert (
        c.post("/api/v1/inventory/interfaces/bulk", json={"ids": [port], "action": "delete"}).status_code
        == 200
    )
    assert c.get("/api/v1/inventory/interfaces").json()["total"] == 0
    with env() as db:
        assert db.get(m.Interface, port) is not None
    c.put(f"/api/v1/devices/{device}/interfaces", json={"ids": [port]})
    assert c.get("/api/v1/interfaces/" + port).json()["monitoring_enabled"] is False


def test_bulk_update_allowlist_and_atomic_rollback(admin_client, records, env):
    c = admin_client
    ids = records["devices"]
    for changes in ({"name": "bad"}, {"management_ip": "192.0.2.7"}, {"backup_retention": 1}):
        assert (
            c.post(
                "/api/v1/inventory/devices/bulk", json={"ids": ids, "action": "update", "changes": changes}
            ).status_code
            == 422
        )
    with env() as db:
        db.get(m.Device, ids[1]).archived = True
        db.commit()
    r = c.post(
        "/api/v1/inventory/devices/bulk",
        json={"ids": ids, "action": "update", "changes": {"vendor": "Changed"}},
    )
    assert r.status_code == 409
    assert c.get("/api/v1/devices/" + ids[0]).json()["vendor"] == "Acme"
    with env() as db:
        db.get(m.Device, ids[1]).archived = False
        db.commit()
    assert (
        c.post(
            "/api/v1/inventory/devices/bulk",
            json={
                "ids": ids,
                "action": "update",
                "changes": {"vendor": "Changed", "ssh_trust_host_key": True},
            },
        ).status_code
        == 200
    )
    assert c.get("/api/v1/devices/" + ids[1]).json()["vendor"] == "Changed"
    c.post("/api/v1/inventory/devices/bulk", json={"ids": ids, "action": "delete"})
    assert c.get("/api/v1/inventory/devices").json()["total"] == 0
    with env() as db:
        assert db.get(m.Device, ids[0]).lifecycle_status == "retired"


def test_only_selected_enabled_interfaces_receive_samples(env, records):
    with env() as db:
        device = db.get(m.Device, records["devices"][0])
        port = db.get(m.Interface, records["ports"][0])
        collected = {
            "interfaces": [
                {
                    "name": "port1",
                    "if_index": 7,
                    "oper_status": "up",
                    "description": "",
                    "mac_address": "",
                    "speed_bps": 1000,
                    "counters": {"in_octets": 100, "out_octets": 100, "uptime_ticks": 100},
                }
            ]
        }
        for selected, enabled in ((False, True), (True, False), (True, True)):
            port.is_managed = selected
            port.monitoring_enabled = enabled
            job = m.Job(kind="monitor", target_id=device.id)
            db.add(job)
            db.flush()
            sync_interfaces(db, device, collected, job.id)
            db.commit()
        assert db.scalar(select(func.count()).select_from(m.Sample)) == 1


def test_group_policy_retention_and_protected_comparison(admin_client, records, env):
    from netrix.configuration.management import policy, prune

    group = admin_client.post(
        "/api/v1/backup-groups", json={"name": "Firewall", "interval_seconds": 900, "retention_count": 1}
    ).json()
    ids = records["devices"]
    assert (
        admin_client.post(
            "/api/v1/backup-settings",
            json={"ids": ids, "action": "update", "changes": {"backup_group_id": group["id"]}},
        ).status_code
        == 200
    )
    with env() as db:
        device = db.get(m.Device, ids[0])
        assert policy(db, device) == (900, 1)
        rows = []
        for i in range(3):
            j = m.Job(kind="backup", target_id=device.id)
            db.add(j)
            db.flush()
            row = m.Snapshot(
                device_id=device.id,
                job_id=j.id,
                fingerprint=str(i),
                encrypted_content=encrypt("hostname x"),
                size_bytes=10,
                created_at=now() - timedelta(minutes=3 - i),
            )
            db.add(row)
            db.flush()
            rows.append(row)
        comparison = m.Job(
            kind="compare", target_id=device.id, status="queued", result={"base_snapshot_id": rows[0].id}
        )
        db.add(comparison)
        db.flush()
        prune(db, device)
        db.flush()
        assert len(db.scalars(select(m.Snapshot)).all()) == 2
        comparison.status = "succeeded"
        db.flush()
        prune(db, device)
        db.commit()
        assert len(db.scalars(select(m.Snapshot)).all()) == 1
    assert admin_client.delete("/api/v1/backup-groups/" + group["id"]).status_code == 409


async def test_live_comparison_is_worker_only_and_masked(admin_client, records, env, monkeypatch):
    c = admin_client
    device_id = records["devices"][0]
    profile = c.post(
        "/api/v1/credentials",
        json={
            "name": "SSH",
            "protocol": "ssh",
            "secret": {"username": "fixture", "password": "fixture-password"},
        },
    ).json()
    with env() as db:
        d = db.get(m.Device, device_id)
        d.config_credential_id = profile["id"]
        j = m.Job(kind="backup", target_id=device_id)
        db.add(j)
        db.flush()
        row = m.Snapshot(
            device_id=device_id,
            job_id=j.id,
            encrypted_content=encrypt("hostname old\npassword OLD-SECRET"),
            fingerprint="old",
            size_bytes=40,
        )
        db.add(row)
        db.commit()
        snapshot_id = row.id
    calls = []

    async def fetch(device, secret):
        calls.append(device.id)
        return "hostname new\npassword NEW-SECRET"

    monkeypatch.setattr("netrix.configuration.management.fetch_config", fetch)
    job = c.post(f"/api/v1/snapshots/{snapshot_id}/compare-live").json()
    assert calls == []
    assert c.delete(f"/api/v1/snapshots/{snapshot_id}").status_code == 409
    await execute(job["id"])
    result = c.get("/api/v1/backup-comparisons/" + job["id"]).json()
    assert result["status"] == "succeeded" and result["result"]["changed"]
    assert (
        "hostname new" in result["result"]["diff"]
        and "NEW-SECRET" not in result["result"]["diff"]
        and "OLD-SECRET" not in result["result"]["diff"]
    )
    assert "diff" not in c.get("/api/v1/jobs/" + job["id"]).json()["result"]
    assert calls == [device_id]
    assert c.get("/api/v1/snapshots").json()["total"] == 1


def test_viewer_cannot_mutate_selection_bulk_or_backups(admin_client, records):
    c = admin_client
    c.post(
        "/api/v1/users",
        json={
            "email": "viewer@test.test",
            "display_name": "Viewer",
            "password": "long-test-password",
            "role": "viewer",
        },
    )
    c.post("/api/v1/auth/logout")
    c.post("/api/v1/auth/login", json={"email": "viewer@test.test", "password": "long-test-password"})
    assert c.get("/api/v1/inventory/devices").status_code == 200
    assert c.put(f"/api/v1/devices/{records['devices'][0]}/interfaces", json={"ids": []}).status_code == 403
    for path in ("inventory/devices/bulk", "inventory/interfaces/bulk", "backup-settings"):
        assert (
            c.post("/api/v1/" + path, json={"ids": records["devices"], "action": "delete"}).status_code == 403
        )
    assert c.post("/api/v1/snapshots/absent/compare-live").status_code == 403


def test_localized_filters_and_archived_backup_history(admin_client, records, env):
    c = admin_client
    device_id = records["devices"][0]
    for field, value, count in (
        ("kind", "Firewall", 1),
        ("lifecycle_status", "Aktif", 2),
        ("ssh_trust_host_key", "Kapalı", 2),
    ):
        filters = [{"field": field, "op": "eq", "value": value}]
        response = c.get("/api/v1/inventory/devices", params={"filters": json.dumps(filters)})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == count
    with env() as db:
        for changed in (True, False):
            job = m.Job(kind="backup", target_id=device_id)
            db.add(job)
            db.flush()
            db.add(
                m.Snapshot(
                    device_id=device_id,
                    job_id=job.id,
                    fingerprint=str(changed),
                    encrypted_content=encrypt("hostname retained"),
                    size_bytes=17,
                    changed=changed,
                )
            )
        db.commit()
    for field, value in (("lifecycle_status", "Aktif"), ("ssh_trust_host_key", "Kapalı")):
        result = c.get(
            "/api/v1/inventory/devices",
            params={"filters": json.dumps([{"field": field, "op": "contains", "value": value}])},
        )
        assert result.status_code == 200 and result.json()["total"] == 2
    response = c.post("/api/v1/inventory/devices/bulk", json={"ids": [device_id], "action": "delete"})
    assert response.status_code == 200
    assert c.get("/api/v1/inventory/snapshots").json()["total"] == 2
    filters = [
        {"field": "device_name", "op": "eq", "value": "missing"},
        {"field": "device_kind", "op": "eq", "value": "Firewall", "join": "or"},
    ]
    result = c.get(
        "/api/v1/inventory/snapshots", params={"changed_only": True, "filters": json.dumps(filters)}
    ).json()
    assert result["total"] == 1 and result["items"][0]["changed"]


def test_group_schedule_overrides_device_interval_without_duplicates(admin_client, records, env):
    from netrix.scheduler import tick

    c = admin_client
    profile = c.post(
        "/api/v1/credentials",
        json={
            "name": "Schedule SSH",
            "protocol": "ssh",
            "secret": {"username": "fixture", "password": "fixture-password"},
        },
    ).json()
    group = c.post(
        "/api/v1/backup-groups", json={"name": "Switch", "interval_seconds": 900, "retention_count": 3}
    ).json()
    device_id = records["devices"][0]
    with env() as db:
        device = db.get(m.Device, device_id)
        device.config_credential_id = profile["id"]
        device.backup_group_id = group["id"]
        device.backup_interval = 0
        device.monitoring_enabled = False
        db.commit()
    tick()
    tick()
    with env() as db:
        jobs = db.scalars(select(m.Job).where(m.Job.kind == "backup", m.Job.target_id == device_id)).all()
        assert len(jobs) == 1 and jobs[0].status == "queued"
        jobs[0].status, jobs[0].active_key = "failed", None
        db.commit()
    tick()
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == "backup")) == 1
    row = c.get("/api/v1/inventory/devices", params={"q": "Device 0"}).json()["items"][0]
    assert row["effective_backup_interval"] == 900 and row["effective_retention"] == 3


def test_backup_device_directory_counts_and_scopes_history(admin_client, records, env):
    c = admin_client
    assert c.get("/api/v1/inventory/backup-devices").json()["total"] == 0
    ids = records["devices"]
    latest = now()
    with env() as db:
        # Names are not identities. Archived devices must retain access to their backups.
        for index, device_id in enumerate(ids):
            device = db.get(m.Device, device_id)
            device.name = "Same name"
            device.archived = index == 1
            for i in range(27 if index == 0 else 1):
                job = m.Job(kind="backup", target_id=device_id)
                db.add(job)
                db.flush()
                db.add(
                    m.Snapshot(
                        device_id=device_id,
                        job_id=job.id,
                        fingerprint=str(i),
                        encrypted_content=encrypt("hostname test"),
                        size_bytes=13,
                        created_at=latest - timedelta(minutes=i),
                    )
                )
        db.add(m.Device(name="No backup", management_ip="192.0.2.99", vrf_id=device.vrf_id))
        db.commit()
    directory = c.get("/api/v1/inventory/backup-devices").json()
    assert directory["total"] == 2
    rows = {r["id"]: r for r in directory["items"]}
    assert rows[ids[0]]["snapshot_count"] == 27
    assert rows[ids[1]]["snapshot_count"] == 1
    assert rows[ids[0]]["latest_snapshot_at"] == latest.isoformat()
    assert "encrypted_content" not in str(directory)
    first = c.get("/api/v1/inventory/backup-devices?limit=1").json()
    second = c.get("/api/v1/inventory/backup-devices?limit=1&offset=1").json()
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]
    assert c.get("/api/v1/inventory/backup-devices", params={"q": "192.0.2.1"}).json()["total"] == 1
    filters = json.dumps([{"field": "snapshot_count", "op": "gt", "value": "1"}])
    assert c.get("/api/v1/inventory/backup-devices", params={"filters": filters}).json()["total"] == 1
    for device_id, total in zip(ids, (27, 1)):
        for offset in (0, 25):
            history = c.get(
                "/api/v1/inventory/snapshots", params={"device_id": device_id, "offset": offset}
            ).json()
            assert history["total"] == total
            assert all(row["device_id"] == device_id for row in history["items"])


def test_archive_restore_preserves_identity_history_and_stops_schedules(
    admin_client, records, env, inventory
):
    c = admin_client
    device_id = records["devices"][0]
    with env() as db:
        device = db.get(m.Device, device_id)
        group = m.BackupGroup(name="Scheduled", interval_seconds=300)
        db.add(group)
        db.flush()
        device.backup_group_id = group.id
        device.snmp_credential_id = inventory["credential"]["id"]
        device.monitoring_enabled = True
        device.backup_interval = 300
        job = m.Job(kind="backup", target_id=device_id, status="succeeded")
        db.add(job)
        db.flush()
        snapshot = m.Snapshot(
            device_id=device_id,
            job_id=job.id,
            encrypted_content=encrypt("fixture"),
            fingerprint="fixture",
            size_bytes=7,
        )
        db.add(snapshot)
        db.commit()
        group_id, snapshot_id = group.id, snapshot.id
    assert c.delete("/api/v1/devices/" + device_id).status_code == 204
    assert c.get("/api/v1/inventory/devices", params={"q": "Device 0"}).json()["total"] == 0
    archived = c.get("/api/v1/inventory/devices", params={"archived": True, "q": "192.0.2.1"}).json()
    assert archived["total"] == 1 and archived["items"][0]["id"] == device_id
    assert archived["items"][0]["snmp_profile"] == "Test SNMP"
    assert "encrypted_content" not in str(archived) and "encrypted_secret" not in str(archived)
    assert c.get("/api/v1/inventory/interfaces", params={"archived": True}).status_code == 422
    restore = {"action": "restore", "ids": [device_id]}
    assert c.post("/api/v1/inventory/devices/bulk", json=restore).json() == {"updated": 1}
    assert c.get("/api/v1/inventory/devices", params={"archived": True}).json()["total"] == 0
    assert c.get("/api/v1/inventory/devices", params={"q": "192.0.2.1"}).json()["items"][0]["id"] == device_id
    with env() as db:
        device = db.get(m.Device, device_id)
        assert not device.archived and device.lifecycle_status == "maintenance"
        assert not device.monitoring_enabled and device.backup_interval == 0
        assert device.backup_group_id == group_id
        assert device.snmp_credential_id == inventory["credential"]["id"]
        assert db.get(m.Snapshot, snapshot_id).device_id == device_id
        assert db.get(m.Interface, records["ports"][0]).device_id == device_id
        assert db.scalar(select(func.count()).select_from(m.Job)) == 1
        assert db.scalar(
            select(m.Audit).where(m.Audit.action == "bulk_restore", m.Audit.entity_id == device_id)
        )
    assert c.post("/api/v1/inventory/devices/bulk", json=restore).status_code == 409


def test_restore_is_atomic_rejects_changes_and_non_devices(admin_client, records, env):
    c = admin_client
    first, second = records["devices"]
    c.delete("/api/v1/devices/" + first)
    for payload, status in (
        ({"ids": [first, second], "action": "restore"}, 409),
        ({"ids": [first, "absent"], "action": "restore"}, 404),
        ({"ids": [first], "action": "restore", "changes": {"vendor": "altered"}}, 422),
    ):
        assert c.post("/api/v1/inventory/devices/bulk", json=payload).status_code == status
        with env() as db:
            assert db.get(m.Device, first).archived
            assert not db.scalar(select(m.Audit).where(m.Audit.action == "bulk_restore"))
    assert (
        c.post(
            "/api/v1/inventory/interfaces/bulk", json={"ids": records["ports"], "action": "restore"}
        ).status_code
        == 422
    )
    assert (
        c.post("/api/v1/inventory/devices/bulk", json={"ids": [first], "action": "restore"}).status_code
        == 200
    )


@pytest.mark.parametrize("role", ["operator", "viewer"])
def test_archive_can_be_read_but_only_admin_can_restore(admin_client, records, env, role):
    device_id = records["devices"][0]
    admin_client.delete("/api/v1/devices/" + device_id)
    with env() as db:
        db.scalar(select(m.User).where(m.User.email == "owner@example.test")).role = role
        db.commit()
    assert admin_client.get("/api/v1/inventory/devices", params={"archived": True}).json()["total"] == 1
    assert (
        admin_client.post(
            "/api/v1/inventory/devices/bulk", json={"action": "restore", "ids": [device_id]}
        ).status_code
        == 403
    )
    with env() as db:
        assert db.get(m.Device, device_id).archived
