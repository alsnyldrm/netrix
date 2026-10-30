"""Run on an isolated disposable MariaDB netrix_test database only."""

import subprocess

from netrix import models as m
from netrix.core import engine, session_factory
from netrix.inventory.management import query
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError

assert engine().url.database == "netrix_test"


def migrate(*args, check=True):
    result = subprocess.run(["alembic", "-c", "backend/alembic.ini", *args], capture_output=True)
    if check and result.returncode:
        raise AssertionError(result.stderr.decode())
    return result


migrate("upgrade", "20261030_06")
with session_factory()() as db:
    db.execute(insert(m.VRF.__table__).values(id="types-vrf", name="Types test"))
    db.execute(
        insert(m.Credential.__table__).values(
            id="types-profile", name="Types SSH", protocol="ssh", encrypted_secret="fixture-ciphertext"
        )
    )
    for code in ("firewall", "legacy"):
        db.execute(
            insert(m.Device.__table__).values(
                id="types-" + code,
                name="Existing " + code,
                management_ip="192.0.2.1" if code == "firewall" else "192.0.2.2",
                vrf_id="types-vrf",
                kind=code,
                config_credential_id="types-profile",
                ssh_trust_host_key=True,
            )
        )
    db.execute(
        insert(m.Interface.__table__).values(
            id="types-port", name="port1", device_id="types-firewall", is_managed=True
        )
    )
    db.commit()
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    device = db.get(m.Device, "types-firewall")
    assert device.kind == "firewall" and device.device_type.name == "Firewall"
    assert device.config_credential_id == "types-profile" and device.ssh_trust_host_key
    assert db.get(m.Device, "types-legacy").device_type.name == "Tür · legacy"
    try:
        db.execute(delete(m.DeviceType).where(m.DeviceType.code == "firewall"))
        db.commit()
    except (IntegrityError, OperationalError):
        db.rollback()
    else:
        raise AssertionError("Used type deletion must fail at DB level")
    try:
        db.execute(update(m.Device).where(m.Device.id == device.id).values(kind="absent"))
        db.commit()
    except (IntegrityError, OperationalError):
        db.rollback()
    else:
        raise AssertionError("Unknown kind must fail at DB level")
    db.execute(update(m.DeviceType).where(m.DeviceType.code == "firewall").values(name="Güvenlik Duvarı"))
    db.commit()
    assert query(db, "devices", q="Güvenlik")["total"] == 1
    assert query(db, "interfaces", q="Güvenlik")["items"][0]["device_kind_name"] == "Güvenlik Duvarı"
result = migrate("downgrade", "20261030_06", check=False)
assert result.returncode and b"custom data" in result.stderr
with session_factory()() as db:
    assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261030_07"
    db.execute(delete(m.Device).where(m.Device.id == "types-legacy"))
    db.execute(delete(m.DeviceType).where(m.DeviceType.code == "legacy"))
    db.execute(update(m.DeviceType).where(m.DeviceType.code == "firewall").values(name="Firewall"))
    db.commit()
migrate("downgrade", "20261030_06")
migrate("upgrade", "head")
migrate("check")
with session_factory()() as db:
    assert db.get(m.Device, "types-firewall").kind == "firewall"
    assert db.get(m.Interface, "types-port").device_id == "types-firewall"
    assert db.get(m.Credential, "types-profile").encrypted_secret == "fixture-ciphertext"
    assert db.scalar(select(m.DeviceType.name).where(m.DeviceType.code == "other")) == "Diğer"
print(
    "MariaDB device types PASS: upgrade, legacy values, preserved relationships, FK guards, search, guarded downgrade, round trip and schema"
)
