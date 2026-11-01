"""Room and cabinet removal; preserve inventory, IPs and discovery evidence."""

from fastapi import HTTPException
from sqlalchemy import delete, select, update

from .. import models as m
from ..identity.security import audit
from ..services import publish


def remove(db, ids, user, *, rooms=False):
    ids = sorted(set(ids))
    if rooms:
        rows = list(
            db.scalars(select(m.Site).where(m.Site.id.in_(ids)).order_by(m.Site.id).with_for_update())
        )
        if len(rows) != len(ids) or any(not r.parent_id for r in rows):
            raise HTTPException(422, "Yalnızca mevcut odalar seçilebilir")
        cabinets = list(
            db.scalars(
                select(m.Cabinet)
                .where(m.Cabinet.sub_site_id.in_(ids))
                .order_by(m.Cabinet.id)
                .with_for_update()
            )
        )
    else:
        rows = list(
            db.scalars(
                select(m.Cabinet).where(m.Cabinet.id.in_(ids)).order_by(m.Cabinet.id).with_for_update()
            )
        )
        if len(rows) != len(ids):
            raise HTTPException(404, "Kabinet bulunamadı")
        cabinets = rows
    cabinet_ids = [c.id for c in cabinets]
    panels = select(m.PatchPanel.id).where(m.PatchPanel.cabinet_id.in_(cabinet_ids))
    db.execute(delete(m.PatchPort).where(m.PatchPort.panel_id.in_(panels)))
    for model in (m.PatchPanel, m.RackAccessory, m.RackPlacement):
        db.execute(delete(model).where(model.cabinet_id.in_(cabinet_ids)))
    db.execute(delete(m.Cabinet).where(m.Cabinet.id.in_(cabinet_ids)))
    if rooms:
        db.execute(update(m.IPAddress).where(m.IPAddress.sub_site_id.in_(ids)).values(sub_site_id=None))
        db.execute(delete(m.Site).where(m.Site.id.in_(ids)))
    for row in rows:
        audit(
            db,
            user,
            "delete",
            "rooms" if rooms else "cabinets",
            row.id,
            f"{row.name}: oda/kabinet yerleşimleri kaldırıldı; cihazlar korundu",
        )
    db.commit()
    publish()
    return {"deleted": len(ids), "cabinets": len(cabinet_ids)}
