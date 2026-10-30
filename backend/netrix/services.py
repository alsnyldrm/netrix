import ipaddress
import json
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, inspect, or_, select

from . import models as m
from . import schemas as s
from .configuration.validation import BackupError, require_ssh_backup
from .core import now, redis_client
from .discovery.neighbor_labels import neighbor_label
from .identity.security import audit, encrypt

RESOURCES = {
    "backup-groups": (m.BackupGroup, s.BackupGroupInput),
    "sites": (m.Site, s.SiteInput),
    "device-types": (m.DeviceType, s.DeviceTypeInput),
    "vrfs": (m.VRF, s.VRFInput),
    "vlans": (m.VLAN, s.VLANInput),
    "devices": (m.Device, s.DeviceInput),
    "prefixes": (m.Prefix, s.PrefixInput),
    "addresses": (m.IPAddress, s.IPInput),
    "scopes": (m.Scope, s.ScopeInput),
    "credentials": (m.Credential, s.CredentialInput),
    "rules": (m.AlertRule, s.RuleInput),
    "interfaces": (m.Interface, None),
    "jobs": (m.Job, None),
    "observations": (m.Observation, None),
    "links": (m.Link, None),
    "snapshots": (m.Snapshot, None),
    "alerts": (m.Alert, None),
    "events": (m.Event, None),
    "audit": (m.Audit, None),
    "users": (m.User, s.UserInput),
}
HIDDEN = {"password_hash", "encrypted_secret", "encrypted_content", "active_key"}
SNMP_PROTOCOLS = ("snmpv3", "snmpv2c")
CONNECTION_TESTS = {"test_snmp": "snmpv3", "test_snmpv2c": "snmpv2c", "test_ssh": "ssh", "test_api": "rest"}
IDENTITY_CONNECTION_FIELDS = (
    "management_ip",
    "vrf_id",
    "adapter",
    "snmp_credential_id",
    "config_credential_id",
    "snmp_port",
    "config_port",
    "ssh_trust_host_key",
    "identity_path",
)


def serialize(obj):
    result = {}
    for col in inspect(obj).mapper.column_attrs:
        if col.key in HIDDEN:
            continue
        value = getattr(obj, col.key)
        if isinstance(obj, m.Link) and col.key in ("remote_name", "remote_port", "interface_name"):
            value = neighbor_label(value)
        if isinstance(obj, m.Job) and obj.kind == "compare" and col.key == "result":
            value = {k: v for k, v in value.items() if k != "diff"}
        if isinstance(value, datetime):
            value = value.isoformat()
        if isinstance(value, Decimal):
            value = int(value)
        result[col.key] = value
    if isinstance(obj, m.Device):
        result["kind_name"] = obj.device_type.name if obj.device_type else obj.kind
    return result


def get(db, model, id):
    row = db.get(model, id)
    if not row:
        raise HTTPException(404, "Kayıt bulunamadı")
    return row


def require_ref(db, model, id):
    return get(db, model, id) if id else None


def lock_vrf(db, vrf_id):
    row = db.scalar(select(m.VRF).where(m.VRF.id == vrf_id).with_for_update())
    if not row:
        raise HTTPException(422, "VRF bulunamadı")
    # Galera row locks are local to a node. A real version write ensures that
    # concurrent mutations on different nodes conflict during certification.
    row.lock_version += 1
    db.flush()
    return row


