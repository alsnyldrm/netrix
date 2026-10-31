import ipaddress
import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import BigInteger, String, cast, delete, func, inspect, or_, select

from . import models as m
from . import schemas as s
from .configuration.validation import BackupError, require_ssh_backup
from .core import now, redis_client
from .discovery.neighbor_labels import neighbor_label
from .identity.security import audit, encrypt
from .ipam.schemas import DNSInput

RESOURCES = {
    "institutions": (m.Institution, s.InstitutionInput),
    "cabinets": (m.Cabinet, s.CabinetInput),
    "operating-systems": (m.OperatingSystem, s.OperatingSystemInput),
    "dns-servers": (m.DNSServer, DNSInput),
    "integrations": (m.Integration, None),
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
    if isinstance(obj, m.Link):
        from .discovery.link_edits import confidence, name_label, peer_id, port_label
        from .discovery.neighbor_detail import remote_port

        result["observed_remote_name"] = neighbor_label(obj.remote_name)
        result["observed_remote_port"] = remote_port(obj.evidence or {}, obj.remote_port)
        result["remote_name"] = name_label(obj)
        result["remote_port"] = port_label(obj)
        result["remote_device_id"] = peer_id(obj)
        result["confidence"] = confidence(obj)
        result["has_manual_changes"] = (
            obj.manual_remote_name is not None or obj.manual_remote_port is not None
        )
        result["local_aggregate"] = (obj.evidence or {}).get("local_aggregate")
    if isinstance(obj, m.Device):
        result["kind_name"] = obj.device_type.name if obj.device_type else obj.kind
    if isinstance(obj, m.Scope):
        result["credential_ids"] = obj.credential_ids
    return result


def get(db, model, id):
    row = db.get(model, id)
    if not row:
        raise HTTPException(404, "Kayıt bulunamadı")
    return row


def require_ref(db, model, id):
    return get(db, model, id) if id else None


def lock_vrf(db, vrf_id):
    # Serialize IP writers on a dedicated state row, not their shared FK parent.
    # An exclusive lock on vrfs also blocks unrelated scope/device FK inserts.
    # Upsert both initializes the mutex safely and performs a real version write
    # for Galera certification. Acquire it before establishing a read snapshot.
    if db.get_bind().dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.mysql import insert

    statement = insert(m.SystemState).values(key="vrf:" + vrf_id, value="1")
    version = cast(cast(m.SystemState.value, BigInteger) + 1, String(100))
    if db.get_bind().dialect.name == "sqlite":
        statement = statement.on_conflict_do_update(index_elements=["key"], set_={"value": version})
    else:
        statement = statement.on_duplicate_key_update(value=version)
    db.execute(statement)
    # A current shared read validates the parent without blocking FK checks.
    row = db.scalar(select(m.VRF).where(m.VRF.id == vrf_id).with_for_update(read=True))
    if not row:
        raise HTTPException(422, "VRF bulunamadı")
    return row


def validate_relations(db, name, data, row_id=None, *, lock=True):
    from .ipam.locations import validate_location_relations

    validate_location_relations(db, name, data, row_id)
    if "vrf_id" in data:
        if lock and name != "scopes":
            lock_vrf(db, data["vrf_id"])
        else:
            get(db, m.VRF, data["vrf_id"])
    if data.get("site_id"):
        require_ref(db, m.Site, data["site_id"])
    if name == "sites" and row_id:
        if db.scalar(
            select(m.Scope.id)
            .where(
                m.Scope.site_id == row_id,
                m.Scope.institution_id.is_not(None),
                m.Scope.institution_id != data["institution_id"],
            )
            .limit(1)
        ):
            raise HTTPException(409, "Önce bu lokasyonu kullanan keşif kapsamlarının kurumunu güncelleyin")
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
        if row_id:
            previous = get(db, m.IPAddress, row_id)
            if previous.address != data["address"] and db.scalar(
                select(m.IPObservation.id).where(m.IPObservation.address_id == row_id).limit(1)
            ):
                raise HTTPException(409, "Kaynaklardan gelen IP adresi değiştirilemez")
        if data.get("device_id"):
            device = get(db, m.Device, data["device_id"])
            if device.archived or device.vrf_id != data["vrf_id"]:
                raise HTTPException(422, "Bağlı cihaz aynı VRF içinde ve aktif envanterde olmalı")
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
            if data.get("device_id") and data["device_id"] != device.id:
                raise HTTPException(422, "Arayüz seçilen bağlı cihaza ait değil")
            if interface.is_deleted or device.archived:
                raise HTTPException(422, "Arayüz aktif envanterde değil")
            data["device_id"] = device.id
            if device.vrf_id != data["vrf_id"] or (prefix.site_id and prefix.site_id != device.site_id):
                raise HTTPException(422, "Arayüzün VRF veya site bilgisi prefix ile uyumsuz")
    if name == "scopes":
        site = get(db, m.Site, data["site_id"]) if data.get("site_id") else None
        # Legacy clients can omit the institution when the location determines it.
        if not data.get("institution_id") and site:
            data["institution_id"] = site.institution_id
        if data.get("institution_id"):
            institution = db.scalar(
                select(m.Institution).where(m.Institution.id == data["institution_id"]).with_for_update()
            )
            if not institution:
                raise HTTPException(422, "Kurum bulunamadı")
            institution.lock_version += 1
            db.flush()
            if site and site.institution_id != institution.id:
                raise HTTPException(422, "Lokasyon seçilen kuruma ait değil")
        for profile_id in data["credential_ids"]:
            if get(db, m.Credential, profile_id).protocol not in SNMP_PROTOCOLS:
                raise HTTPException(422, "Keşif SNMPv3 veya SNMPv2c profili gerektirir")
    if name == "rules" and row_id and not data["enabled"]:
        for alert in db.scalars(
            select(m.Alert).where(m.Alert.rule_id == row_id, m.Alert.active_key.is_not(None))
        ):
            alert.state, alert.active_key, alert.resolved_at = "resolved", None, now()


def save_resource(db, name, payload, user, row_id=None, *, commit=True, manual_fields=None):
    if name not in RESOURCES or RESOURCES[name][1] is None:
        raise HTTPException(405, "Bu kaynak salt okunur")
    model, schema = RESOURCES[name]
    if name in ("credentials", "users") and user.role != "admin":
        raise HTTPException(403, "Yönetici yetkisi gerekli")
    if name == "users" and row_id:
        raise HTTPException(405, "Kullanıcı parolası için parola değiştirme işlemini kullanın")
    value = schema.model_validate(payload)
    data = value.model_dump()
    if name == "devices" and row_id:
        row = db.scalar(
            select(model)
            .where(model.id == row_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not row:
            raise HTTPException(404, "Kayıt bulunamadı")
    else:
        row = get(db, model, row_id) if row_id else model()
    identify_changed = name == "devices" and (
        not row_id
        or any(
            getattr(row, key) != data[key]
            for key in (*IDENTITY_CONNECTION_FIELDS, "vendor", "model", "kind", "lifecycle_status")
        )
    )
    replay_prefix = name == "prefixes" and (
        not row_id or row.cidr != data["cidr"] or row.vrf_id != data["vrf_id"]
    )
    if name == "prefixes" and row_id and (row.cidr != data["cidr"] or row.vrf_id != data["vrf_id"]):
        row.scan_authorized = row.ping_enabled = row.discovery_enabled = False
    if name == "addresses" and row_id:
        hierarchy = {"institution_id", "site_id", "sub_site_id"}
        if not hierarchy.intersection(value.model_fields_set) and data["location"] == row.location:
            # Older clients may update another field without knowing the hierarchy.
            data.update({key: getattr(row, key) for key in hierarchy})
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
    if name == "devices" and row_id:
        # Full edit forms include unchanged observations: protect actual edits only.
        # Bulk operations explicitly select fields, including a value already in use.
        changed = {
            key
            for key in ("vendor", "model", "kind")
            if getattr(row, key) != data[key] or key in (manual_fields or ())
        }
        row.manual_identity_fields = sorted(set(row.manual_identity_fields or []) | changed)
    scope_profiles = data.pop("credential_ids") if name == "scopes" else None
    for key, val in data.items():
        setattr(row, key, val)
    db.add(row)
    db.flush()
    if scope_profiles is not None:
        db.execute(delete(m.ScopeCredential).where(m.ScopeCredential.scope_id == row.id))
        db.add_all(
            m.ScopeCredential(scope_id=row.id, credential_id=id, position=position)
            for position, id in enumerate(scope_profiles)
        )
        db.flush()
        db.expire(row, ["profiles"])
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
    if name == "devices":
        from .ipam.service import inventory_observations

        latest = db.scalar(
            select(m.Observation)
            .where(m.Observation.device_id == row.id, m.Observation.source.in_(SNMP_PROTOCOLS))
            .order_by(m.Observation.created_at.desc())
            .limit(1)
        )
        collected = latest.evidence if latest and latest.created_at >= now() - timedelta(hours=24) else {}
        inventory_observations(db, row, {**collected, "hostname": row.name})
    if replay_prefix:
        # Durable work is committed atomically with the block. API latency must
        # not grow with the number of devices or cached ARP/FDB observations.
        enqueue(db, "ipam_inventory", row.id, user, commit=False)
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
        stmt = stmt.where(m.Link.is_current.is_(True), m.Link.auto_add_excluded.is_(False))
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
    if name == "prefixes":
        # CIDRs are stored as text. Sort numerically before pagination so that
        # 10.2 precedes 10.10 and compressed IPv6 notation orders correctly.
        def network_key(row):
            network = ipaddress.ip_network(row.cidr)
            return network.version, int(network.network_address), network.prefixlen, row.vrf_id, row.id

        rows = sorted(db.scalars(stmt).all(), key=network_key)[offset : offset + limit]
    else:
        rows = db.scalars(stmt.order_by(model.created_at.desc(), model.id).offset(offset).limit(limit)).all()
    items = [serialize(row) for row in rows]
    if name == "prefixes":
        from .ipam.service import prefix_summaries

        items = prefix_summaries(db, rows)
    if name == "addresses":
        from .ipam.service import enrich

        items = enrich(db, rows)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def delete_resource(db, name, id, user):
    if name == "links":
        if user.role != "admin":
            raise HTTPException(403, "Silme için yönetici yetkisi gerekli")
        from .discovery.link_deletions import delete_link

        return delete_link(db, id, user)
    if name not in RESOURCES or RESOURCES[name][1] is None:
        raise HTTPException(405, "Bu kaynak salt okunur")
    if user.role != "admin":
        raise HTTPException(403, "Silme için yönetici yetkisi gerekli")
    model = RESOURCES[name][0]
    row = get(db, model, id)
    if name in ("users", "vrfs"):
        raise HTTPException(409, "Kimlik ve VRF kayıtları geçmişi korumak için silinemez")
    if name == "prefixes":
        from .ipam.prefix_deletion import remove

        return remove(db, [id], user)
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
        row.backup_interval = 0
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
    from .ipam.service import require_scope

    for prefix in db.scalars(
        select(m.Prefix).where(m.Prefix.vrf_id == device.vrf_id, m.Prefix.scan_authorized.is_(True))
    ):
        scopes.append(require_scope(db, prefix))
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
    from .ipam.jobs import KINDS, validate_target

    if kind not in (*KINDS, "discovery", "backup", "compare", "identify", *CONNECTION_TESTS):
        raise HTTPException(422, "Geçersiz görev türü")
    if kind in KINDS:
        target = validate_target(db, kind, target_id)
    elif kind == "discovery":
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
    current = db.scalar(
        select(type(target))
        .where(type(target).id == target_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None:
        raise HTTPException(404, "Görev hedefi artık yok")
    if kind in KINDS:
        validate_target(db, kind, target_id)
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
        client = redis_client()
        client.incr("netrix:ipam:revision")
        client.publish("netrix:events", "refresh")
    except Exception:
        pass
