import socket

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from netrix.core import Base, engine, settings
from netrix.models import SystemState
from sqlalchemy.orm import sessionmaker


class MemoryRedis:
    def __init__(self):
        self.data = {}

    def ping(self):
        return True

    def publish(self, *args):
        return 1

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def expire(self, *args):
        return True

    def set(self, key, value, **kwargs):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)


@pytest.fixture(autouse=True)
def prohibit_real_network(monkeypatch):
    original = socket.socket.connect

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Real network access is forbidden in unit tests")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NETRIX_DATABASE_URL", "sqlite+pysqlite:///" + str(tmp_path / "test.db"))
    monkeypatch.setenv("NETRIX_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("NETRIX_SETUP_TOKEN", "test-only-setup-token-32-characters")
    monkeypatch.setenv("NETRIX_SECURE_COOKIES", "false")
    monkeypatch.setenv("NETRIX_PUBLIC_URL", "http://testserver")
    settings.cache_clear()
    engine.cache_clear()
    from netrix import main, services, worker

    Base.metadata.create_all(engine())
    sf = sessionmaker(engine(), expire_on_commit=False)
    with sf() as db:
        db.add(SystemState(key="setup", value="pending"))
        db.commit()
    memory = MemoryRedis()
    for module in (main, services, worker):
        monkeypatch.setattr(module, "redis_client", lambda: memory)
    yield sf
    engine().dispose()
    engine.cache_clear()
    settings.cache_clear()


@pytest.fixture
def client(env):
    from netrix.main import app

    with TestClient(app, headers={"X-Netrix-Request": "1"}) as client:
        yield client


@pytest.fixture
def admin_client(client):
    response = client.post(
        "/api/v1/auth/setup",
        json={
            "email": "owner@example.test",
            "display_name": "Owner",
            "password": "test-only-password-long",
            "setup_token": settings().setup_token,
        },
    )
    assert response.status_code == 201, response.text
    response = client.post(
        "/api/v1/auth/login", json={"email": "owner@example.test", "password": "test-only-password-long"}
    )
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def inventory(admin_client):
    c = admin_client
    vrf = c.get("/api/v1/vrfs").json()["items"][0]
    credential = c.post(
        "/api/v1/credentials",
        json={
            "name": "Test SNMP",
            "protocol": "snmpv3",
            "secret": {"username": "fixture", "auth_key": "fixture-auth", "priv_key": "fixture-priv"},
        },
    ).json()
    scope = c.post(
        "/api/v1/scopes",
        json={
            "name": "Fixture network",
            "cidr": "192.0.2.0/30",
            "vrf_id": vrf["id"],
            "credential_id": credential["id"],
        },
    ).json()
    return {"vrf": vrf, "credential": credential, "scope": scope}