def validate_relations(db, name, data, row_id=None, *, lock=True):
    if "vrf_id" in data:
        if lock:
            lock_vrf(db, data["vrf_id"])
        else:
            get(db, m.VRF, data["vrf_id"])
    if data.get("site_id"):
        require_ref(db, m.Site, data["site_id"])
    if name == "devices":
        if not db.scalar(select(m.DeviceType.id).where(m.DeviceType.code == data["kind"])):
            raise HTTPException(422, "Cihaz türü bulunamadı; Cihaz Türü menüsündeki kayıtlı bir türü seçin")
        require_ref(db, m.BackupGroup, data.get("backup_group_id"))
        for key, protocols in [
            ("snmp_credential_id", SNMP_PROTOCOLS),
            ("config_credential_id", ["rest"] if data["adapter"] == "rest" else ["ssh"]),
        ]:
            if data.get(key) and get(db, m.Credential, data[key]).protocol not in protocols:
                raise HTTPException(422, "Erişim profilinin protokolü adaptörle uyumlu değil")
        if data["monitoring_enabled"] and not data.get("snmp_credential_id"):
            raise HTTPException(422, "İzleme için SNMPv3 veya SNMPv2c profili gerekli")
        if data["backup_interval"] and not data.get("config_credential_id"):
            raise HTTPException(422, "Yedekleme için erişim profili gerekli")
        if data["backup_interval"] and data["adapter"] == "rest":
            raise HTTPException(422, BackupError.MESSAGES["ssh_required"])
        if row_id:
            device = get(db, m.Device, row_id)
            if data["vrf_id"] != device.vrf_id and db.scalar(
                select(m.Interface.id).where(m.Interface.device_id == row_id).limit(1)
            ):
                raise HTTPException(409, "Arayüzleri bulunan cihazın VRF bilgisi değiştirilemez")
    if name == "prefixes":
        require_ref(db, m.VLAN, data.get("vlan_id"))
        network = ipaddress.ip_network(data["cidr"])
        for prefix in db.scalars(
            select(m.Prefix).where(m.Prefix.vrf_id == data["vrf_id"], m.Prefix.id != (row_id or ""))
        ):
            other = ipaddress.ip_network(prefix.cidr)
            if (
                other.version == network.version
                and other.overlaps(network)
                and not (other.subnet_of(network) or network.subnet_of(other))
            ):
                raise HTTPException(409, "Ağ blokları çakışıyor")
        if row_id:
            for address in db.scalars(select(m.IPAddress).where(m.IPAddress.prefix_id == row_id)):
                if data["vrf_id"] != address.vrf_id or ipaddress.ip_address(address.address) not in network:
                    raise HTTPException(409, "Mevcut IP atamaları yeni prefix ile uyumsuz")
    if name == "addresses":
        prefix = get(db, m.Prefix, data["prefix_id"])
        address, network = ipaddress.ip_address(data["address"]), ipaddress.ip_network(prefix.cidr)
        if prefix.vrf_id != data["vrf_id"] or address not in network:
            raise HTTPException(422, "Adres seçilen prefix veya VRF içinde değil")
        if (
            network.version == 4
            and network.prefixlen < 31
            and address in (network.network_address, network.broadcast_address)
        ):
            raise HTTPException(422, "Ağ/yayın adresi atanamaz")
        if data.get("interface_id"):
            interface = get(db, m.Interface, data["interface_id"])
            device = get(db, m.Device, interface.device_id)
            if device.vrf_id != data["vrf_id"] or (prefix.site_id and prefix.site_id != device.site_id):
                raise HTTPException(422, "Arayüzün VRF veya site bilgisi prefix ile uyumsuz")
    if name == "scopes" and get(db, m.Credential, data["credential_id"]).protocol not in SNMP_PROTOCOLS:
        raise HTTPException(422, "Keşif SNMPv3 veya SNMPv2c profili gerektirir")
    if name == "rules" and row_id and not data["enabled"]:
        for alert in db.scalars(
            select(m.Alert).where(m.Alert.rule_id == row_id, m.Alert.active_key.is_not(None))
        ):
            alert.state, alert.active_key, alert.resolved_at = "resolved", None, now()


def save_resource(db, name, payload, user, row_id=None, *, commit=True):
    if name not in RESOURCES or RESOURCES[name][1] is None:
        raise HTTPException(405, "Bu kaynak salt okunur")
    model, schema = RESOURCES[name]
    if name in ("credentials", "users") and user.role != "admin":
        raise HTTPException(403, "Yönetici yetkisi gerekli")
    if name == "users" and row_id:
        raise HTTPException(405, "Kullanıcı parolası için parola değiştirme işlemini kullanın")
    value = schema.model_validate(payload)
    data = value.model_dump()
    row = get(db, model, row_id) if row_id else model()
    identify_changed = name == "devices" and (
        not row_id
        or any(
            getattr(row, key) != data[key]
            for key in (*IDENTITY_CONNECTION_FIELDS, "vendor", "model", "kind", "lifecycle_status")
        )
    )
    validate_relations(db, name, data, row_id)
    if name == "device-types":
        if db.scalar(
            select(m.DeviceType.id).where(
                func.lower(m.DeviceType.name) == data["name"].lower(), m.DeviceType.id != (row_id or "")
            )
        ):
            raise HTTPException(409, "Bu cihaz türü adı zaten var")
        if not row_id:
            data["code"] = uuid4().hex[:20]
    if name == "credentials":
        if row_id and row.protocol != data["protocol"]:
            raise HTTPException(409, "Profil protokolü değiştirilemez; yeni bir erişim profili oluşturun")
        data["encrypted_secret"] = encrypt(json.dumps(data.pop("secret")))
    if name == "users":
        from .identity.security import hasher

        data["password_hash"] = hasher.hash(data.pop("password"))
    if name == "addresses" and row_id:
        changes = {
            key: {"previous": getattr(row, key), "current": data[key]}
            for key in ("address", "hostname", "status", "interface_id")
            if getattr(row, key) != data[key]
        }
        if changes:
            db.add(
                m.Event(
                    kind="ip_assignment_change",
                    message="IP ataması güncellendi",
                    details={"address_id": row.id, "changes": changes},
                )
            )
    if name == "devices" and row_id and row.management_ip != data["management_ip"]:
        db.add(
            m.Event(
                device_id=row.id,
                kind="management_ip_change",
                message=f"{row.name}: yönetim adresi değişti",
                details={"previous": row.management_ip, "current": data["management_ip"]},
            )
        )
    for key, val in data.items():
        setattr(row, key, val)
    db.add(row)
    db.flush()
    if name == "devices":
        db.expire(row, ["device_type"])
    audit(
        db,
        user,
        "update" if row_id else "create",
        name,
        row.id,
        f"{name}: kayıt güncellendi" if row_id else f"{name}: kayıt oluşturuldu",
    )
    identification = None
    if identify_changed:
        try:
            job = enqueue(db, "identify", row.id, user, commit=False)
            identification = {
                "status": "queued",
                "job_id": job.id,
                "message": "Cihaz bilgileri arka planda sorgulanıyor. Görev merkezinden takip edebilirsiniz.",
            }
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            identification = {"status": "skipped", "message": str(exc.detail) + ". Manuel bilgiler korundu."}
    initial_backup = None
    if name == "devices" and not row_id:
        # The inventory creation is the trigger, including CSV/XLSX imports.
        # Keep the durable job in the same transaction; no network in the API.
        try:
            job = enqueue(db, "backup", row.id, user, commit=False)
            initial_backup = {"status": "queued", "job_id": job.id}
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            initial_backup = {"status": "skipped", "message": str(exc.detail)}
    if commit:
        db.commit()
        publish()
    result = serialize(row)
    if identification:
        result["identification"] = identification
    if initial_backup:
        result["backup"] = initial_backup
    return result


