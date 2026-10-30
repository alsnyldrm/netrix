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
    delete_links(db, [id], user)


def locked_selection(db, ids):
    ids = sorted(set(ids))
    targets = list(db.scalars(select(m.Link).where(m.Link.id.in_(ids))))
    if len(targets) != len(ids):
        raise HTTPException(404, "Seçilen kayıtlardan biri bulunamadı")
    # Use the same deterministic lock order as the worker and reload stale ORM state.
    links = list(
        db.scalars(
            select(m.Link)
            .where(m.Link.device_id.in_({target.device_id for target in targets}))
            .order_by(m.Link.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    return targets, links


def delete_links(db, ids, user):
    from .. import services as svc

    targets, links = locked_selection(db, ids)
    devices = {target.device_id: db.get(m.Device, target.device_id) for target in targets}
    # Validate the entire selection before changing any observation or audit record.
    if any(
        not target.auto_add_excluded and (devices[target.device_id].archived or not target.is_current)
        for target in targets
    ):
        raise HTTPException(409, "Yalnızca aktif cihazın güncel komşuluk kaydı silinebilir")
    for target in sorted(targets, key=lambda row: row.id):
        if target.auto_add_excluded:
            continue
        device = devices[target.device_id]
        removed = []
        for row in links:
            if row.device_id == target.device_id and (
                row.id == target.id
                or matches(target, observation(row), db)
                or matches(row, observation(target), db)
            ):
                row.auto_add_excluded = True
                row.is_current = False
                removed.append(row.id)
        audit(
            db,
            user,
            "delete_link",
            "links",
            target.id,
            "Komşuluk silindi; keşifte yeniden eklenmesi engellendi",
        )
        db.add(
            m.Event(
                device_id=target.device_id,
                kind="link_deleted",
                message=f"{device.name}: komşuluk silindi ve yeniden keşfi engellendi",
                details={
                    "link_id": target.id,
                    "excluded_ids": removed,
                    "interface_name": target.interface_name,
                },
            )
        )
    db.commit()
    svc.publish()
    return {"updated": len(targets)}


def restore_links(db, ids, user):
    from .. import services as svc

    targets, links = locked_selection(db, ids)
    devices = {target.device_id: db.get(m.Device, target.device_id) for target in targets}
    if any(devices[target.device_id].archived for target in targets):
        raise HTTPException(
            409, "Önce kaynak cihazı Envanter → Arşivlenmiş cihazlar menüsünden geri yükleyin"
        )
    if any(not target.auto_add_excluded and not target.is_current for target in targets):
        raise HTTPException(409, "Yalnızca silinen komşuluk kayıtları geri yüklenebilir")
    deleted_targets = [target for target in targets if target.auto_add_excluded]
    for target in deleted_targets:
        # Clear related tombstones too: any remaining protocol duplicate can
        # suppress this restored observation on the next scan. Keep duplicates
        # historical unless the user explicitly selected them for restoration.
        pending = [target]
        unblocked = {target.id}
        while pending:
            current = pending.pop()
            for row in links:
                if (
                    row.device_id == target.device_id
                    and row.auto_add_excluded
                    and row.id not in unblocked
                    and (matches(current, observation(row), db) or matches(row, observation(current), db))
                ):
                    unblocked.add(row.id)
                    pending.append(row)
        for row in links:
            if row.id in unblocked:
                row.auto_add_excluded = False
        target.is_current = True
        audit(db, user, "restore_link", "links", target.id, "Komşuluk geri yüklendi; keşif engeli kaldırıldı")
        db.add(
            m.Event(
                device_id=target.device_id,
                kind="link_restored",
                message=f"{devices[target.device_id].name}: komşuluk geri yüklendi",
                details={"link_id": target.id, "unblocked_ids": sorted(unblocked)},
            )
        )
    # Restoring is a user action, not a new device observation: retain last_seen_at.
    db.commit()
    svc.publish()
    return {"updated": len(targets)}
