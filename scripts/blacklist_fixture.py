"""Disposable browser workspace with documentation addresses and no workers."""

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

fixture = tempfile.TemporaryDirectory(prefix="netrix-blacklist-")
os.environ.update(
    NETRIX_DATABASE_URL="sqlite+pysqlite:///" + str(Path(fixture.name) / "test.db"),
    NETRIX_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    NETRIX_SETUP_TOKEN="blacklist-browser-fixture-setup-token",
    NETRIX_PUBLIC_URL="http://127.0.0.1:8291",
    NETRIX_SECURE_COOKIES="false",
    NETRIX_FIRMWARE_DIRECTORY=str(Path(fixture.name) / "images"),
)

from netrix import main, services  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import Base, engine, session_factory  # noqa: E402
from netrix.identity.security import hasher  # noqa: E402


class MemoryRedis:
    def ping(self):
        return True

    def incr(self, *args):
        return 1

    def expire(self, *args):
        return True

    def publish(self, *args):
        return 1


main.redis_client = services.redis_client = lambda: MemoryRedis()
Base.metadata.create_all(engine())
with session_factory()() as db:
    from netrix.inventory.device_types import seed_defaults

    seed_defaults(db)
    db.add(m.SystemState(key="setup", value="complete"))
    db.add(
        m.User(
            email="browser@example.test",
            display_name="Browser Tester",
            role="admin",
            password_hash=hasher.hash("browser-fixture-password"),
        )
    )
    vrf = m.VRF(name="Fixture")
    db.add(vrf)
    db.flush()
    for index, (name, model, adapter) in enumerate(
        [
            ("Fixture 5412", "J9851A", "aruba_5400"),
            ("Fixture 5406", "J9850A", "aruba_5400"),
            ("Fixture 2930", "JL256A", "aruba_2900"),
            ("Fixture 6100", "JL675A", "aruba_6100"),
            ("Fixture 7205", "Aruba 7205", "aruba_7200"),
            ("Fixture HP 1950", "JG963A", "hp_1950"),
            ("Fixture gateway", "JL256A", "aruba_2900"),
        ]
    ):
        db.add(
            m.Device(
                name=name,
                model=model,
                adapter=adapter,
                kind="switch",
                management_ip=f"192.0.2.{index + 1}",
                vrf_id=vrf.id,
                is_gateway=index == 6,
            )
        )
    db.commit()

app = main.app