def list_resource(db, name, limit=100, offset=0, q="", device_id=None):
    if name not in RESOURCES:
        raise HTTPException(404, "Kaynak bulunamadı")
    model = RESOURCES[name][0]
    stmt = select(model)
    if name == "links":
        stmt = stmt.where(m.Link.is_current.is_(True))
    if name == "devices":
        stmt = stmt.where(m.Device.archived.is_(False))
    if name == "interfaces":
        stmt = stmt.join(m.Device, m.Interface.device_id == m.Device.id).where(
            m.Interface.is_managed.is_(True), m.Interface.is_deleted.is_(False), m.Device.archived.is_(False)
        )
    if q:
        fields = [
            getattr(model, key)
            for key in (
                "name",
                "management_ip",
                "cidr",
                "address",
                "email",
                "message",
                "kind",
                "status",
                "summary",
            )
            if hasattr(model, key)
        ]
        if fields:
            stmt = stmt.where(
                or_(*[field.ilike("%" + q.replace("%", r"\%").replace("_", r"\_") + "%") for field in fields])
            )
    if device_id and hasattr(model, "device_id"):
        stmt = stmt.where(model.device_id == device_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(model.created_at.desc(), model.id).offset(offset).limit(limit)).all()
    items = [serialize(row) for row in rows]
    if name == "prefixes":
        for item in items:
            net = ipaddress.ip_network(item["cidr"])
            capacity = net.num_addresses - (2 if net.version == 4 and net.prefixlen < 31 else 0)
            used = db.scalar(
                select(func.count())
                .select_from(m.IPAddress)
                .where(m.IPAddress.prefix_id == item["id"], m.IPAddress.status != "deprecated")
            )
            item.update(capacity=str(capacity), used=used, utilization=round(used * 100 / capacity, 2))
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def delete_resource(db, name, id, user):
    if name not in RESOURCES or RESOURCES[name][1] is None:
        raise HTTPException(405, "Bu kaynak salt okunur")
    if user.role != "admin":
        raise HTTPException(403, "Silme için yönetici yetkisi gerekli")
    model = RESOURCES[name][0]
    row = get(db, model, id)
    if name in ("users", "vrfs"):
        raise HTTPException(409, "Kimlik ve VRF kayıtları geçmişi korumak için silinemez")
    if name == "device-types":
        if row.code == "other":
            raise HTTPException(409, "Varsayılan cihaz türü silinemez; adını düzenleyebilirsiniz")
        if db.scalar(select(m.Device.id).where(m.Device.kind == row.code).limit(1)):
            raise HTTPException(
                409, "Bu türü kullanan cihazlar var (arşiv dahil). Önce cihazlara başka bir tür atayın"
            )
    if name == "devices":
        row.archived = True
        row.lifecycle_status = "retired"
        row.monitoring_enabled, row.backup_interval = False, 0
    else:
        db.delete(row)
    audit(
        db, user, "archive" if name == "devices" else "delete", name, id, f"{name}: kayıt arşivlendi/silindi"
    )
    db.commit()
    publish()


