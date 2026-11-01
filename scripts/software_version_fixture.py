"""Disposable software version UI data; never contacts a real device."""

from sqlalchemy import select

from scripts.archive_fixture import app, m, session_factory  # noqa: F401

with session_factory()() as db:
    device = db.scalar(select(m.Device).where(m.Device.name == "Fixture 00"))
    device.software_version = "KB.16.11.0032"
    device.vendor, device.model, device.kind = "HP", "J9851A", "switch"
    db.commit()
