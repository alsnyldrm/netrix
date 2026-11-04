"""Version comparison browser scenarios; disposable DB, no worker or network I/O."""

from netrix import models as m
from netrix.core import session_factory
from sqlalchemy import select

from scripts.firmware_fixture import app  # noqa: F401

with session_factory()() as db:
    user = db.scalar(select(m.User))
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
