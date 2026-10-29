from netrix.core import settings


def test_no_auth_and_csrf_guard(client):
    assert client.get("/api/v1/devices").status_code == 401
    assert client.post("/api/v1/auth/login", json={}, headers={"X-Netrix-Request": ""}).status_code == 403
    assert (
        client.post("/api/v1/auth/login", json={}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )


def test_setup_single_use_password_hash_and_session_revocation(admin_client, env):
    c = admin_client
    from netrix.models import User
    from sqlalchemy import select

    with env() as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
    assert (
        c.post(
            "/api/v1/auth/setup",
            json={
                "email": "another@example.test",
                "display_name": "Another",
                "password": "another-test-password",
                "setup_token": settings().setup_token,
            },
        ).status_code
        == 409
    )
    assert (
        "httponly"
        in c.cookies.jar._cookies["testserver.local"]["/"]["netrix_session"]._rest.keys().__str__().lower()
    )
    r = c.post(
        "/api/v1/auth/password",
        json={"current_password": "test-only-password-long", "new_password": "changed-test-password"},
    )
    assert r.status_code == 204
    assert c.get("/api/v1/auth/me").status_code == 401
    assert (
        c.post(
            "/api/v1/auth/login", json={"email": "OWNER@example.test", "password": "changed-test-password"}
        ).status_code
        == 200
    )


def test_roles_are_enforced_on_server(admin_client):
    c = admin_client
    for role in ("viewer", "operator"):
        r = c.post(
            "/api/v1/users",
            json={
                "email": role + "@example.test",
                "display_name": role,
                "password": "role-test-password-long",
                "role": role,
            },
        )
        assert r.status_code == 201
    c.post("/api/v1/auth/logout")
    for role in ("viewer", "operator"):
        assert (
            c.post(
                "/api/v1/auth/login",
                json={"email": role + "@example.test", "password": "role-test-password-long"},
            ).status_code
            == 200
        )
        assert c.get("/api/v1/devices").status_code == 200
        assert c.get("/api/v1/users").status_code == 403
        assert c.post("/api/v1/credentials", json={}).status_code == 403
        result = c.post("/api/v1/sites", json={"name": role, "code": role})
        assert result.status_code == (403 if role == "viewer" else 201)
        assert c.post("/api/v1/users", json={}).status_code == 403
        c.post("/api/v1/auth/logout")


def test_validation_does_not_echo_secret(client):
    marker = "DO-NOT-LEAK-SECRET"
    r = client.post(
        "/api/v1/auth/setup",
        json={"email": "bad", "display_name": "X", "password": marker, "setup_token": marker},
    )
    assert r.status_code == 422
    assert marker not in r.text


def test_login_rate_limit_and_generic_failure(client):
    for _ in range(15):
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "nobody@example.test", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.test", "password": "wrong"}
        ).status_code
        == 429
    )


def test_openapi_and_live_independent_of_dependencies(client, monkeypatch):
    import netrix.main as main

    assert client.get("/api/v1/openapi.json").json()["info"]["title"] == "NETRIX API"
    monkeypatch.setattr(main, "redis_client", lambda: (_ for _ in ()).throw(ConnectionError()))
    assert client.get("/api/v1/health/live").status_code == 200
    assert client.get("/api/v1/health/ready").status_code == 503


def test_referenced_credential_protocol_is_immutable(admin_client, inventory):
    response = admin_client.put(
        "/api/v1/credentials/" + inventory["credential"]["id"],
        json={
            "name": "Test SNMP",
            "protocol": "ssh",
            "secret": {"username": "fixture", "password": "fixture-password"},
        },
    )
    assert response.status_code == 409
    assert (
        admin_client.get("/api/v1/credentials/" + inventory["credential"]["id"]).json()["protocol"]
        == "snmpv3"
    )
