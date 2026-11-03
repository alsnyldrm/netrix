"""Disposable UI fixture. No worker or real device traffic; terminal WebSockets are browser mocks."""

import os
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path

from cryptography.fernet import Fernet

fixture = tempfile.TemporaryDirectory(prefix="netrix-user-workspace-")
os.environ.update(
    NETRIX_DATABASE_URL="sqlite+pysqlite:///" + str(Path(fixture.name) / "test.db"),
    NETRIX_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    NETRIX_SETUP_TOKEN="workspace-browser-setup-token",
    NETRIX_PUBLIC_URL="http://127.0.0.1:8241",
    NETRIX_SECURE_COOKIES="false",
)
from netrix import main, services  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.access import ephemeral as e  # noqa: E402
from netrix.core import Base, engine, session_factory  # noqa: E402
from netrix.identity.security import encrypt, hasher  # noqa: E402


class MemoryRedis:
    def __init__(self):
        self.data = {}
        self.zsets = {}

    def hmget(self, key, fields):
        return [None for _ in fields]

    def pipeline(self, **kwargs):
        class Pipeline:
            def __init__(pipe):
                pipe.calls = []

            def __enter__(pipe):
                return pipe

            def __exit__(pipe, *args):
                pass

            def set(pipe, *args, **kwargs):
                pipe.calls.append((self.set, args, kwargs))

            def zadd(pipe, *args, **kwargs):
                pipe.calls.append((self.zadd, args, kwargs))

            def rpush(pipe, *args, **kwargs):
                pipe.calls.append((self.rpush, args, kwargs))

            def execute(pipe):
                for call, args, kwargs in pipe.calls:
                    call(*args, **kwargs)

        return Pipeline()

    def get(self, key):
        if key == e.PREFIX + "heartbeat":
            return str(time.time())
        return self.data.get(key)

    def set(self, key, value, **kwargs):
        self.data[key] = value
        if key.startswith(e.PREFIX + "cancel:"):
            id = key.rsplit(":", 1)[1]
            for entries in self.zsets.values():
                entries.pop(id, None)
        return True

    def lock(self, *args, **kwargs):
        return nullcontext()

    def zremrangebyscore(self, key, low, high):
        pass

    def zrange(self, key, *args):
        return list(self.zsets.get(key, {}))

    def zadd(self, key, value):
        self.zsets.setdefault(key, {}).update(value)

    def rpush(self, key, value):
        import json

        data = json.loads(value)
        if data["kind"] == "batch":
            record = e.unpack(self.data[e.key("batch", data["id"])])
            record["status"] = "completed"
            for n, target in enumerate(record["targets"]):
                target.update(
                    status="succeeded" if target["name"] == "SW-01" else "failed",
                    output="NETRIX fixture SSH output"
                    if target["name"] == "SW-01"
                    else "Fixture: authentication failed",
                )
            self.data[e.key("batch", data["id"])] = e.pack(record)

    def ping(self):
        return True

    def incr(self, key):
        return 1

    def expire(self, *args):
        return True

    def publish(self, *args):
        return 1


memory = MemoryRedis()
main.redis_client = services.redis_client = e.redis_client = lambda: memory
Base.metadata.create_all(engine())
with session_factory()() as db:
    from netrix.inventory.device_types import seed_defaults

    seed_defaults(db)
    user = m.User(
        email="browser@example.test",
        display_name="Browser Tester",
        role="admin",
        password_hash=hasher.hash("browser-fixture-password"),
    )
    vrf = m.VRF(name="Global")
    credential = m.Credential(name="Fixture SNMP", protocol="snmpv3", encrypted_secret=encrypt("{}"))
    db.add_all([m.SystemState(key="setup", value="complete"), user, vrf, credential])
    db.flush()
    scope = m.Scope(name="Fixture network", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=credential.id)
    db.add(scope)
    db.flush()
    db.add(
        m.UserWorkspace(
            user_id=user.id,
            preferences={},
            encrypted_ssh=encrypt(
                '{"username":"fixture","password":"fixture-password","port":22,"connect_timeout":10,"initial_command":""}'
            ),
        )
    )
    for n in range(20):
        db.add(
            m.Device(
                name=f"SW-{n + 1:02}",
                management_ip=f"192.0.2.{n + 1}",
                vrf_id=vrf.id,
                discovery_scope_id=scope.id,
                kind="switch",
                vendor="Aruba",
                adapter="aruba_2900",
            )
        )
    db.commit()
app = main.app
