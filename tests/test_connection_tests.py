from types import SimpleNamespace

import pytest
from netrix import models as m
from netrix.discovery import connection_tests as probes
from netrix.discovery import protocols as protocols
from netrix.worker import claim, execute


def device_with_profiles(client, inventory, protocols):
    payload = {"name": "Connection fixture", "management_ip": "192.0.2.1", "vrf_id": inventory["vrf"]["id"]}
    if "snmpv3" in protocols:
        payload["snmp_credential_id"] = inventory["credential"]["id"]
        payload["snmp_port"] = 1161
    for protocol in ("ssh", "rest"):
        if protocol in protocols:
            credential = client.post(
                "/api/v1/credentials",
                json={
                    "name": "Connection " + protocol,
                    "protocol": protocol,
                    "secret": {
                        "username": "fixture-user",
                        "password": "fixture-password",
                        "token": "fixture-token",
                    },
                },
            ).json()
            payload.update(
                config_credential_id=credential["id"],
                adapter="rest" if protocol == "rest" else "fortios",
                config_port=8443 if protocol == "rest" else 2222,
            )
    response = client.post("/api/v1/devices", json=payload)
    assert response.status_code == 201, response.text
    device = response.json()
    if device.get("identification", {}).get("job_id"):
        client.post("/api/v1/jobs/" + device["identification"]["job_id"] + "/cancel")
    return device


@pytest.mark.parametrize(
    "protocols", [[], ["snmpv3"], ["ssh"], ["rest"], ["snmpv3", "ssh"], ["snmpv3", "rest"]]
)
def test_options_only_enable_assigned_compatible_profiles(admin_client, inventory, protocols):
    device = device_with_profiles(admin_client, inventory, protocols)
    response = admin_client.get(f"/api/v1/devices/{device['id']}/connection-tests")
    assert response.status_code == 200
    data = response.json()
    assert {p["protocol"] for p in data["protocols"] if p["enabled"]} == set(protocols)
    assert data["can_test"] == bool(protocols)
    for secret in ("fixture-user", "fixture-password", "fixture-token", "fixture-auth", "encrypted_secret"):
        assert secret not in response.text
    # Merely opening the popup must not enqueue a network test.
    assert not any(
        row["kind"].startswith("test_") for row in admin_client.get("/api/v1/jobs").json()["items"]
    )
    for protocol in {"snmpv3", "ssh", "rest"} - set(protocols):
        assert (
            admin_client.post(
                f"/api/v1/devices/{device['id']}/connection-tests", json={"protocol": protocol}
            ).status_code
            == 422
        )


@pytest.mark.parametrize("protocol", ["snmpv3", "ssh", "rest"])
async def test_selected_protocol_uses_saved_profile_and_no_fallback(
    admin_client, inventory, monkeypatch, protocol
):
    device = device_with_profiles(
        admin_client, inventory, ["snmpv3", protocol] if protocol != "snmpv3" else [protocol, "ssh"]
    )
    calls = []

    async def probe(target, selected, secret, collector):
        calls.append(selected)
        assert target.management_ip == "192.0.2.1" and selected == protocol
        if protocol == "snmpv3":
            assert secret["auth_key"] == "fixture-auth" and target.snmp_port == 1161
        else:
            assert secret["password" if protocol == "ssh" else "token"].startswith("fixture-")
        return "Fixture successful probe"

    monkeypatch.setattr("netrix.worker.probe_connection", probe)
    url = f"/api/v1/devices/{device['id']}/connection-tests"
    response = admin_client.post(url, json={"protocol": protocol})
    assert response.status_code == 202
    job_id = response.json()["id"]
    assert admin_client.post(url, json={"protocol": protocol}).json()["id"] == job_id
    assert calls == []  # API returns promptly; only the worker opens device connections.
    assert claim() == job_id
    await execute(job_id)
    result = admin_client.get("/api/v1/jobs/" + job_id).json()
    assert result["status"] == "succeeded" and result["result"]["success"] is True
    assert result["result"]["protocol"] == protocol and result["result"]["duration_ms"] >= 0
    assert result["result"]["checked_at"].endswith("+00:00")
    assert calls == [protocol]
    assert admin_client.get("/api/v1/devices/" + device["id"]).json()["last_seen_at"] is None
    assert admin_client.get("/api/v1/observations").json()["total"] == 0
    await execute(job_id)
    assert calls == [protocol]  # Redelivery reuses the completed test result.


