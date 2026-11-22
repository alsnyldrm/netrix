"""Real API enrollment and replay/recovery controls, with no external protocols."""

import base64

from netrix import models as m
from netrix.core import now
from netrix.identity.mfa import totp
from netrix.identity.security import decrypt
from sqlalchemy import select

EMAIL = "alisan.yildirim@fbu.edu.tr"
PASSWORD = "test-only-password-long"


def login(client):
    return client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})


def test_rfc6238_sha1_vectors():
    secret = base64.b32encode(b"12345678901234567890").decode()
    for timestamp, expected in [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ]:
        assert totp(secret, timestamp // 30, digits=8) == expected


def test_enrollment_required_encrypted_and_one_use(client, env):
    client.post(
        "/api/v1/auth/setup",
        json={
            "email": EMAIL,
            "display_name": "Owner",
            "password": PASSWORD,
            "setup_token": "test-only-setup-token-32-characters",
        },
    )
    result = login(client)
    assert result.status_code == 200
    assert "netrix_session" not in result.cookies
    assert client.get("/api/v1/auth/me").status_code == 401
    data = result.json()
    assert data["mfa_setup_required"] and data["qr_code"].startswith("data:image/png;base64,")
    with env() as db:
        user = db.scalar(select(m.User))
        assert user.encrypted_mfa_secret is None
        assert data["secret"] not in user.encrypted_mfa_pending
        assert decrypt(user.encrypted_mfa_pending) == data["secret"]
    body = {"challenge": data["challenge"], "code": totp(data["secret"], int(now().timestamp()) // 30)}
    response = client.post("/api/v1/auth/mfa/verify", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["mfa_enabled"]
    assert not any(k.startswith(("encrypted_", "mfa_challenge", "mfa_last")) for k in response.json())
    assert client.post("/api/v1/auth/mfa/verify", json=body).status_code == 401
    client.post("/api/v1/auth/logout")
    second = login(client).json()
    assert not second["mfa_setup_required"]
    assert "secret" not in second and "qr_code" not in second
    assert (
        client.post("/api/v1/auth/mfa/verify", json={**body, "challenge": second["challenge"]}).status_code
        == 401
    )


def test_attempt_expiry_reset_and_permissions(admin_client, env):
    user = admin_client.get("/api/v1/auth/me").json()
    result = admin_client.post(f"/api/v1/users/{user['id']}/mfa/reset")
    assert result.status_code == 204
    assert admin_client.get("/api/v1/auth/me").status_code == 401
    first = login(admin_client).json()
    second = login(admin_client).json()

    def verify(data, code="000000"):
        return admin_client.post(
            "/api/v1/auth/mfa/verify", json={"challenge": data["challenge"], "code": code}
        )

    assert verify(first).status_code == 401
    for _ in range(5):
        assert verify(second, "999999").status_code == 401
    with env() as db:
        user = db.get(m.User, user["id"])
        assert user.mfa_challenge_hash is None
    third = login(admin_client).json()
    with env() as db:
        user = db.scalar(select(m.User))
        from datetime import timedelta

        user.mfa_expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert verify(third, totp(third["secret"], int(now().timestamp()) // 30)).status_code == 401


def test_viewer_cannot_reset(admin_client, env):
    with env() as db:
        from netrix.identity.security import issue_session

        viewer = m.User(
            email="viewer@example.test", display_name="Viewer", password_hash="unused", role="viewer"
        )
        db.add(viewer)
        db.flush()
        token = issue_session(db, viewer)
        db.commit()
        id = viewer.id
    admin_client.cookies.set("netrix_session", token)
    assert admin_client.post(f"/api/v1/users/{id}/mfa/reset").status_code == 403
