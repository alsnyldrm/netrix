"""Exclusive owner role, independent SSH grants and escalation protection."""

from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.identity.permissions import SUPER_ADMIN_EMAIL, can_operate, can_ssh, is_admin, is_super_admin
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


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


def test_owner_exclusive_and_protected(admin_client, env):
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
    assert (
        admin_client.put(f"/api/v1/users/{target['id']}/roles", json={"role": "super_admin"}).status_code
        == 422
    )
    with env() as db:
        row = db.get(m.User, target["id"])
        row.role = "super_admin"
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert len(list(db.scalars(select(m.User).where(m.User.role == "super_admin")))) == 1
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


def test_super_admin_role_with_wrong_identity_never_has_privileged_access():
    user = SimpleNamespace(role="super_admin", email="another@example.test", ssh_access=False)
    assert not is_super_admin(user) and not is_admin(user) and not can_operate(user) and not can_ssh(user)


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
