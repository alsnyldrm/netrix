"""Record an operator-confirmed device connection separately from discovery."""

from sqlalchemy import select

from .. import models as m


def confirm_link(db, local_id, remote_id):
    local, remote = db.get(m.Device, local_id), db.get(m.Device, remote_id)
    if not local or not remote or local.id == remote.id or local.vrf_id != remote.vrf_id:
        raise ValueError("Bağlantı için aynı VRF içinde iki farklı cihaz gerekli")
    if local.archived or remote.archived:
        raise ValueError("Arşivlenmiş cihaz bağlanamaz")
    existing = db.scalar(
        select(m.Link).where(
            m.Link.source == "manual", m.Link.device_id == local.id, m.Link.remote_device_id == remote.id
        )
    )
    if existing:
        return existing
    # Unknown physical ports stay empty; the confirmation is at device level.
    link = m.Link(
        device_id=local.id,
        remote_device_id=remote.id,
        remote_name=remote.name,
        interface_name="",
        remote_port="",
        source="manual",
        confidence=1,
    )
    db.add(link)
    db.add(
        m.Event(
            device_id=local.id,
            kind="link_confirmed",
            message="Kullanıcı cihaz bağlantısını doğruladı",
            details={"remote_device_id": remote.id, "source": "manual", "ports_known": False},
        )
    )
    db.flush()
    return link
