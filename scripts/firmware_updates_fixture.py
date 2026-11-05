"""Version comparison browser scenarios; disposable DB, no worker or network I/O."""

from netrix import models as m
from netrix.core import session_factory
from sqlalchemy import select

from scripts.firmware_fixture import app  # noqa: F401

with session_factory()() as db:
    user = db.scalar(select(m.User))
    # Reproduce inventory normalization: generic series names with older uploads
    # that still contain SKU notes. No device query or worker is involved.
    for device in db.scalars(select(m.Device)):
        device.model = "6100" if device.adapter == "aruba_6100" else "2930F"
    missing = db.scalar(select(m.Device).where(m.Device.name == "Fixture 0998"))
    missing.adapter, missing.model, missing.software_version = "hp_1950", "1950-JG962A", "R3507P09"
    db.add(
        m.FirmwareImage(
            name="Aruba comparison image",
            family="aos_s_29xx",
            version="WC.16.11.0026",
            models=["JL256A"],
            original_name="comparison.swi",
            expected_sha256="b" * 64,
            sha256="b" * 64,
            size_bytes=100,
            status="ready",
            uploaded_by=user.id,
        )
    )
    for name, value in (
        ("Fixture 0001", "WC.16.11.0026"),
        ("Fixture 0002", "WC.16.12.0001"),
        ("Fixture 0003", ""),
        ("Fixture 0006", "WC.16.11.0026"),
    ):
        db.scalar(select(m.Device).where(m.Device.name == name)).software_version = value
    for name, members in (("Erişim güncelleme grubu", [0, 1, 2, 3]), ("Yönetim güncelleme grubu", [5, 6])):
        group = m.FirmwareGroup(name=name)
        db.add(group)
        db.flush()
        for number in members:
            device = db.scalar(select(m.Device).where(m.Device.name == f"Fixture {number:04}"))
            db.add(m.FirmwareMember(group_id=group.id, device_id=device.id))
    db.commit()
