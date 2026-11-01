"""Shared institution/location hierarchy and cabinet placement rules."""

import re

from fastapi import HTTPException
from sqlalchemy import or_, select

from .. import models as m


def validate_location_relations(db, name, data, row_id=None):
    from ..services import get

    if data.get("site_id"):
        site = get(db, m.Site, data["site_id"])
        if site.parent_id:
            raise HTTPException(
                422, "Lokasyon alanında ana lokasyon seçin; alt lokasyon bu alanda kullanılamaz"
            )

    if name == "sites":
        institution = db.scalar(
            select(m.Institution).where(m.Institution.id == data["institution_id"]).with_for_update()
        )
        if not institution:
            raise HTTPException(422, "Kurum seçin")
        institution.lock_version += 1
        db.flush()
        parent = get(db, m.Site, data["parent_id"]) if data.get("parent_id") else None
        if parent and (parent.parent_id or parent.id == row_id or parent.institution_id != institution.id):
            raise HTTPException(422, "Alt lokasyon aynı kurumdaki bir ana lokasyona bağlı olmalı")
        children = db.scalars(select(m.Site).where(m.Site.parent_id == row_id)).all() if row_id else []
        if children and (parent or any(c.institution_id != institution.id for c in children)):
            raise HTTPException(
                409, "Alt lokasyonları bulunan kaydın hiyerarşisini değiştirmeden önce alt kayıtları taşıyın"
            )
        if row_id:
            existing = get(db, m.Site, row_id)
            if parent and not existing.parent_id:
                for model in (m.Device, m.Scope, m.VLAN):
                    if db.scalar(select(model.id).where(model.site_id == row_id).limit(1)):
                        raise HTTPException(409, "Kullanılan ana lokasyon alt lokasyona dönüştürülemez")
            if (parent.id if parent else None, institution.id) != (
                existing.parent_id,
                existing.institution_id,
            ) and db.scalar(
                select(m.IPAddress.id)
                .where(or_(m.IPAddress.site_id == row_id, m.IPAddress.sub_site_id == row_id))
                .limit(1)
            ):
                raise HTTPException(409, "Önce bu lokasyonu kullanan IP adreslerini taşıyın")
            if parent and db.scalar(select(m.Cabinet.id).where(m.Cabinet.site_id == row_id).limit(1)):
                raise HTTPException(409, "Kabinetlerin ana lokasyonu alt lokasyona dönüştürülemez")
            if data.get("parent_id") != existing.parent_id and db.scalar(
                select(m.Cabinet.id).where(m.Cabinet.sub_site_id == row_id).limit(1)
            ):
                raise HTTPException(409, "Önce bu alt lokasyona bağlı kabinetleri taşıyın")
            if institution.id != existing.institution_id and db.scalar(
                select(m.VLAN.id)
                .where(
                    m.VLAN.site_id == row_id,
                    m.VLAN.institution_id.is_not(None),
                    m.VLAN.institution_id != institution.id,
                )
                .limit(1)
            ):
                raise HTTPException(409, "Önce bu lokasyonu kullanan ağ bloklarının kurumunu güncelleyin")
        if row_id:
            row = get(db, m.Site, row_id)
            # Existing codes are stable; automatic allocation applies only on create.
            data["code"] = data["code"] or row.code
        elif parent or not data["code"]:
            codes = set(db.scalars(select(m.Site.code)))
            match = re.fullmatch(r"(.+)-(\d{6})", parent.code) if parent else None
            if parent and match:
                stem, start = match[1], int(match[2]) * 10 + 1
            else:
                stem, start = institution.code, 11 if parent else 1
            for number in range(start, 1000000):
                candidate = f"{stem}-{number:06d}"
                if candidate not in codes:
                    data["code"] = candidate
                    break
            else:
                raise HTTPException(409, "Bu lokasyon için kullanılabilir kod kalmadı")
    if name == "addresses":
        institution = get(db, m.Institution, data["institution_id"]) if data.get("institution_id") else None
        site = get(db, m.Site, data["site_id"]) if data.get("site_id") else None
        sub = get(db, m.Site, data["sub_site_id"]) if data.get("sub_site_id") else None
        if site and (not institution or site.parent_id or site.institution_id != institution.id):
            raise HTTPException(422, "Lokasyon seçilen kurumun ana lokasyonu olmalı")
        if sub and (not site or sub.parent_id != site.id or sub.institution_id != institution.id):
            raise HTTPException(422, "Alt lokasyon seçilen lokasyona ait olmalı")
        if institution:
            data["location"] = sub.name if sub else site.name if site else ""
    if name == "vlans":
        site = get(db, m.Site, data["site_id"]) if data.get("site_id") else None
        if data.get("institution_id"):
            get(db, m.Institution, data["institution_id"])
            if site and site.institution_id != data["institution_id"]:
                raise HTTPException(422, "Lokasyon seçilen kuruma ait değil")
        elif site:
            data["institution_id"] = site.institution_id
    if name == "cabinets":
        site = get(db, m.Site, data["site_id"]) if data.get("site_id") else None
        if not site or site.parent_id:
            raise HTTPException(422, "Kabinet için ana lokasyon seçin")
        if data.get("sub_site_id"):
            sub = get(db, m.Site, data["sub_site_id"])
            if sub.parent_id != site.id:
                raise HTTPException(422, "Alt lokasyon seçilen lokasyona ait değil")
        if row_id:
            cabinet = db.scalar(select(m.Cabinet).where(m.Cabinet.id == row_id).with_for_update())
            cabinet.lock_version += 1
            db.flush()
            for model in (m.RackPlacement, m.RackAccessory):
                if db.scalar(
                    select(model.id)
                    .where(model.cabinet_id == row_id, model.start_unit + model.units - 1 > data["units"])
                    .limit(1)
                ):
                    raise HTTPException(409, "Kabinet kapasitesi mevcut yerleşimlerin altına indirilemez")
