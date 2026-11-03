"""Repository comparisons use inventory metadata only; never connect to a device."""

from collections import Counter

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select

from .. import models as m
from .service import Input, compatible
from .versions import compare, release


def statuses(db, where):
    images = list(db.scalars(select(m.FirmwareImage).where(m.FirmwareImage.status == "ready")))
    rows = db.execute(
        select(m.Device.id, m.Device.adapter, m.Device.model, m.Device.software_version).where(*where)
    )
    # Cache identical model/revision combinations within this request, not across
    # uploads or inventory changes. Query count does not grow with device count.
    cache, result = {}, {}
    for row in rows:
        key = (row.adapter, row.model, row.software_version)
        if key not in cache:
            supported = [image for image in images if compatible(image, row)]
            comparable = [
                image for image in supported if compare(row.software_version, image.version) is not None
            ]
            latest = max(comparable, key=lambda image: (release(image.version)[1], image.id), default=None)
            status = "unknown" if supported else "no_image"
            if latest:
                status = "outdated" if compare(row.software_version, latest.version) < 0 else "current"
            cache[key] = {
                "update_status": status,
                "latest_image_id": latest.id if latest else None,
                "latest_version": latest.version if latest else None,
            }
        result[row.id] = cache[key]
    return result


def counts(db, where):
    values = Counter(row["update_status"] for row in statuses(db, where).values())
    return {key: values[key] for key in ("current", "outdated", "unknown", "no_image")}


class SelectionInput(Input):
    device_ids: list[str] = Field(default_factory=list, max_length=1000)
    group_ids: list[str] = Field(default_factory=list, max_length=50)
    include_ungrouped: bool = False


def outdated_members(db, where):
    updates = statuses(db, where)
    ids = [id for id, row in updates.items() if row["update_status"] == "outdated"]
    members = db.execute(
        select(m.Device.id, m.FirmwareGroup.id.label("group_id"), m.FirmwareGroup.name.label("group_name"))
        .outerjoin(m.FirmwareMember, m.FirmwareMember.device_id == m.Device.id)
        .outerjoin(m.FirmwareGroup, m.FirmwareGroup.id == m.FirmwareMember.group_id)
        .where(m.Device.id.in_(ids))
        .order_by(m.FirmwareGroup.name, m.Device.name, m.Device.id)
    )
    return [(row, updates[row.id]) for row in members]


def outdated_groups(db, where, *, offset=0, limit=30):
    groups = {}
    for row, update in outdated_members(db, where):
        group = groups.setdefault(
            row.group_id,
            {
                "id": row.group_id or "ungrouped",
                "group_id": row.group_id,
                "name": row.group_name or "Gruba atanmamış cihazlar",
                "device_count": 0,
                "versions": set(),
            },
        )
        group["device_count"] += 1
        group["versions"].add(update["latest_version"])
    return {
        "items": [
            {**g, "versions": sorted(g["versions"])} for g in list(groups.values())[offset : offset + limit]
        ],
        "total": len(groups),
    }


def prepare_selection(db, payload, where):
    if not payload.device_ids and not payload.group_ids and not payload.include_ungrouped:
        raise HTTPException(422, "Güncellenecek cihaz veya grup seçin")
    selected, found, steps = set(payload.device_ids), set(), {}
    if selected and not payload.group_ids and not payload.include_ungrouped:
        where = [*where, m.Device.id.in_(selected)]
    for row, update in outdated_members(db, where):
        if not (
            row.id in selected
            or row.group_id in payload.group_ids
            or payload.include_ungrouped
            and row.group_id is None
        ):
            continue
        found.add(row.id)
        if len(found) > 1000:
            raise HTTPException(422, "Bir plan en fazla 1000 cihaz içerebilir; seçimi daraltın")
        key = (row.group_id, update["latest_image_id"])
        step = steps.setdefault(
            key, {"group_id": row.group_id, "image_id": update["latest_image_id"], "device_ids": []}
        )
        step["device_ids"].append(row.id)
    if selected - found:
        raise HTTPException(
            409, "Seçimde güncel, karşılaştırılamayan veya artık bulunmayan cihaz var; listeyi yenileyin"
        )
    missing = set(payload.group_ids) - {key[0] for key in steps}
    if missing or not steps:
        raise HTTPException(409, "Seçilen grupta güncellenecek cihaz kalmadı; listeyi yenileyin")
    if len(steps) > 50:
        raise HTTPException(422, "Seçim 50 aşamayı aşıyor; daha az grup/model seçin")
    return {"steps": list(steps.values()), "target_total": len(found)}
