"""Isolated browser fixture; never starts workers or touches actual network devices."""

import json
import os
import tempfile
from contextlib import nullcontext
from pathlib import Path

from cryptography.fernet import Fernet

fixture = tempfile.TemporaryDirectory(prefix="netrix-ipam-browser-")
os.environ.update(
    NETRIX_DATABASE_URL="sqlite+pysqlite:///" + str(Path(fixture.name) / "fixture.db"),
    NETRIX_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    NETRIX_SETUP_TOKEN="fixture-setup-only",
    NETRIX_PUBLIC_URL="http://127.0.0.1:8211",
    NETRIX_SECURE_COOKIES="false",
)
from netrix import main, services  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import Base, engine, now, session_factory  # noqa: E402
from netrix.discovery import interactive_tests  # noqa: E402
from netrix.identity.security import encrypt, hasher  # noqa: E402
from netrix.inventory.device_types import seed_defaults  # noqa: E402
from netrix.ipam.service import observe  # noqa: E402


class Redis:
    def incr(self, *args):
        return 1

    def expire(self, *args):
        pass

    def publish(self, *args):
        pass

    def ping(self):
        return True

    def get(self, *args):
        return now().isoformat()

    def lock(self, *args, **kwargs):
        return nullcontext()


memory = Redis()
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
    site = m.Site(name="Kuzey Kampüs", code="N")
    db.add_all([vrf, site])
    db.flush()
    credential = m.Credential(
        name="Fixture SNMP",
        protocol="snmpv3",
        encrypted_secret=encrypt(
            json.dumps({"username": "fixture", "auth_key": "fixture-auth", "priv_key": "fixture-priv"})
        ),
    )
    dns = m.DNSServer(name="Kampüs DNS", address="192.0.2.53")
    db.add_all([credential, dns])
    db.flush()
    device = m.Device(
        name="Core Switch",
        management_ip="192.0.2.254",
        vrf_id=vrf.id,
        site_id=site.id,
        kind="switch",
        snmp_credential_id=credential.id,
    )
    scope = m.Scope(
        name="Yetkili kampüs ağı", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=credential.id
    )
    db.add_all([device, scope])
    db.flush()
    port = m.Interface(
        device_id=device.id, name="GigabitEthernet1/0/12", if_index=12, is_managed=True, speed_bps=1000000000
    )
    p = m.Prefix(
        cidr="192.0.2.0/24",
        vrf_id=vrf.id,
        site_id=site.id,
        description="Sunucu ağı",
        scope_id=scope.id,
        dns_server_id=dns.id,
    )
    db.add_all([port, p])
    db.flush()
    config = m.Integration(
        name="Kampüs vCenter",
        kind="vcenter",
        host="vc.example.test",
        port=443,
        enabled=True,
        prefix_ids=[p.id],
        interval_seconds=0,
        encrypted_secret=encrypt('{"username":"fixture","password":"fixture-only"}'),
    )
    db.add(config)
    db.flush()
    ip = observe(
        db,
        p,
        "192.0.2.10",
        "vcenter",
        config.id + ":vm-1:4000",
        dict(
            hostname="app-01.example.test",
            mac_address="00:11:22:33:44:55",
            operating_system="Ubuntu Linux 24.04",
            power_state="poweredOn",
            network="DV-Servers",
            vm_id="vm-1",
            nic_key="4000",
            dvport="42",
            integration_id=config.id,
        ),
    )
    ip.cabinet = "K-04"
    ip.location = "Veri merkezi / Kat 1"
    ip.interface_id = port.id
    db.commit()
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(main.app, host="127.0.0.1", port=8211, log_level="warning")
