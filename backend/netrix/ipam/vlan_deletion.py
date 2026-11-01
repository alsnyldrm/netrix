"""Remove a VLAN and its IPAM data without modifying discovery or integrations."""

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import delete, select

from .. import models as m
from ..core import now
from ..identity.security import audit
from ..services import lock_vrf, publish


def selection(db, ids, *, lock=False):
    ids = sorted(set(ids))
    stmt = select(m.VLAN).where(m.VLAN.id.in_(ids)).order_by(m.VLAN.id)
    rows = list(db.scalars(stmt))
    if len(rows) != len(ids):
        raise HTTPException(404, "Seçilen VLAN artık yok; listeyi yenileyin")
    if lock:
        for vrf in sorted({r.vrf_id for r in rows if r.vrf_id}):
            lock_vrf(db, vrf)
        rows = list(db.scalars(stmt.with_for_update().execution_options(populate_existing=True)))
    addresses = list(db.scalars(select(m.IPAddress.id).where(m.IPAddress.vlan_id.in_(ids))))
    state = [{"id": r.id, "cidr": r.cidr, "updated_at": r.updated_at.isoformat()} for r in rows]
    token = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
    return rows, addresses, token


def preview(db, ids):
    rows, addresses, token = selection(db, ids)
    return {
        "vlans": [{"id": r.id, "name": r.name, "cidr": r.cidr} for r in rows],
        "address_count": len(addresses),
        "confirmation": token,
    }


def remove(db, ids, user, confirmation=None):
    if user.role != "admin":
        raise HTTPException(403, "Silme için yönetici yetkisi gerekli")
    rows, addresses, token = selection(db, ids, lock=True)
    if confirmation is not None and token != confirmation:
        raise HTTPException(409, "VLAN değişti; silme önizlemesini yenileyin")
    for job in db.scalars(
        select(m.Job)
        .where(
            m.Job.target_id.in_(ids),
            m.Job.kind.in_(("ipam_ping", "ipam_discover")),
            m.Job.active_key.is_not(None),
        )
        .with_for_update()
    ):
        job.cancel_requested = True
        if job.status == "queued":
            job.status, job.active_key, job.finished_at = "cancelled", None, now()
    db.execute(delete(m.IPAddress).where(m.IPAddress.vlan_id.in_(ids)))
    for row in rows:
        audit(db, user, "delete", "vlans", row.id, "VLAN ve bağlı IPAM kayıtları silindi")
        db.delete(row)
    db.commit()
    publish()
    return {"affected": len(rows), "deleted_addresses": len(addresses)}
