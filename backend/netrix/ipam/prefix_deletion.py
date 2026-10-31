"""Atomic prefix removal with an explicit preview of dependent IPAM records."""

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import delete, or_, select

from .. import models as m
from ..identity.security import audit
from ..services import lock_vrf, publish


def selection(db, ids, *, lock=False):
    ids = sorted(set(ids))
    rows = list(db.scalars(select(m.Prefix).where(m.Prefix.id.in_(ids)).order_by(m.Prefix.id)))
    if len(rows) != len(ids):
        raise HTTPException(404, "Seçilen ağ bloklarından biri artık yok; listeyi yenileyin")
    if lock:
        for vrf in sorted({r.vrf_id for r in rows}):
            lock_vrf(db, vrf)
        rows = list(
            db.scalars(
                select(m.Prefix)
                .where(m.Prefix.id.in_(ids))
                .order_by(m.Prefix.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if len(rows) != len(ids):
            raise HTTPException(409, "Ağ blokları değişti; silme önizlemesini yenileyin")
    addresses = select(m.IPAddress.id).where(m.IPAddress.prefix_id.in_(ids)).order_by(m.IPAddress.id)
    address_ids = list(db.scalars(addresses.with_for_update() if lock else addresses))
    configs = select(m.Integration).order_by(m.Integration.id)
    integrations = [
        c
        for c in db.scalars(configs.with_for_update() if lock else configs)
        if set(ids).intersection(c.prefix_ids)
    ]
    state = {
        "prefixes": [{"id": r.id, "cidr": r.cidr} for r in rows],
        "address_ids": address_ids,
        "integrations": [
            {"id": c.id, "name": c.name, "prefix_ids": c.prefix_ids, "enabled": c.enabled}
            for c in integrations
        ],
    }
    token = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
    return rows, address_ids, integrations, token


def preview(db, ids):
    rows, addresses, configs, token = selection(db, ids)
    selected = {r.id for r in rows}
    return {
        "prefixes": [{"id": r.id, "cidr": r.cidr} for r in rows],
        "address_count": len(addresses),
        "integrations": [
            {"name": c.name, "will_disable": not (set(c.prefix_ids) - selected)} for c in configs
        ],
        "confirmation": token,
    }


def remove(db, ids, user, confirmation=None):
    if user.role != "admin":
        raise HTTPException(403, "Silme için yönetici yetkisi gerekli")
    rows, address_ids, configs, token = selection(db, ids, lock=True)
    if confirmation is not None and token != confirmation:
        raise HTTPException(
            409, "Silinecek kayıtlar değişti; pencereyi kapatıp silme önizlemesini yeniden açın"
        )
    selected = {r.id for r in rows}
    if db.scalar(
        select(m.Job.id)
        .where(
            m.Job.active_key.is_not(None),
            or_(
                m.Job.target_id.in_(selected | {c.id for c in configs}),
                m.Job.target_id.in_(select(m.IPAddress.id).where(m.IPAddress.prefix_id.in_(selected))),
            ),
        )
        .limit(1)
    ):
        raise HTTPException(
            409, "Önce seçilen bloklar, IP adresleri veya bağlı entegrasyonlar için çalışan işleri durdurun"
        )
    for config in configs:
        config.prefix_ids = [id for id in config.prefix_ids if id not in selected]
        if not config.prefix_ids:
            config.enabled = False
        audit(
            db,
            user,
            "prefix_unlink",
            "integrations",
            config.id,
            f"Silinen ağ blokları entegrasyondan çıkarıldı: {config.name}",
        )
    # IP observations and traffic cascade via existing database foreign keys.
    db.execute(delete(m.IPAddress).where(m.IPAddress.prefix_id.in_(selected)))
    for row in rows:
        audit(db, user, "delete", "prefixes", row.id, f"Ağ bloğu ve bağlı IPAM kayıtları silindi: {row.cidr}")
        db.delete(row)
    db.commit()
    publish()
    return {"affected": len(rows), "deleted_addresses": len(address_ids)}
