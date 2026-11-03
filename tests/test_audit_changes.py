import json

import pytest
from fastapi.testclient import TestClient
from netrix import models as m
from netrix.identity.security import audit
from netrix.main import app
from sqlalchemy import select


def entries(client, **params):
    response = client.get("/api/v1/audit", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_all_users_and_background_separation(admin_client, env):
    user = admin_client.post(
        "/api/v1/users",
        json={
            "email": "operator@example.test",
            "display_name": "İkinci kullanıcı",
            "password": "fixture-long-password",
            "role": "operator",
        },
    )
    assert user.status_code == 201, user.text
    with TestClient(app, headers={"X-Netrix-Request": "1"}) as other:
        assert (
            other.post(
                "/api/v1/auth/login",
                json={
                    "email": "operator@example.test",
                    "password": "fixture-long-password",
                },
            ).status_code
            == 200
        )
        created = other.post("/api/v1/institutions", json={"name": "Operator kurumu", "code": "OP"})
        assert created.status_code == 201, created.text
        assert other.get("/api/v1/audit").status_code == 403
    owner = admin_client.post("/api/v1/institutions", json={"name": "Yönetici kurumu", "code": "ADM"}).json()
    with env() as db:
        audit(db, None, "enqueue", "jobs", None, "ipam_ping görevi kuyruğa alındı")
        db.commit()
    result = entries(admin_client)
    assert all(row["actor_id"] for row in result["items"])
    assert not any(row["summary"].startswith("ipam_ping") for row in result["items"])
    by_id = {row["entity_id"]: row for row in result["items"] if row["entity_type"] == "institutions"}
    assert by_id[created.json()["id"]]["actor_name"] == "İkinci kullanıcı"
    assert by_id[owner["id"]]["actor_name"] == "Owner"
    assert entries(admin_client, q="İkinci kullanıcı")["total"] >= 2
    assert entries(admin_client, q="operator@example.test")["total"] >= 2
    assert entries(admin_client, q="Oluşturdu")["total"] >= 3
    page = entries(admin_client, limit=1, offset=1)
    assert len(page["items"]) == 1 and page["total"] == result["total"]


def test_safe_field_diff_delete_and_historical_identity(admin_client, env):
    item = admin_client.post("/api/v1/institutions", json={"name": "Önceki ad", "code": "A"}).json()
    updated = admin_client.put("/api/v1/institutions/" + item["id"], json={"name": "Yeni ad", "code": "A"})
    assert updated.status_code == 200, updated.text
    rows = [r for r in entries(admin_client)["items"] if r["entity_id"] == item["id"]]
    assert len(rows) == 2  # No duplicate automatic + domain audit records.
    change = next(r for r in rows if r["action"] == "update")
    assert change["details"]["changes"] == {"name": {"previous": "Önceki ad", "current": "Yeni ad"}}
    assert change["target_label"] == "Yeni ad"
    assert change["resource_label"] == "Kurum" and change["action_label"] == "Güncelledi"
    assert admin_client.delete("/api/v1/institutions/" + item["id"]).status_code == 204
    removed = next(
        r for r in entries(admin_client)["items"] if r["entity_id"] == item["id"] and r["action"] == "delete"
    )
    assert removed["target_label"] == "Yeni ad"
    with env() as db:
        user = db.scalar(select(m.User).where(m.User.display_name == "Owner"))
        user.display_name = "Renamed user"
        db.commit()
    detail = admin_client.get("/api/v1/audit/" + change["id"]).json()
    assert detail["actor_name"] == "Owner" and detail["target_label"] == "Yeni ad"


def test_credentials_and_password_values_never_enter_journal(admin_client):
    response = admin_client.post(
        "/api/v1/credentials",
        json={
            "name": "Safe SSH",
            "protocol": "ssh",
            "secret": {"username": "hidden-login", "password": "NEVER-COPY-THIS-SECRET"},
        },
    )
    assert response.status_code == 201, response.text
    row = next(r for r in entries(admin_client)["items"] if r["entity_id"] == response.json()["id"])
    assert row["details"]["changes"]["protected_values"]["current"] == "Güncellendi"
    output = json.dumps(entries(admin_client))
    for secret in ("NEVER-COPY-THIS-SECRET", "hidden-login", "fixture-long-password", "$argon2", "gAAAAA"):
        assert secret not in output
    assert "encrypted_secret" not in output and "password_hash" not in output


def test_failed_write_and_rollback_leave_no_changes(admin_client, env):
    admin_client.post("/api/v1/institutions", json={"name": "First", "code": "UNIQUE"})
    before = entries(admin_client)["total"]
    assert (
        admin_client.post("/api/v1/institutions", json={"name": "Invalid", "code": "UNIQUE"}).status_code
        == 409
    )
    assert entries(admin_client)["total"] == before
    with env() as db:
        db.info["audit_actor"] = db.scalar(select(m.User))
        row = m.Institution(name="Rolled back", code="ROLLBACK")
        db.add(row)
        db.flush()
        assert db.scalar(select(m.Audit).where(m.Audit.entity_id == row.id))
        db.rollback()
        assert not db.info.get("audit_entries")
        assert db.scalar(select(m.Audit).where(m.Audit.entity_id == row.id)) is None


def test_custom_mutation_gets_actor_and_old_role(admin_client):
    user = admin_client.post(
        "/api/v1/users",
        json={
            "email": "viewer@example.test",
            "display_name": "Viewer",
            "password": "fixture-long-password",
            "role": "viewer",
        },
    ).json()
    response = admin_client.put(
        "/api/v1/users/" + user["id"] + "/roles", json={"role": "operator", "ssh_access": True}
    )
    assert response.status_code == 200, response.text
    row = next(r for r in entries(admin_client)["items"] if r["action"] == "user_roles_updated")
    assert row["details"]["changes"]["role"] == {"previous": "viewer", "current": "operator"}
    assert row["details"]["changes"]["ssh_access"] == {"previous": False, "current": True}


def test_legacy_actor_resolution_and_empty_search(admin_client, env):
    with env() as db:
        user = db.scalar(select(m.User))
        db.add(
            m.Audit(
                actor_id=user.id,
                action="update",
                entity_type="devices",
                entity_id="deleted-id",
                summary="Geçmiş işlem",
                details=None,
            )
        )
        db.commit()
    row = entries(admin_client, q="Geçmiş")["items"][0]
    assert row["actor_name"] == "Owner" and row["target_label"] == "deleted-id"
    assert row["details"] is None
    assert entries(admin_client, q="no-matching-fixture")["total"] == 0
    assert entries(admin_client, q="%")["total"] == 0


def test_unicode_snapshot_search_and_preference_changes(admin_client, env):
    with env() as db:
        user = db.scalar(select(m.User))
        db.add(
            m.Audit(
                actor_id=user.id,
                action="update",
                entity_type="institutions",
                summary="Ad güncellendi",
                details={"actor": {"name": "Çağrı", "email": "old@example.test"}, "target": "Şube-İstanbul"},
            )
        )
        db.commit()
    assert entries(admin_client, q="Çağrı")["total"] == 1
    assert entries(admin_client, q="Şube-İstanbul")["total"] == 1
    before = admin_client.get("/api/v1/access/preferences").json()
    assert admin_client.put("/api/v1/access/preferences", json=before).status_code == 200
    response = admin_client.put("/api/v1/access/preferences", json={**before, "palette": "violet"})
    assert response.status_code == 200, response.text
    row = next(r for r in entries(admin_client)["items"] if r["entity_type"] == "user_workspaces")
    assert row["details"]["changes"]["preferences.palette"] == {"previous": "cobalt", "current": "violet"}


def test_scan_schedule_records_one_descriptive_change(admin_client, inventory, env):
    from conftest import make_vlan

    with env() as db:
        vlan = make_vlan(cidr="192.0.2.0/30", vrf_id=inventory["vrf"]["id"])
        db.add(vlan)
        db.commit()
        vlan_id = vlan.id
    payload = {
        "name": "Audit scan group",
        "vlan_ids": [vlan_id],
        "frequency": "daily",
        "repeat_every": 1,
        "start_at": "2026-12-01T06:00:00+00:00",
    }
    response = admin_client.post("/api/v1/ipam/scan-groups", json=payload)
    assert response.status_code == 201, response.text
    group_id = response.json()["id"]
    assert len([row for row in entries(admin_client)["items"] if row["entity_id"] == group_id]) == 1
    response = admin_client.put("/api/v1/ipam/scan-groups/" + group_id, json={**payload, "repeat_every": 2})
    assert response.status_code == 200, response.text
    rows = [row for row in entries(admin_client)["items"] if row["entity_id"] == group_id]
    assert len(rows) == 2
    row = next(row for row in rows if row["action"] == "update")
    assert row["resource_label"] == "Tarama grubu"
    assert row["details"]["changes"]["repeat_every"] == {"previous": 1, "current": 2}


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_audit_detail_is_admin_only(admin_client, env, role):
    event = entries(admin_client)["items"][0]
    with env() as db:
        db.scalar(select(m.User)).role = role
        db.commit()
    assert admin_client.get("/api/v1/audit").status_code == 403
    assert admin_client.get("/api/v1/audit/" + event["id"]).status_code == 403
