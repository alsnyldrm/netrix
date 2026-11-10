"""Read all users' actions without mixing scheduler/worker journal entries."""

from sqlalchemy import String, cast, func, or_, select

from .. import models as m

RESOURCE_LABELS = {
    "users": "Kullanıcı",
    "institutions": "Kurum",
    "sites": "Lokasyon",
    "cabinets": "Kabin",
    "devices": "Cihaz",
    "interfaces": "Port",
    "addresses": "IP adresi",
    "vlans": "VLAN",
    "vrfs": "VRF",
    "scopes": "Keşif kapsamı",
    "credentials": "Erişim profili",
    "integrations": "Entegrasyon",
    "dns-servers": "DNS sunucusu",
    "operating-systems": "İşletim sistemi",
    "scan-groups": "Tarama grubu",
    "ipam_scan_groups": "Tarama grubu",
    "backup-groups": "Yedekleme grubu",
    "device-types": "Cihaz türü",
    "jobs": "Görev",
    "job_archives": "Görev arşivi",
    "snapshots": "Konfigürasyon",
    "alerts": "Uyarı",
    "rules": "Uyarı kuralı",
    "links": "Komşuluk",
    "firmware_images": "Firmware dosyası",
    "firmware_groups": "Firmware grubu",
    "firmware_plans": "Firmware planı",
    "user_workspaces": "Kişisel ayarlar",
    "user_ssh_profile": "Kişisel SSH profili",
    "access_group": "Kişisel cihaz grubu",
    "rack_placements": "Kabin yerleşimi",
    "rack_accessories": "Kabin aksesuarı",
    "patch_panels": "Patch panel",
    "patch_ports": "Patch portu",
}
ACTION_LABELS = {
    "create": "Oluşturdu",
    "update": "Güncelledi",
    "delete": "Sildi",
    "archive": "Arşivledi",
    "archive_jobs": "Görevleri arşivledi",
    "setup": "İlk kurulumu tamamladı",
    "login": "Oturum açtı",
    "password_change": "Parolasını değiştirdi",
    "enqueue": "Görev başlattı",
    "cancel": "İptal istedi",
    "acknowledge": "Uyarıyı onayladı",
    "read_config": "Konfigürasyonu görüntüledi",
    "compare_config": "Konfigürasyonları karşılaştırdı",
    "set_base": "Base config seçti",
    "approve_config": "Konfigürasyon farkını onayladı",
    "user_roles_updated": "Yetkileri değiştirdi",
    "toggle_user": "Hesap erişimini değiştirdi",
    "integration_save": "Entegrasyonu kaydetti",
    "ipam_settings": "VLAN ayarlarını değiştirdi",
    "bulk_update": "Toplu güncelledi",
    "bulk_archive": "Toplu arşivledi",
    "bulk_restore": "Geri yükledi",
    "bulk_purge": "Kalıcı sildi",
    "bulk_delete": "Toplu sildi",
    "delete_link": "Komşuluğu sildi",
    "restore_link": "Komşuluğu geri yükledi",
    "edit_link_labels": "Komşuluk bilgilerini değiştirdi",
    "select_interfaces": "Portları seçti",
    "csv_import": "CSV içe aktardı",
    "xlsx_import": "Excel içe aktardı",
    "rack_place": "Kabine yerleştirdi",
    "rack_unplace": "Kabin yerleşimini kaldırdı",
    "rack_accessory_remove": "Kabin aksesuarını kaldırdı",
    "model_image": "Model görselini kaydetti",
    "ssh_profile_saved": "SSH profilini kaydetti",
    "ssh_profile_deleted": "SSH profilini sildi",
    "access_group_saved": "Cihaz grubunu kaydetti",
    "access_group_deleted": "Cihaz grubunu sildi",
    "ssh_session_opened": "SSH oturumu açtı",
    "ssh_batch_requested": "Toplu komut istedi",
    "start": "Başlattı",
    "activate": "Etkinleştirdi",
    "upload": "Dosya yükledi",
    "verify": "Dosyayı doğruladı",
    "retry": "Yeniden denedi",
    "manual_recovery": "Kurtarma işlemi yaptı",
    "create_from_ip": "IP kaydından oluşturdu",
    "patch_panel_delete": "Patch paneli sildi",
    "patch_panel_save": "Patch paneli kaydetti",
    "patch_port_save": "Patch portunu kaydetti",
    "rack_accessory_save": "Kabin aksesuarını kaydetti",
    "scan_group_save": "Tarama grubunu kaydetti",
    "scan_group_delete": "Tarama grubunu sildi",
    "concurrency": "Eşzamanlılığı değiştirdi",
    "force_stop": "Zorla durdurdu",
    "stop": "Durdurdu",
    "remove": "Listeden kaldırdı",
}


def enrich(db, rows):
    from ..services import RESOURCES, serialize

    actors = {u.id: u for u in db.scalars(select(m.User).where(m.User.id.in_({r.actor_id for r in rows})))}
    targets = {}
    # Historical entries have no snapshot. Resolve labels in batches per resource.
    for resource in {r.entity_type for r in rows}:
        model = RESOURCES.get(resource, (None,))[0]
        ids = {r.entity_id for r in rows if r.entity_type == resource and not (r.details or {}).get("target")}
        if model and ids:
            key = next(
                (key for key in ("name", "address", "display_name", "kind") if hasattr(model, key)), None
            )
            if key:
                for target_id, label in db.execute(
                    select(model.id, getattr(model, key)).where(model.id.in_(ids))
                ):
                    targets[(resource, target_id)] = label or target_id
    items = []
    for row in rows:
        details = row.details or {}
        actor = details.get("actor") or {}
        user = actors.get(row.actor_id)
        items.append(
            dict(
                serialize(row),
                actor_name=actor.get("name") or (user.display_name if user else "Kayıtlı kullanıcı"),
                actor_email=actor.get("email") or (user.email if user else ""),
                resource_label=RESOURCE_LABELS.get(row.entity_type, "Uygulama kaydı"),
                action_label=ACTION_LABELS.get(row.action, "İşlem yaptı"),
                target_label=details.get("target")
                or targets.get((row.entity_type, row.entity_id))
                or row.entity_id,
            )
        )
    return items


def list_entries(db, limit, offset, q):
    stmt = select(m.Audit).where(m.Audit.actor_id.is_not(None))
    if q:
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        actor_ids = select(m.User.id).where(
            or_(
                m.User.display_name.ilike(pattern, escape="\\"),
                m.User.email.ilike(pattern, escape="\\"),
            )
        )
        actions = [key for key, label in ACTION_LABELS.items() if q.casefold() in label.casefold()]
        resources = [key for key, label in RESOURCE_LABELS.items() if q.casefold() in label.casefold()]
        stmt = stmt.where(
            or_(
                m.Audit.actor_id.in_(actor_ids),
                m.Audit.summary.ilike(pattern, escape="\\"),
                cast(m.Audit.details, String).ilike(pattern, escape="\\"),
                m.Audit.details["target"].as_string().ilike(pattern, escape="\\"),
                m.Audit.details["actor"]["name"].as_string().ilike(pattern, escape="\\"),
                m.Audit.details["actor"]["email"].as_string().ilike(pattern, escape="\\"),
                m.Audit.action.in_(actions),
                m.Audit.entity_type.in_(resources),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.with_only_columns(m.Audit.id).subquery()))
    rows = list(db.scalars(stmt.order_by(m.Audit.created_at.desc(), m.Audit.id).limit(limit).offset(offset)))
    return {"items": enrich(db, rows), "total": total, "limit": limit, "offset": offset}
