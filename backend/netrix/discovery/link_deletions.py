"""Keep deleted observations as durable discovery exclusions."""

from fastapi import HTTPException
from sqlalchemy import select

from .. import models as m
from ..identity.security import audit
from .neighbor_labels import neighbor_label


def observation(link):
    return {
        key: getattr(link, key)
        for key in ("interface_name", "remote_name", "remote_port", "source", "evidence")
    }


def matches(link, neighbor, db=None):
    from .links import legacy_match

    # A portless manual connection represents the entire device pair.
    if db is not None and link.source == "manual" and not link.interface_name and link.remote_device_id:
        from .neighbor_detail import addresses

        remote = db.get(m.Device, link.remote_device_id)
        if remote:
            advertised = addresses(neighbor)
            if advertised:
                return remote.management_ip in advertised
            if neighbor_label(neighbor["remote_name"]) in (remote.name, neighbor_label(link.remote_name)):
                return True
    # Compare the original protocol values, never the user's display corrections.
    if all(
        neighbor_label(getattr(link, key)) == neighbor_label(neighbor[key])
        for key in ("interface_name", "remote_name", "remote_port")
    ):
        return True
    return legacy_match(link, neighbor)


def delete_link(db, id, user):
    from .. import services as svc

    target = svc.get(db, m.Link, id)
    # Use the same deterministic lock order as the worker and reload stale ORM state.
    links = list(
        db.scalars(
            select(m.Link)
            .where(m.Link.device_id == target.device_id)
            .order_by(m.Link.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if target.auto_add_excluded:
        return
    device = db.get(m.Device, target.device_id)
    if device.archived or not target.is_current:
        raise HTTPException(409, "Yalnızca aktif cihazın güncel komşuluk kaydı silinebilir")
    removed = []
    for row in links:
        if (
            row.id == target.id
            or matches(target, observation(row), db)
            or matches(row, observation(target), db)
        ):
            row.auto_add_excluded = True
            row.is_current = False
            removed.append(row.id)
    audit(db, user, "delete_link", "links", id, "Komşuluk silindi; keşifte yeniden eklenmesi engellendi")
    db.add(
        m.Event(
            device_id=target.device_id,
            kind="link_deleted",
            message=f"{device.name}: komşuluk silindi ve yeniden keşfi engellendi",
            details={"link_id": id, "excluded_ids": removed, "interface_name": target.interface_name},
        )
    )
    db.commit()
    svc.publish()
