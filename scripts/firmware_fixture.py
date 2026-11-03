"""Disposable browser fixture; no workers, schedules or real device connections."""

import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

fixture = tempfile.TemporaryDirectory(prefix="netrix-firmware-browser-")
port = int(os.environ.get("NETRIX_FIRMWARE_FIXTURE_PORT", "8231"))
os.environ.update(
    NETRIX_DATABASE_URL="sqlite+pysqlite:///" + str(Path(fixture.name) / "test.db"),
    NETRIX_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    NETRIX_SETUP_TOKEN="firmware-browser-fixture-setup-token",
    NETRIX_PUBLIC_URL=f"http://127.0.0.1:{port}",
    NETRIX_SECURE_COOKIES="false",
    NETRIX_FIRMWARE_DIRECTORY=str(Path(fixture.name) / "images"),
    NETRIX_FIRMWARE_ADVERTISE_HOST="192.0.2.100",
)
from netrix import main, services  # noqa: E402
from netrix import models as m  # noqa: E402
from netrix.core import Base, engine, now, session_factory  # noqa: E402
from netrix.identity.security import encrypt, hasher  # noqa: E402


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
from types import SimpleNamespace  # noqa: E402

from netrix.firmware import api as firmware_api  # noqa: E402

firmware_api.shutil.disk_usage = lambda _: SimpleNamespace(free=2 * 1024**3)
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
    vrf = m.VRF(name="Global")
    profile = m.Credential(
        name="Fixture SSH",
        protocol="ssh",
        encrypted_secret=encrypt('{"username":"fixture","password":"fixture-password"}'),
    )
    db.add_all([vrf, profile])
    db.flush()
    scope = m.Scope(
        name="Fixture scope", cidr="192.0.2.0/24", vrf_id=vrf.id, credential_id=profile.id, vlan_vid=10
    )
    db.add(scope)
    db.flush()
    for n in range(1000):
        db.add(
            m.Device(
                name=f"Fixture {n:04}",
                management_ip=f"198.18.{n // 250}.{n % 250 + 1}",
                vrf_id=vrf.id,
                discovery_scope_id=scope.id,
                model="JL675A" if n == 999 else "JL256A",
                vendor="Aruba",
                adapter="aruba_6100" if n == 999 else "aruba_2900",
                kind="switch",
                config_credential_id=profile.id,
                software_version="PL.10.17.1030" if n == 999 else "WC.16.10.0025",
            )
        )
    db.flush()
    # Populated tables exercise alignment, wrapping and recovery actions. These
    # records live only in the disposable fixture DB; no worker is started.
    from sqlalchemy import select

    device = db.scalar(select(m.Device).where(m.Device.name == "Fixture 0999"))
    user = db.scalar(select(m.User))
    image = m.FirmwareImage(
        name="Fixture firmware",
        family="cx6100",
        version="PL.10.18.1010",
        models=["JL675A"],
        original_name="fixture.swi",
        expected_sha256="a" * 64,
        sha256="a" * 64,
        status="ready",
        size_bytes=285115183,
    )
    group = m.FirmwareGroup(name="Fixture group", description="Fixture alignment sample")
    db.add_all([image, group])
    db.flush()
    db.add(m.FirmwareMember(group_id=group.id, device_id=device.id))
    for status, name in (("paused", "Fixture paused plan"), ("cancelled", "Fixture history plan")):
        plan = m.FirmwarePlan(
            name=name,
            status=status,
            mode="upgrade",
            requested_by=user.id,
            steps=[{"group_name": group.name, "version": image.version, "count": 1}],
        )
        db.add(plan)
        db.flush()
        db.add(
            m.FirmwareTarget(
                plan_id=plan.id,
                device_id=device.id,
                image_id=image.id,
                stage=0,
                status="attention" if status == "paused" else "cancelled",
                phase="transferring",
                bank="primary",
                previous_bank="secondary",
                previous_version="PL.10.17.1030",
                error_code="image",
                error="Firmware hedef yazılım alanında doğrulanamadı. Sonucu yeniden doğrulayın.",
                evidence={
                    "device_name": device.name,
                    "management_ip": device.management_ip,
                    "expected_version": image.version,
                },
                finished_at=now(),
            )
        )
    db.commit()

    # New transcript examples are confined to this disposable DB and never sent to devices.
    from netrix.firmware.history import add_event

    extra_devices = list(
        db.scalars(
            select(m.Device)
            .where(m.Device.name.in_(("Fixture 0000", "Fixture 0001")))
            .order_by(m.Device.name)
        )
    )
    transcript_plan = m.FirmwarePlan(
        name="Fixture transcript operation",
        status="paused",
        mode="upgrade",
        requested_by=user.id,
        steps=[
            {"group_name": "Erişim switchleri", "version": image.version, "count": 2},
            {"group_name": "Yönetim switchleri", "version": image.version, "count": 1},
        ],
    )
    db.add(transcript_plan)
    db.flush()
    for n, fixture_device in enumerate([device, *extra_devices]):
        target = m.FirmwareTarget(
            plan_id=transcript_plan.id,
            device_id=fixture_device.id,
            image_id=image.id,
            stage=0 if n < 2 else 1,
            status="succeeded" if n == 0 else "attention" if n == 1 else "queued",
            phase="verifying" if n == 0 else "transferring" if n == 1 else "waiting",
            bank="primary",
            previous_bank="secondary",
            previous_version="PL.10.17.1030",
            verified_version=image.version if n == 0 else "",
            error_code="image" if n == 1 else "",
            error="İmaj hedef yazılım alanında doğrulanamadı." if n == 1 else "",
            transfer_bytes=image.size_bytes if n == 0 else 1024**2,
            evidence={
                "device_name": fixture_device.name,
                "management_ip": fixture_device.management_ip,
                "expected_version": image.version,
                "protocol": "scp",
                "history_version": 1,
            },
        )
        db.add(target)
        db.flush()
        if n == 2:
            continue
        for step in range(45 if n == 0 else 2):
            add_event(
                db,
                target,
                kind="command",
                title="Cihaz sorgusu",
                status="succeeded" if n == 0 else "failed",
                command="show version" if step == 0 else "show images",
                response="Version : PL.10.18.1010\nActive Image : primary\n<device-output>\npassword fixture-output-secret\n"
                + ("response-line\n" * 1300 if step == 1 else "Fixture response"),
                finished=True,
            )
    db.commit()

app = main.app
