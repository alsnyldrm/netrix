import json
import ssl
from unittest.mock import Mock

import pytest
from netrix import models as m
from netrix import worker
from netrix.core import now
from netrix.discovery import interactive_tests
from netrix.identity.security import decrypt
from netrix.ipam import connection_tests as tests
from sqlalchemy import func, select


def payload(**changes):
    return dict(
        name="DHCP fixture",
        kind="windows_dhcp",
        host="dhcp.example.test",
        port=5986,
        username="EXAMPLE\\fixture",
        password="NEVER-EXPOSE-THIS",
        verify_tls=True,
        **changes,
    )


@pytest.mark.parametrize("saved", [False, True])
async def test_saved_and_unsaved_settings_are_tested_without_writes(admin_client, env, monkeypatch, saved):
    c = admin_client
    original = payload()
    stored = c.post("/api/v1/integrations", json=original).json() if saved else None
    with env() as db:
        before = db.scalar(select(func.count()).select_from(m.IPObservation))
        cipher = db.get(m.Integration, stored["id"]).encrypted_secret if saved else None
    values = {**original, "username": "", "password": ""} if saved else original
    response = c.post(
        "/api/v1/integrations" + ("/" + stored["id"] if saved else "") + "/connection-tests", json=values
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["result"]["interactive"] is True and job["kind"] == tests.KIND
    assert "NEVER-EXPOSE" not in response.text and "username" not in response.text
    cached = interactive_tests.redis_client().get(tests.key(job["id"]))
    assert "NEVER-EXPOSE" not in cached
    assert json.loads(decrypt(cached))["secret"]["password"] == original["password"]
    called = []

    def probe(config, secret):
        called.append(config.host)
        assert config.verify_tls is True and secret["username"] == original["username"]
        return "Fixture connection and read access successful"

    monkeypatch.setattr(tests, "probe", probe)
    assert not called
    assert worker.claim(interactive=True) == job["id"]
    await worker.execute(job["id"])
    result = c.get("/api/v1/jobs/" + job["id"]).json()
    assert result["status"] == "succeeded" and result["result"]["success"] is True
    assert called == [original["host"]]
    assert not interactive_tests.redis_client().get(tests.key(job["id"]))
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.IPObservation)) == before
        assert db.scalar(select(func.count()).select_from(m.Integration)) == int(saved)
        if saved:
            row = db.get(m.Integration, stored["id"])
            assert row.encrypted_secret == cipher and row.last_success_at is None
        assert all("NEVER-EXPOSE" not in str(row.details) for row in db.scalars(select(m.Audit)))
    detail = c.get(f"/api/v1/jobs/{job['id']}/details")
    assert detail.status_code == 200 and "Entegrasyon bağlantı testi" in detail.text


async def test_unsaved_override_and_sanitized_failure(admin_client, env, monkeypatch):
    original = payload()
    row = admin_client.post("/api/v1/integrations", json=original).json()
    new = {**original, "host": "another.example.test", "verify_tls": False, "password": "REPLACEMENT-SECRET"}
    job = admin_client.post(f"/api/v1/integrations/{row['id']}/connection-tests", json=new).json()

    def probe(config, secret):
        assert config.host == new["host"] and not config.verify_tls
        assert secret["password"] == new["password"]
        raise RuntimeError("NEVER-EXPOSE-THIS or REPLACEMENT-SECRET")

    monkeypatch.setattr(tests, "probe", probe)
    worker.claim(interactive=True)
    await worker.execute(job["id"])
    response = admin_client.get("/api/v1/jobs/" + job["id"])
    assert response.json()["status"] == "failed"
    assert "REPLACEMENT-SECRET" not in response.text and "NEVER-EXPOSE" not in response.text
    with env() as db:
        saved = db.get(m.Integration, row["id"])
        assert saved.host == original["host"] and saved.verify_tls
        assert json.loads(decrypt(saved.encrypted_secret))["password"] == original["password"]