@pytest.mark.parametrize("exc", [TimeoutError("fixture-password"), OSError("fixture-password")])
async def test_failed_probe_is_terminal_and_sanitized_without_retry(
    admin_client, inventory, monkeypatch, exc
):
    device = device_with_profiles(admin_client, inventory, ["snmpv3", "ssh"])
    calls = []

    async def probe(*args):
        calls.append(args[1])
        raise exc

    monkeypatch.setattr("netrix.worker.probe_connection", probe)
    job = admin_client.post(
        f"/api/v1/devices/{device['id']}/connection-tests", json={"protocol": "snmpv3"}
    ).json()
    claim()
    await execute(job["id"])
    result = admin_client.get("/api/v1/jobs/" + job["id"]).json()
    assert result["status"] == "failed" and result["attempts"] == 1
    assert result["result"]["success"] is False
    assert result["result"]["error_code"] == ("timeout" if isinstance(exc, TimeoutError) else "snmp_failed")
    assert calls == ["snmpv3"]
    assert "fixture-password" not in str(result)
    assert claim() is None


async def test_changed_profile_during_test_invalidates_success(admin_client, inventory, env, monkeypatch):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])

    async def probe(*args):
        with env() as db:
            current = db.get(m.Device, device["id"])
            current.snmp_port = 2161
            db.commit()
        return "Success using old settings"

    monkeypatch.setattr("netrix.worker.probe_connection", probe)
    job = admin_client.post(
        f"/api/v1/devices/{device['id']}/connection-tests", json={"protocol": "snmpv3"}
    ).json()
    claim()
    await execute(job["id"])
    result = admin_client.get("/api/v1/jobs/" + job["id"]).json()
    assert result["status"] == "failed" and result["result"]["error_code"] == "connection_changed"


async def test_cancel_during_connection_test_does_not_report_success(admin_client, inventory, monkeypatch):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])
    job = admin_client.post(
        f"/api/v1/devices/{device['id']}/connection-tests", json={"protocol": "snmpv3"}
    ).json()

    async def probe(*args):
        admin_client.post("/api/v1/jobs/" + job["id"] + "/cancel")
        return "Must not appear as success"

    monkeypatch.setattr("netrix.worker.probe_connection", probe)
    claim()
    await execute(job["id"])
    result = admin_client.get("/api/v1/jobs/" + job["id"]).json()
    assert result["status"] == "cancelled" and not result["result"].get("success")


def test_connection_tests_enforce_scope_and_roles(admin_client, inventory, env):
    device = device_with_profiles(admin_client, inventory, ["snmpv3"])
    with env() as db:
        db.get(m.Device, device["id"]).management_ip = "198.51.100.1"
        db.commit()
    url = f"/api/v1/devices/{device['id']}/connection-tests"
    assert admin_client.get(url).json()["can_test"] is False
    assert admin_client.post(url, json={"protocol": "snmpv3"}).status_code == 422
    assert (
        admin_client.post("/api/v1/jobs", json={"kind": "test_snmp", "target_id": device["id"]}).status_code
        == 422
    )
    admin_client.post(
        "/api/v1/users",
        json={
            "email": "viewer@example.test",
            "display_name": "Viewer",
            "password": "viewer-test-password-long",
            "role": "viewer",
        },
    )
    admin_client.post("/api/v1/auth/logout")
    admin_client.post(
        "/api/v1/auth/login", json={"email": "viewer@example.test", "password": "viewer-test-password-long"}
    )
    assert admin_client.get(url).status_code == 403
    assert admin_client.post(url, json={"protocol": "snmpv3"}).status_code == 403


