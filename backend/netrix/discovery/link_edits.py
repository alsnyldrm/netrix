"""Keep operator labels separate from protocol observations."""

from fastapi import HTTPException
from sqlalchemy import case, select

from .. import models as m
from ..identity.security import audit
from .neighbor_detail import remote_port
from .neighbor_labels import neighbor_label


def peer_id(link):
    return link.manual_remote_device_id if link.manual_remote_name is not None else link.remote_device_id


def peer_column():
    return case(
        (m.Link.manual_remote_name.is_not(None), m.Link.manual_remote_device_id),
        else_=m.Link.remote_device_id,
    )


def port_label(link):
    return (
        link.manual_remote_port
        if link.manual_remote_port is not None
        else remote_port(link.evidence or {}, link.remote_port)
    )


def name_label(link):
    return (
        link.manual_remote_name if link.manual_remote_name is not None else neighbor_label(link.remote_name)
    )


def confidence(link):
    # A text correction must not upgrade an inferred identity into protocol proof.
    return min(link.confidence, 0.65) if peer_id(link) != link.remote_device_id else link.confidence


def update_labels(db, id, payload, user):
    from .. import services as svc

    link = db.scalar(select(m.Link).where(m.Link.id == id).with_for_update())
    if link is None:
        raise HTTPException(404, "Bağlantı kaydı bulunamadı")
    device = db.get(m.Device, link.device_id)
    if link.auto_add_excluded or not link.is_current or device.archived:
        raise HTTPException(409, "Yalnızca aktif cihazın güncel komşuluk kaydı düzenlenebilir")
    before = {"remote_name": link.manual_remote_name, "remote_port": link.manual_remote_port}
    link.manual_remote_name, link.manual_remote_port = payload.remote_name, payload.remote_port
    link.manual_remote_device_id = None
    if payload.remote_name is not None:
        candidates = list(
            db.scalars(
                select(m.Device).where(
                    m.Device.name == payload.remote_name,
                    m.Device.vrf_id == device.vrf_id,
                    m.Device.id != device.id,
                    m.Device.archived.is_(False),
                )
            )
        )
        # Ambiguous names are labels only; never choose an arbitrary managed device.
        if len(candidates) == 1:
            link.manual_remote_device_id = candidates[0].id
    after = {"remote_name": link.manual_remote_name, "remote_port": link.manual_remote_port}
    audit(
        db, user, "edit_link_labels", "links", link.id, "Komşu ve uzak port kullanıcı değerleri güncellendi"
    )
    db.add(
        m.Event(
            device_id=link.device_id,
            kind="link_labels_edited",
            message=f"{device.name}: komşuluk alanları kullanıcı tarafından düzenlendi",
            details={"link_id": link.id, "before": before, "after": after},
        )
    )
    db.commit()
    svc.publish()
    return svc.serialize(link)