@pytest.mark.parametrize("state,status", [("offline", 503), ("full", 429)])
def test_admission_failure_leaves_no_pending_test(admin_client, env, state, status):
    if state == "offline":
        interactive_tests.redis_client().set("netrix:tests:heartbeat", None)
    else:
        with env() as db:
            db.add_all(
                [
                    m.Job(
                        kind="test_ssh",
                        target_id=str(i),
                        status="running",
                        heartbeat_at=now(),
                        result={"interactive": True},
                    )
                    for i in range(4)
                ]
            )
            db.commit()
    response = admin_client.post("/api/v1/integrations/connection-tests", json=payload())
    assert response.status_code == status, response.text
    with env() as db:
        assert db.scalar(select(func.count()).select_from(m.Job).where(m.Job.kind == tests.KIND)) == 0


def test_credentials_validation_and_role_boundary(admin_client):
    c = admin_client
    row = c.post("/api/v1/integrations", json=payload()).json()
    base = f"/api/v1/integrations/{row['id']}/connection-tests"
    values = {**payload(), "username": "", "password": ""}
    assert c.post(base, json={**values, "host": "new.example.test"}).status_code == 422
    assert c.post(base, json={**values, "username": "partial"}).status_code == 422
    assert c.post("/api/v1/integrations/connection-tests", json=values).status_code == 422
    assert c.post(base, json={**payload(), "kind": "corner_switch"}).status_code == 422
    c.post(
        "/api/v1/users",
        json={
            "email": "viewer@example.test",
            "display_name": "Viewer",
            "password": "viewer-fixture-password",
            "role": "viewer",
        },
    )
    c.post("/api/v1/auth/logout")
    c.post("/api/v1/auth/login", json={"email": "viewer@example.test", "password": "viewer-fixture-password"})
    assert c.post(base, json=values).status_code == 403


@pytest.mark.parametrize("cancelled", [False, True])
async def test_expiry_and_cancellation_never_probe(admin_client, monkeypatch, cancelled):
    job = admin_client.post("/api/v1/integrations/connection-tests", json=payload()).json()
    probe = Mock(side_effect=AssertionError("Must not connect"))
    monkeypatch.setattr(tests, "probe", probe)
    if cancelled:
        admin_client.post(f"/api/v1/jobs/{job['id']}/cancel")
    else:
        interactive_tests.redis_client().set(tests.key(job["id"]), "")
    worker.claim(interactive=True)
    await worker.execute(job["id"])
    result = admin_client.get("/api/v1/jobs/" + job["id"]).json()
    assert result["status"] == ("cancelled" if cancelled else "failed")
    if not cancelled:
        assert result["result"]["error_code"] == "expired"
    assert not probe.called


def test_protocol_probes_only_read_minimal_data(monkeypatch):
    from types import SimpleNamespace

    from pyVim import connect

    config = SimpleNamespace(kind="windows_dhcp", host="dhcp.example.test", port=5986, verify_tls=True)
    dhcp = Mock(return_value=[])
    monkeypatch.setattr(tests.adapters, "windows_dhcp", dhcp)
    assert "DHCP" in tests.probe(config, {"username": "u", "password": "p"})
    script = dhcp.call_args.kwargs["script"]
    assert "Get-DhcpServerv4Scope" in script and "Get-DhcpServerv4Lease" not in script
    config.kind = "vcenter"
    view = Mock(view=[])
    si = Mock()
    si.RetrieveContent.return_value.viewManager.CreateContainerView.return_value = view
    monkeypatch.setattr(tests.adapters, "connect_vcenter", Mock(return_value=si))
    disconnect = Mock()
    monkeypatch.setattr(connect, "Disconnect", disconnect)
    assert "vCenter" in tests.probe(config, {"username": "u", "password": "p"})
    view.Destroy.assert_called_once()
    disconnect.assert_called_once_with(si)


@pytest.mark.parametrize(
    "exc,code", [(TimeoutError("SECRET"), "timeout"), (ssl.SSLError("SECRET"), "tls_failed")]
)
def test_failure_messages_never_echo_protocol_errors(exc, code):
    value, message = tests.failure(exc)
    assert value == code and "SECRET" not in message
