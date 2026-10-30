"""Inventory query and atomic management operations; never opens device connections."""

import json
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import Integer, String, and_, case, cast, func, inspect, or_, select
from sqlalchemy.orm import aliased

from .. import models as m
from .. import schemas as s
from .. import services as svc
from ..identity.security import audit

LABELS = {
    "name": "Ad",
    "management_ip": "Yönetim adresi",
    "vrf_id": "VRF kimliği",
    "site_id": "Lokasyon kimliği",
    "vendor": "Üretici",
    "model": "Model",
    "kind": "Cihaz türü",
    "lifecycle_status": "Yaşam döngüsü",
    "reachability": "Erişim",
    "adapter": "Adaptör",
    "snmp_credential_id": "SNMP profil kimliği",
    "config_credential_id": "SSH / API profil kimliği",
    "snmp_port": "SNMP portu",
    "config_port": "SSH / HTTPS portu",
    "ssh_trust_host_key": "Anahtara güven",
    "config_path": "Konfigürasyon yolu",
    "identity_path": "Cihaz bilgisi yolu",
    "monitoring_enabled": "İzleme etkin",
    "monitor_interval": "İzleme aralığı",
    "backup_interval": "Yedekleme aralığı",
    "backup_retention": "Saklanacak yedek sayısı",
    "last_seen_at": "Son gözlem",
    "last_monitor_at": "Son izleme",
    "last_backup_at": "Son yedek",
    "created_at": "Oluşturulma",
    "updated_at": "Güncelleme",
    "id": "Kayıt kimliği",
    "device_id": "Cihaz kimliği",
    "if_index": "ifIndex",
    "mac_address": "MAC adresi",
    "speed_bps": "Kapasite (bps)",
    "oper_status": "Port durumu",
    "description": "Açıklama",
    "is_managed": "Uygulamaya ekli",
    "device_name": "Cihaz",
    "device_kind": "Cihaz türü",
    "site_name": "Lokasyon",
    "vrf_name": "VRF",
    "snmp_profile": "SNMP profili",
    "config_profile": "SSH / API profili",
    "backup_group_id": "Yedek grubu kimliği",
    "backup_group": "Yedek grubu",
    "fingerprint": "SHA-256",
    "size_bytes": "Boyut (byte)",
    "changed": "Değişiklik",
    "job_id": "Görev kimliği",
    "capacity": "Kapasite",
    "effective_backup_interval": "Uygulanan yedek aralığı",
    "effective_retention": "Uygulanan saklama sınırı",
}
TRANSLATIONS = {
    "switch": "Switch",
    "router": "Router",
    "firewall": "Firewall",
    "server": "Sunucu",
    "other": "Diğer",
    "active": "Aktif",
    "planned": "Planlandı",
    "maintenance": "Bakımda",
    "retired": "Emekli",
    "reachable": "Yanıt verdi",
    "unreachable": "Yanıt yok",
    "unknown": "Bilinmiyor",
    "up": "Açık",
    "down": "Kapalı",
}
BULK_FIELDS = {
    "vrf_id",
    "site_id",
    "vendor",
    "kind",
    "model",
    "lifecycle_status",
    "adapter",
    "snmp_credential_id",
    "config_credential_id",
    "ssh_trust_host_key",
    "monitoring_enabled",
    "monitor_interval",
    "backup_interval",
}


