import socket
from contextlib import nullcontext

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from netrix.core import Base, engine, settings
from netrix.models import SystemState
from sqlalchemy.orm import sessionmaker


class MemoryRedis:
    def __init__(self):
        self.data = {}

    def lock(self, *args, **kwargs):
        return nullcontext()

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
        from netrix.inventory.device_types import seed_defaults

        seed_defaults(db)
        db.add(SystemState(key="setup", value="pending"))
        db.commit()
    memory = MemoryRedis()
    # API tests use a fake ready interactive worker; no real protocol operations.
    from netrix.core import now
    from netrix.discovery import interactive_tests

    memory.set("netrix:tests:heartbeat", now().isoformat())
    monkeypatch.setattr(interactive_tests, "redis_client", lambda: memory)
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


@pytest.fixture
def transfer_profiles(admin_client, institution, env):
    """Existing public profile references required by device file imports."""
    response = admin_client.post(
        "/api/v1/sites", json={"name": "Site-01", "code": "TRANSFER", "institution_id": institution["id"]}
    )
    assert response.status_code == 201, response.text
    for name, protocol, secret in (
        (
            "SNMP-Profil-01",
            "snmpv3",
            {"username": "fixture", "auth_key": "fixture-auth", "priv_key": "fixture-priv"},
        ),
        ("SSH-Profil-01", "ssh", {"username": "fixture", "password": "fixture-password"}),
    ):
        response = admin_client.post(
            "/api/v1/credentials", json={"name": name, "protocol": protocol, "secret": secret}
        )
        assert response.status_code == 201, response.text

    from netrix import models as m
    from sqlalchemy import select

    with env() as db:
        vrf = db.scalar(select(m.VRF))
        db.add(
            m.Scope(
                name="Import network",
                cidr="192.0.2.0/24",
                vrf_id=vrf.id,
                vlan_vid=20,
                credential_id=db.scalar(select(m.Credential.id).where(m.Credential.protocol == "snmpv3")),
            )
        )
        db.commit()


@pytest.fixture
def institution(admin_client):
    result = admin_client.post("/api/v1/institutions", json={"name": "Test institution", "code": "01"})
    assert result.status_code == 201
    return result.json()


def vlan_payload(data):
    """Network fixtures now belong to VLANs; keep test address boundaries unchanged."""
    import hashlib

    key = str(data.get("vrf_id", "")) + str(data.get("cidr", ""))
    return {
        "name": "Fixture VLAN",
        "vid": 10,
        "domain": hashlib.sha256(key.encode()).hexdigest()[:20],
        **data,
    }


def make_vlan(**data):
    from netrix.models import VLAN

    return VLAN(**vlan_payload(data))


def make_inventory_scope(db, vrf_id, cidr="192.0.2.0/24"):
    """Persist explicit inventory ownership for topology fixtures."""
    from netrix import models as m
    from netrix.identity.security import encrypt

    credential = m.Credential(name="Topology fixture SNMP", protocol="snmpv3", encrypted_secret=encrypt("{}"))
    db.add(credential)
    db.flush()
    scope = m.Scope(name="Inventory VLAN", cidr=cidr, vrf_id=vrf_id, credential_id=credential.id, vlan_vid=10)
    db.add(scope)
    db.flush()
    return scope
