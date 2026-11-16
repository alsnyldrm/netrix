"""Delegated super admins, recovery owner protection and independent SSH grants."""

from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.identity.permissions import SUPER_ADMIN_EMAIL, can_operate, can_ssh, is_admin, is_super_admin
from sqlalchemy import select


@pytest.mark.parametrize(
    "role,ssh,admin,write,terminal",
    [
        ("super_admin", False, True, True, True),
        ("admin", False, True, True, False),
        ("admin", True, True, True, True),
        ("operator", False, False, True, False),
        ("viewer", False, False, False, False),
        ("viewer", True, False, False, True),
    ],
)
def test_capabilities(role, ssh, admin, write, terminal):
    user = SimpleNamespace(role=role, ssh_access=ssh, email=SUPER_ADMIN_EMAIL)
    assert is_admin(user) == admin
    assert can_operate(user) == write
    assert can_ssh(user) == terminal


def test_recovery_owner_protected_and_regular_admin_cannot_grant_roles(admin_client):
    owner = admin_client.get("/api/v1/auth/me").json()
    assert owner["email"] == SUPER_ADMIN_EMAIL and owner["role"] == "super_admin"
    assert admin_client.get("/api/v1/audit").status_code == 200
    assert admin_client.get("/api/v1/access/ssh-profiles").status_code == 200
    assert admin_client.put(f"/api/v1/users/{owner['id']}/roles", json={"role": "admin"}).status_code == 409
    assert admin_client.post(f"/api/v1/users/{owner['id']}/toggle").status_code == 409
    payload = {
        "email": "another@example.test",
        "display_name": "Another",
        "password": "test-password-long",
        "role": "super_admin",
    }
    assert admin_client.post("/api/v1/users", json=payload).status_code == 422
    payload["role"] = "admin"
    target = admin_client.post("/api/v1/users", json=payload).json()
    assert not target["ssh_access"]
    admin_client.post("/api/v1/auth/logout")
    assert (
        admin_client.post(
            "/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]}
        ).status_code
        == 200
    )
    assert (
        admin_client.put(
            f"/api/v1/users/{target['id']}/roles", json={"role": "admin", "ssh_access": True}
        ).status_code
        == 403
    )
    assert (
        admin_client.put(f"/api/v1/users/{target['id']}/roles", json={"role": "super_admin"}).status_code
        == 403
    )
    assert admin_client.put(f"/api/v1/users/{owner['id']}/roles", json={"role": "viewer"}).status_code == 403
    assert admin_client.post(f"/api/v1/users/{owner['id']}/toggle").status_code == 403
    for role, ssh in (("admin", False), ("operator", False), ("viewer", True), ("super_admin", False)):
        assert (
            admin_client.post(
                "/api/v1/users",
                json={**payload, "email": "escalation@example.test", "role": role, "ssh_access": ssh},
            ).status_code
            == 403
        )
    assert (
        admin_client.post(
            "/api/v1/users", json={**payload, "email": "normal@example.test", "role": "viewer"}
        ).status_code
        == 201
    )
    for path in (
        "ssh-profiles",
        "groups",
        "commands",
        "devices",
        "device-selection",
        "sessions/missing",
        "batches/missing",
        "batch-drafts/missing",
    ):
        assert admin_client.get("/api/v1/access/" + path).status_code == 403, path
    assert admin_client.post("/api/v1/access/sessions", json={"device_id": "missing"}).status_code == 403
    assert (
        admin_client.post(
            "/api/v1/access/batches", json={"device_ids": ["missing"], "command": "show version"}
        ).status_code
        == 403
    )
    assert admin_client.put("/api/v1/access/preferences/terminal", json={}).status_code == 403
    assert admin_client.get("/api/v1/access/preferences").status_code == 200
    assert admin_client.get("/api/v1/users").status_code == 200


def test_super_admin_is_an_explicit_role_instead_of_a_reserved_email():
    user = SimpleNamespace(
        role="super_admin", email="another@example.test", ssh_access=False, auth_source="saml"
    )
    assert is_super_admin(user) and is_admin(user) and can_operate(user) and can_ssh(user)


def test_delegated_super_admin_can_grant_and_revoke_but_cannot_demote_recovery_owner(admin_client, env):
    from fastapi.testclient import TestClient
    from netrix.main import app

    owner = admin_client.get("/api/v1/auth/me").json()
    data = {"email": "delegate@example.test", "display_name": "Delegate", "password": "fixture-long-password"}
    delegate = admin_client.post("/api/v1/users", json=data).json()
    another = admin_client.post("/api/v1/users", json={**data, "email": "next@example.test"}).json()
    promote = {"role": "super_admin", "ssh_access": False}

    def roles(id):
        return f"/api/v1/users/{id}/roles"

    assert admin_client.put(roles(delegate["id"]), json=promote).status_code == 200

    with TestClient(app, headers={"X-Netrix-Request": "1"}) as delegated:
        response = delegated.post(
            "/api/v1/auth/login", json={"email": data["email"], "password": data["password"]}
        )
        assert response.json()["role"] == "super_admin"
        assert delegated.get("/api/v1/access/ssh-profiles").status_code == 200
        assert delegated.put(roles(another["id"]), json=promote).status_code == 200
        assert delegated.put(roles(owner["id"]), json={"role": "admin"}).status_code == 409
        assert delegated.post(f"/api/v1/users/{owner['id']}/toggle").status_code == 403
        assert delegated.post(f"/api/v1/users/{another['id']}/toggle").status_code == 403
        assert delegated.put(roles(another["id"]), json={"role": "admin"}).json()["role"] == "admin"
        assert admin_client.put(roles(delegate["id"]), json={"role": "admin"}).status_code == 200
        assert delegated.put(roles(another["id"]), json=promote).status_code == 403
        assert delegated.get("/api/v1/access/ssh-profiles").status_code == 403

    with env() as db:
        rows = db.scalars(
            select(m.Audit).where(
                m.Audit.actor_id == delegate["id"],
                m.Audit.entity_id == another["id"],
                m.Audit.action == "user_roles_updated",
            )
        ).all()
        assert len(rows) == 2
        assert db.get(m.User, owner["id"]).role == "super_admin"


def test_setup_cannot_leave_installation_without_designated_owner(client):
    from netrix.core import settings

    payload = {
        "email": "another@example.test",
        "display_name": "Owner",
        "password": "test-password-long",
        "setup_token": settings().setup_token,
        "role": "super_admin",
    }
    assert client.post("/api/v1/auth/setup", json=payload).status_code == 422
    response = client.post("/api/v1/auth/setup", json={**payload, "email": SUPER_ADMIN_EMAIL})
    assert response.status_code == 201 and response.json()["role"] == "super_admin"