def query(
    db,
    resource,
    limit=25,
    offset=0,
    q="",
    filters="[]",
    device_id=None,
    candidates=False,
    group_by="",
    changed_only=False,
):
    models = {"devices": m.Device, "interfaces": m.Interface, "snapshots": m.Snapshot}
    if resource not in models:
        raise HTTPException(404, "Kaynak bulunamadı")
    model = models[resource]
    if group_by not in ("", "device_name", "backup_group") or (group_by and resource != "snapshots"):
        raise HTTPException(422, "Geçersiz gruplama")
    stmt = select(model)
    cols = {
        c.key: getattr(model, c.key)
        for c in inspect(model).column_attrs
        if c.key not in svc.HIDDEN | {"archived", "is_deleted"}
    }
    if resource != "devices":
        stmt = stmt.join(m.Device, model.device_id == m.Device.id)
        cols.update(
            device_name=m.Device.name, device_kind=m.Device.kind, management_ip=m.Device.management_ip
        )
        if device_id:
            stmt = stmt.where(model.device_id == device_id)
    if resource != "snapshots":
        stmt = stmt.where(m.Device.archived.is_(False))
    if resource == "interfaces" and not candidates:
        stmt = stmt.where(m.Interface.is_managed.is_(True), m.Interface.is_deleted.is_(False))
    stmt = stmt.outerjoin(m.Site, m.Device.site_id == m.Site.id).outerjoin(m.VRF, m.Device.vrf_id == m.VRF.id)
    stmt = stmt.outerjoin(m.BackupGroup, m.Device.backup_group_id == m.BackupGroup.id)
    cols.update(site_name=m.Site.name, vrf_name=m.VRF.name, backup_group=m.BackupGroup.name)
    if resource == "devices":
        snmp, config = aliased(m.Credential), aliased(m.Credential)
        stmt = stmt.outerjoin(snmp, m.Device.snmp_credential_id == snmp.id).outerjoin(
            config, m.Device.config_credential_id == config.id
        )
        cols.update(
            snmp_profile=snmp.name,
            config_profile=config.name,
            effective_backup_interval=case(
                (m.BackupGroup.id.is_not(None), m.BackupGroup.interval_seconds),
                else_=m.Device.backup_interval,
            ),
            effective_retention=case(
                (m.BackupGroup.id.is_not(None), m.BackupGroup.retention_count),
                else_=m.Device.backup_retention,
            ),
        )
    if resource == "interfaces":

        def capacity(divisor, unit):
            numeric = case(
                (
                    m.Interface.speed_bps % divisor == 0,
                    cast(cast(m.Interface.speed_bps / divisor, Integer), String),
                ),
                else_=cast(func.round(m.Interface.speed_bps / divisor, 2), String),
            )
            return numeric + unit

        cols["capacity"] = case(
            (m.Interface.speed_bps >= 1000000000, capacity(1000000000, " Gbps")),
            else_=capacity(1000000, " Mbps"),
        )

    def contains(col, value):
        return cast(col, String).ilike(
            "%" + value.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%", escape="!"
        )

    def field_contains(key, col, value):
        clauses = [contains(col, value)]
        if key in ("kind", "device_kind", "lifecycle_status", "reachability", "oper_status"):
            clauses.append(contains(case(TRANSLATIONS, value=col, else_=col), value))
        if key in ("monitoring_enabled", "ssh_trust_host_key", "is_managed"):
            clauses.append(contains(case((col.is_(True), "Etkin Evet"), else_="Kapalı Hayır"), value))
        if key == "changed":
            clauses.append(contains(case((col.is_(True), "Değişti"), else_="Değişmedi"), value))
        return or_(*clauses)

    if q:
        stmt = stmt.where(or_(*(field_contains(key, col, q) for key, col in cols.items())))
    try:
        raw = json.loads(filters)
        if not isinstance(raw, list) or len(raw) > 20:
            raise ValueError()
        parsed = [s.InventoryFilter.model_validate(v) for v in raw]
    except (ValueError, TypeError):
        raise HTTPException(422, "En fazla 20 geçerli filtre kullanılabilir") from None
    expression = None
    for f in parsed:
        if f.field not in cols:
            raise HTTPException(422, "Geçersiz filtre alanı")
        col = cols[f.field]
        value = f.value
        if f.op in ("gt", "lt"):
            try:
                value = Decimal(value)
                if not value.is_finite() or col.type.python_type not in (int, float, Decimal):
                    raise ValueError()
            except (ValueError, InvalidOperation, NotImplementedError):
                raise HTTPException(422, "Sayısal filtre için sayısal alan ve değer gerekli") from None
        if f.op in ("eq", "ne"):
            if f.field in ("kind", "device_kind", "lifecycle_status", "reachability", "oper_status"):
                value = next((k for k, v in TRANSLATIONS.items() if v.casefold() == value.casefold()), value)
            if f.field in ("monitoring_enabled", "ssh_trust_host_key", "changed", "is_managed"):
                converted = {
                    "true": True,
                    "false": False,
                    "etkin": True,
                    "kapalı": False,
                    "evet": True,
                    "hayır": False,
                    "değişti": True,
                    "değişmedi": False,
                }
                if value.casefold() not in converted:
                    raise HTTPException(422, "Mantıksal filtre değeri Etkin / Kapalı olmalı")
                value = converted[value.casefold()]
        clause = {
            "contains": lambda: field_contains(f.field, col, f.value),
            "eq": lambda: col == value,
            "ne": lambda: or_(col != value, col.is_(None)),
            "gt": lambda: col > value,
            "lt": lambda: col < value,
        }[f.op]()
        expression = (
            clause
            if expression is None
            else (and_(expression, clause) if f.join == "and" else or_(expression, clause))
        )
    if expression is not None:
        stmt = stmt.where(expression)
    if resource == "snapshots" and changed_only:
        stmt = stmt.where(m.Snapshot.changed.is_(True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    extras = {k: v for k, v in cols.items() if k not in inspect(model).column_attrs.keys()}
    stmt = stmt.add_columns(*[v.label(k) for k, v in extras.items()])
    result = db.execute(
        stmt.order_by(*([cols[group_by]] if group_by else []), model.created_at.desc(), model.id)
        .offset(offset)
        .limit(limit)
    ).all()
    items = [{**svc.serialize(row[0]), **dict(zip(extras, row[1:]))} for row in result]
    return {"items": items, "total": total, "columns": [{"key": k, "label": LABELS.get(k, k)} for k in cols]}


def select_interfaces(db, device_id, ids, user):
    svc.get(db, m.Device, device_id)
    db.scalar(select(m.Device).where(m.Device.id == device_id).with_for_update())
    ports = db.scalars(select(m.Interface).where(m.Interface.device_id == device_id).with_for_update()).all()
    selected = set(ids)
    if selected - {p.id for p in ports}:
        raise HTTPException(422, "Seçilen arayüzler bu cihaza ait olmalı")
    for port in ports:
        port.is_managed = port.id in selected
        if port.is_managed:
            port.is_deleted = False
    audit(db, user, "select_interfaces", "devices", device_id, f"{len(selected)} arayüz uygulamaya alındı")
    db.commit()
    svc.publish()
    return {"selected": len(selected)}


def bulk(db, resource, payload, user):
    if resource not in ("devices", "interfaces"):
        raise HTTPException(404, "Kaynak bulunamadı")
    if payload.action == "delete" and user.role != "admin":
        raise HTTPException(403, "Silme için yönetici yetkisi gerekli")
    ids = sorted(set(payload.ids))
    model = m.Device if resource == "devices" else m.Interface
    rows = db.scalars(select(model).where(model.id.in_(ids)).order_by(model.id).with_for_update()).all()
    if len(rows) != len(ids):
        raise HTTPException(404, "Seçilen kayıtlardan biri bulunamadı")
    if resource == "devices":
        if payload.action not in ("update", "delete"):
            raise HTTPException(422, "Geçersiz cihaz işlemi")
        if payload.action == "update":
            if not payload.changes or set(payload.changes) - BULK_FIELDS:
                raise HTTPException(422, "Toplu düzenlemede yalnızca izin verilen alanlar değiştirilebilir")
            for row in rows:
                if row.archived:
                    raise HTTPException(409, "Arşivlenmiş cihaz düzenlenemez")
                data = {key: getattr(row, key) for key in s.DeviceInput.model_fields}
                data.update(payload.changes)
                svc.save_resource(db, "devices", data, user, row.id, commit=False)
        else:
            for row in rows:
                row.archived, row.lifecycle_status, row.monitoring_enabled, row.backup_interval = (
                    True,
                    "retired",
                    False,
                    0,
                )
    else:
        if payload.action not in ("delete", "disable", "enable") or payload.changes:
            raise HTTPException(422, "Geçersiz arayüz işlemi")
        for row in rows:
            if payload.action == "delete":
                row.is_deleted, row.is_managed = True, False
            else:
                row.monitoring_enabled = payload.action == "enable"
    for row in rows:
        audit(db, user, "bulk_" + payload.action, resource, row.id, "Toplu envanter işlemi")
    db.commit()
    svc.publish()
    return {"updated": len(rows)}
