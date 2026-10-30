"""Disposable local browser fixture. No scheduler, worker or real device connections."""

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

fixture = tempfile.TemporaryDirectory(prefix="netrix-inventory-browser-")
os.environ.update(
    NETRIX_DATABASE_URL="sqlite+pysqlite:///" + str(Path(fixture.name) / "fixture.db"),
    NETRIX_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    NETRIX_SETUP_TOKEN="browser-fixture-setup-token-only",
    NETRIX_PUBLIC_URL=os.environ.get("NETRIX_PUBLIC_URL", "http://127.0.0.1:8205"),
    NETRIX_SECURE_COOKIES="false",
)
from netrix import main, services  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import Base, engine, session_factory  # noqa: E402
from netrix.identity.security import encrypt, hasher  # noqa: E402


class MemoryRedis:
    def __init__(self):
        self.values = {}

    def ping(self):
        return True

    def publish(self, *args):
        return 1

    def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, *args):
        return True

    def get(self, key):
        return self.values.get(key)


memory = MemoryRedis()
main.redis_client = services.redis_client = lambda: memory
Base.metadata.create_all(engine())
with session_factory()() as db:
    from netrix.inventory.device_types import seed_defaults

    seed_defaults(db)
    db.add(m.SystemState(key="setup", value="complete"))
    db.add(
        m.User(
            email="browser@example.test",
            display_name="Browser Tester",
            password_hash=hasher.hash("browser-fixture-password"),
            role="admin",
        )
    )
    vrf = m.VRF(name="Global")
    site = m.Site(name="Kuzey Kampüs", code="N")
    group = m.BackupGroup(name="Firewall", interval_seconds=0, retention_count=0)
    profile = m.Credential(
        name="Fixture SSH",
        protocol="ssh",
        encrypted_secret=encrypt('{"username":"fixture","password":"fixture-password"}'),
    )
    db.add_all([vrf, site, group, profile])
    db.flush()
    for i in range(35):
        device = m.Device(
            name=f"Fixture {i:02}",
            management_ip=f"192.0.2.{i + 1}",
            vrf_id=vrf.id,
            site_id=site.id,
            kind="firewall" if i == 0 else "switch",
            model="600F" if i == 0 else "X1",
            vendor="Acme",
            adapter="fortios",
            config_credential_id=profile.id,
            backup_group_id=group.id if i == 0 else None,
        )
        db.add(device)
        db.flush()
        if i == 0:
            for j in range(4):
                db.add(
                    m.Interface(
                        device_id=device.id,
                        name=f"port{j + 1}",
                        if_index=j + 1,
                        speed_bps=1000000000,
                        oper_status="up",
                        is_managed=j == 0,
                    )
                )
        if i in (0, 1):
            for j in range(2 if i == 0 else 1):
                job = m.Job(kind="backup", target_id=device.id, status="succeeded")
                db.add(job)
                db.flush()
                db.add(
                    m.Snapshot(
                        device_id=device.id,
                        job_id=job.id,
                        encrypted_content=encrypt(f"hostname fixture-{j}\npassword FIXTURE-SECRET"),
                        fingerprint=str(j),
                        size_bytes=50,
                        changed=bool(j),
                    )
                )
    db.commit()
app = main.app
