"""Isolated browser fixture; never starts workers or touches actual network devices."""

import os
import tempfile
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path

from cryptography.fernet import Fernet

fixture = tempfile.TemporaryDirectory(prefix="netrix-vlan-browser-")
os.environ.update(
    NETRIX_DATABASE_URL="sqlite+pysqlite:///" + str(Path(fixture.name) / "fixture.db"),
    NETRIX_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    NETRIX_SETUP_TOKEN="fixture-setup-only",
    NETRIX_PUBLIC_URL="http://127.0.0.1:8215",
    NETRIX_SECURE_COOKIES="false",
)
from netrix import main, services  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.configuration import baselines  # noqa: E402
from netrix.core import Base, engine, now, session_factory  # noqa: E402
from netrix.discovery import interactive_tests  # noqa: E402
from netrix.identity.security import encrypt, hasher  # noqa: E402
from netrix.inventory.device_types import seed_defaults  # noqa: E402
from netrix.ipam import read_cache  # noqa: E402
from netrix.ipam.service import observe  # noqa: E402


class Redis:
    def __init__(self):
        self.data = {}

    def incr(self, key):
        self.data[key] = self.data.get(key, 0) + 1
        return self.data[key]

    def set(self, key, value, **kwargs):
        self.data[key] = value

    def expire(self, *args):
        pass

    def publish(self, *args):
        pass

    def ping(self):
        return True

    def get(self, key):
        return now().isoformat() if key.endswith(":heartbeat") else self.data.get(key)

    def lock(self, *args, **kwargs):
        return nullcontext()


memory = Redis()
read_cache.client = lambda _: memory
main.redis_client = services.redis_client = interactive_tests.redis_client = lambda: memory
Base.metadata.create_all(engine())

with session_factory()() as db:
    seed_defaults(db)
    db.add(m.SystemState(key="setup", value="complete"))
    db.add(
        m.User(
            email="browser@example.test",
            display_name="Browser",
            password_hash=hasher.hash("browser-fixture-password"),
            role="admin",
        )
    )
    vrf = m.VRF(name="Global")
    institution = m.Institution(name="Fixture Üniversitesi", code="01")
    db.add_all([vrf, institution])
    db.flush()
    site = m.Site(name="Kuzey Kampüs", code="01-000001", institution_id=institution.id)
    credential = m.Credential(
        name="Fixture SNMP", protocol="snmpv2c", encrypted_secret=encrypt('{"community":"fixture"}')
    )
    dns = m.DNSServer(name="Kampüs DNS", address="192.0.2.53")
    db.add_all([site, credential, dns])
    db.flush()
    scope = m.Scope(
        name="Envanter VLAN", vlan_vid=10, cidr="198.51.100.0/24", vrf_id=vrf.id, credential_id=credential.id
    )
    vlan = m.VLAN(
        name="SERVER",
        vid=20,
        cidr="192.0.2.0/24",
        vrf_id=vrf.id,
        institution_id=institution.id,
        site_id=site.id,
        dns_server_id=dns.id,
    )
    db.add(m.Cabinet(name="K-01", site_id=site.id, units=42))
    db.add_all([scope, vlan])
    db.flush()
    config = m.Integration(
        name="Kampüs vCenter",
        kind="vcenter",
        host="vc.example.test",
        port=443,
        enabled=True,
        encrypted_secret=encrypt('{"username":"fixture","password":"fixture"}'),
    )
    db.add(config)
    db.flush()
    for i in range(1, 5):
        d = m.Device(
            name=f"Switch {i}",
            management_ip=f"198.51.100.{i}",
            vrf_id=vrf.id,
            kind="switch",
            discovery_scope_id=scope.id,
        )
        db.add(d)
        db.flush()
        for j in range(2):
            job = m.Job(kind="backup", target_id=d.id, status="succeeded")
            db.add(job)
            db.flush()
            content = f"!Version AOS-CX PL.10.17.103{j}\nhostname switch-{i}\ninterface 1/1/1\n description {'original' if not j else 'changed'}\npassword fixture-secret"
            db.add(
                m.Snapshot(
                    device_id=d.id,
                    job_id=job.id,
                    fingerprint=baselines.fingerprint(content),
                    encrypted_content=encrypt(content),
                    size_bytes=len(content),
                    created_at=now() - timedelta(minutes=2 - j),
                )
            )
            db.flush()
        baselines.rebuild(db, d)
    observe(
        db,
        vlan,
        "192.0.2.10",
        "vcenter",
        config.id + ":vm-1:4000",
        dict(
            hostname="app-01.example.test",
            mac_address="00:11:22:33:44:55",
            vm_id="vm-1",
            nic_key="4000",
            dvswitch_name="FBU-DS",
            dvport="89",
            network="SERVER",
            integration_id=config.id,
        ),
    )
    observe(db, vlan, "192.0.2.10", "icmp", vlan.id, {"reachability": "reachable"})
    db.commit()
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8215, log_level="warning")