def in_scope(address, scope):
    ip = ipaddress.ip_address(address)
    network = ipaddress.ip_network(scope.cidr)
    return (
        scope.enabled
        and ip in network
        and not any(ip in ipaddress.ip_network(cidr) for cidr in scope.exclusions)
    )


def authorized_device(db, device):
    if device.archived:
        raise ValueError("Cihaz arşivlenmiş; bağlantı testi ve cihaz sorguları çalıştırılamaz.")
    if device.lifecycle_status in ("retired", "planned", "maintenance"):
        raise ValueError("Cihaz aktif durumda değil. Cihaz ayarlarında yaşam döngüsünü Aktif yapıp kaydedin.")
    scopes = db.scalars(
        select(m.Scope).where(m.Scope.vrf_id == device.vrf_id, m.Scope.enabled.is_(True))
    ).all()
    if not any(in_scope(device.management_ip, scope) for scope in scopes):
        address = ipaddress.ip_address(device.management_ip)
        raise ValueError(
            f"{address} için cihazın VRF'inde etkin, adresi hariç tutmayan bir keşif kapsamı yok. "
            f"Ağ keşfi menüsünde bu cihaz için {address}/{address.max_prefixlen} kapsamı "
            "veya yetkili ağınızı tanımlayıp etkinleştirin. Henüz bağlantı denenmedi."
        )


def connection_profile(db, device, protocol):
    profile_id = device.snmp_credential_id if protocol in SNMP_PROTOCOLS else device.config_credential_id
    profile = db.get(m.Credential, profile_id) if profile_id else None
    if not profile or profile.protocol != protocol:
        return None
    if protocol == "rest" and device.adapter != "rest":
        return None
    if protocol == "ssh" and device.adapter == "rest":
        return None
    return profile


def connection_test_options(db, device):
    options = []
    for protocol, label in (("snmpv3", "SNMPv3"), ("snmpv2c", "SNMPv2c"), ("ssh", "SSH"), ("rest", "API")):
        profile = connection_profile(db, device, protocol)
        options.append(
            {
                "protocol": protocol,
                "label": label,
                "enabled": profile is not None,
                "profile_name": profile.name if profile else None,
                "port": device.snmp_port if protocol in SNMP_PROTOCOLS else device.config_port,
                "path": device.identity_path if protocol == "rest" else None,
            }
        )
    reason = ""
    try:
        authorized_device(db, device)
    except ValueError as exc:
        reason = str(exc)
    return {
        "device_id": device.id,
        "target": device.management_ip,
        "protocols": options,
        "can_test": not reason and any(option["enabled"] for option in options),
        "reason": reason
        or ("" if any(option["enabled"] for option in options) else "Önce cihaza bir erişim profili atayın."),
    }


def backup_profile(db, device):
    profile = db.get(m.Credential, device.config_credential_id) if device.config_credential_id else None
    return require_ssh_backup(device, profile)


def enqueue(db, kind, target_id, user=None, *, commit=True):
    if kind not in ("discovery", "backup", "compare", "monitor", "identify", *CONNECTION_TESTS):
        raise HTTPException(422, "Geçersiz görev türü")
    if kind == "discovery":
        target = get(db, m.Scope, target_id)
        if not target.enabled:
            raise HTTPException(422, "Keşif kapsamı devre dışı")
    else:
        target = get(db, m.Device, target_id)
        try:
            authorized_device(db, target)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if kind in CONNECTION_TESTS:
            if not connection_profile(db, target, CONNECTION_TESTS[kind]):
                raise HTTPException(422, "Seçilen protokol için cihaza uyumlu bir erişim profili atanmamış")
        elif kind in ("backup", "compare"):
            try:
                backup_profile(db, target)
            except BackupError as exc:
                raise HTTPException(422, str(exc)) from None
        else:
            credential_id = (
                (target.snmp_credential_id or target.config_credential_id)
                if kind == "identify"
                else target.snmp_credential_id
            )
            if not credential_id:
                raise HTTPException(422, "Görev için erişim profili atanmalı")
    key = f"{kind}:{target_id}"
    # Serialize submitters on the target, including scheduled and API requests.
    db.scalar(select(type(target)).where(type(target).id == target_id).with_for_update())
    existing = db.scalar(select(m.Job).where(m.Job.active_key == key))
    if existing:
        return existing
    job = m.Job(kind=kind, target_id=target_id, active_key=key, requested_by=user.id if user else None)
    db.add(job)
    db.flush()
    audit(db, user, "enqueue", "jobs", job.id, f"{kind} görevi kuyruğa alındı")
    if commit:
        db.commit()
        publish()
    return job


def publish():
    # DB is the durable outbox/queue; Redis is a wake-up hint, never the source of truth.
    try:
        redis_client().publish("netrix:events", "refresh")
    except Exception:
        pass