async def test_ssh_probe_authenticates_with_host_verification_without_running_commands(env, monkeypatch):
    class Context:
        async def __aenter__(self):
            return object()  # No command/run method: this checks login only.

        async def __aexit__(self, *args):
            pass

    def connect(host, **kwargs):
        from netrix.core import settings

        assert host == "192.0.2.1" and kwargs["port"] == 2222
        assert kwargs["username"] == "fixture-user" and kwargs["password"] == "fixture-password"
        assert kwargs["known_hosts"] == settings().known_hosts and kwargs["client_keys"] == []
        return Context()

    monkeypatch.setattr(probes.asyncssh, "connect", connect)
    message = await probes.probe(
        SimpleNamespace(management_ip="192.0.2.1", config_port=2222),
        "ssh",
        {"username": "fixture-user", "password": "fixture-password"},
        None,
    )
    assert "başarılı" in message


@pytest.mark.parametrize(
    "status,body,success",
    [
        (200, b"{}", True),
        (401, b"fixture-token", False),
        (200, b"<html>login</html>", False),
        (302, b"", False),
        (200, b"x" * (256 * 1024 + 1), False),
    ],
)
async def test_api_probe_validates_https_status_json_and_response_limit(monkeypatch, status, body, success):
    import httpx

    calls = []

    def respond(request):
        calls.append(str(request.url))
        assert request.headers["authorization"] == "Bearer fixture-token"
        return httpx.Response(
            status, content=body, headers={"location": "https://outside.example"} if status == 302 else {}
        )

    client = httpx.AsyncClient

    def build_client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        assert kwargs.get("verify", True) is True
        return client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(probes.httpx, "AsyncClient", build_client)
    device = SimpleNamespace(management_ip="2001:db8::1", config_port=8443, identity_path="/device/info")
    if success:
        assert "HTTP 200" in await probes.probe(device, "rest", {"token": "fixture-token"}, None)
    else:
        with pytest.raises(Exception) as error:
            await probes.probe(device, "rest", {"token": "fixture-token"}, None)
        code, message = probes.failure(error.value, "rest")
        assert code and "fixture-token" not in message
    assert calls == ["https://[2001:db8::1]:8443/device/info"]


def test_failure_diagnostics_do_not_expose_remote_exception_text():
    import asyncssh
    import httpx

    for error, protocol, expected in [
        (asyncssh.PermissionDenied("HIDDEN"), "ssh", "authentication_failed"),
        (asyncssh.HostKeyNotVerifiable("HIDDEN"), "ssh", "host_key_failed"),
        (httpx.ConnectError("CERTIFICATE_VERIFY_FAILED HIDDEN"), "rest", "tls_failed"),
    ]:
        code, message = probes.failure(error, protocol)
        assert code == expected and "HIDDEN" not in message


@pytest.mark.parametrize("transport_failure", [False, True])
async def test_snmp_probe_requires_readable_oid_and_always_closes_dispatcher(monkeypatch, transport_failure):
    class Engine:
        closed = False

        def close_dispatcher(self):
            self.closed = True

    class Transport:
        @classmethod
        async def create(cls, *args, **kwargs):
            if transport_failure:
                raise OSError("HIDDEN")
            return object()

    async def get(*args, **kwargs):
        return None, 0, 0, [("oid", value) for value in ["Unknown", "Unknown", "No Such Object", "Unknown"]]

    engine = Engine()
    monkeypatch.setattr(protocols, "SnmpEngine", lambda: engine)
    monkeypatch.setattr(protocols, "UdpTransportTarget", Transport)
    monkeypatch.setattr(protocols, "get_cmd", get)
    with pytest.raises((OSError, protocols.NetworkError)):
        await protocols.SNMPCollector().probe(
            "192.0.2.1", 161, {"username": "fixture", "auth_key": "fixture-auth", "priv_key": "fixture-priv"}
        )
    assert engine.closed
