"""Human-readable task context; never expose raw results or access secrets."""

from datetime import datetime

from sqlalchemy import select

from . import models as m
from .core import now

DESCRIPTIONS = {
    "test_integration": (
        "Entegrasyon bağlantı testi",
        "DHCP veya vCenter bağlantısını, kullanıcı doğrulamasını ve temel okuma erişimini formdaki ayarlarla kontrol eder. Entegrasyon ayarlarını ve IPAM kayıtlarını değiştirmez.",
    ),
    "ipam_address_scan": (
        "Tek IP taraması",
        "Seçilen IP adresini SQL kaynak kayıtlarından yeniden eşleştirir. Cihaz sorgusu veya ping başlatmaz.",
    ),
    "discovery": (
        "SNMP ağ keşfi",
        "Seçilen ağ kapsamındaki IP adreslerine SNMP ile bağlanır. Yanıt veren cihazların adını, modelini, portlarını ve LLDP/CDP komşularını okuyarak yalnızca cihaz envanterini günceller.",
    ),
    "ipam_ping": (
        "IP erişilebilirlik kontrolü",
        "Ağ bloğunda kayıtlı IP adreslerine ping gönderir. Yanıt verenleri aktif olarak işaretler ve doluluk bilgisini günceller. Yeni cihaz eklemez.",
    ),
    "ipam_discover": (
        "IP adresi keşfi",
        "VLAN içindeki IP adreslerini ping ve DNS ile kontrol eder. Gateway ARP/NDP ve switch MAC tablolarını kayıtlı cihaz profilleriyle okur; komşuluk kanıtlarıyla bağlantıyı eşleştirir. Envantere cihaz eklemez. DHCP/VMware eşitlemelerini de kuyruğa alır.",
    ),
    "integration": (
        "Entegrasyon güncellemesi",
        "Seçilen vCenter veya Windows DHCP sunucusundan kayıtları okur. IPAM VLAN’larındaki IP, MAC ve sunucu bilgilerini günceller.",
    ),
    "identify": (
        "Cihaz kimliği sorgulama",
        "Cihazın erişim profillerini kullanarak üretici, model ve cihaz türünü okur. Okunamayan veya kullanıcı tarafından düzenlenmiş alanları korur.",
    ),
    "backup": (
        "Konfigürasyon yedekleme",
        "Cihazın mevcut konfigürasyonunu okur, şifreli bir sürüm olarak saklar ve base config ile değişikliklerini karşılaştırır. Cihazın konfigürasyonunu değiştirmez.",
    ),
    "compare": (
        "Canlı konfigürasyon karşılaştırma",
        "Cihazın şu anki konfigürasyonunu okur ve seçilen kayıtlı yedekle karşılaştırır. Cihaz üzerinde değişiklik yapmaz.",
    ),
    "test_snmp": (
        "SNMP bağlantı testi",
        "Cihazın SNMP erişim profiliyle temel sistem bilgisinin okunabildiğini kontrol eder. Tam ağ taraması yapmaz.",
    ),
    "test_snmpv2c": (
        "SNMPv2c bağlantı testi",
        "Cihazın SNMPv2c profiliyle temel sistem bilgisine erişilebildiğini kontrol eder.",
    ),
    "test_ssh": (
        "SSH bağlantı testi",
        "Cihazın SSH bağlantısını, kullanıcı erişimini ve host anahtarı doğrulamasını kontrol eder.",
    ),
    "test_api": (
        "API bağlantı testi",
        "Cihazın API adresine erişimi, TLS güvenini ve erişim profilini kontrol eder.",
    ),
}


def target_model(kind):
    if kind == "ipam_address_scan":
        return m.IPAddress
    if kind == "discovery":
        return m.Scope
    if kind in ("ipam_ping", "ipam_discover"):
        return m.VLAN
    if kind in ("integration", "test_integration"):
        return m.Integration
    return m.Device


def target_label(target):
    if target is None:
        return "Hedef kayıt artık mevcut değil"
    if isinstance(target, m.Scope):
        return f"{target.name} · {target.cidr}"
    if isinstance(target, m.Device):
        return f"{target.name} · {target.management_ip}"
    return getattr(target, "cidr", None) or getattr(target, "name", None) or target.address


def job_target_label(job, target):
    if job.kind == "test_integration":
        result = job.result or {}
        return f"{result.get('target', 'Entegrasyon')}:{result.get('port', '')}"
    return target_label(target)


def summaries(db, jobs):
    targets = {}
    for model in {target_model(job.kind) for job in jobs}:
        ids = {job.target_id for job in jobs if target_model(job.kind) is model}
        targets.update({(model, row.id): row for row in db.scalars(select(model).where(model.id.in_(ids)))})
    return [
        {
            "title": DESCRIPTIONS.get(job.kind, ("Geçmiş görev", ""))[0],
            "target_label": job_target_label(job, targets.get((target_model(job.kind), job.target_id))),
        }
        for job in jobs
    ]


def details(db, job):
    title, description = DESCRIPTIONS.get(
        job.kind, ("Geçmiş görev", "Bu eski görev türü için açıklama bulunmuyor.")
    )
    target = db.get(target_model(job.kind), job.target_id)
    sql_only = ((job.result or {}).get("network") or {}).get("mode") == "sql" or (
        job.kind in ("ipam_address_scan", "ipam_discover")
        and (job.result or {}).get("ipam_origin") == "manual"
    )
    if sql_only:
        description = "Seçili IP/VLAN kayıtlarını yalnız SQL kaynak verilerinden yeniden eşleştirir; cihazlara bağlanmaz."
    paragraphs = [description]
    if isinstance(target, m.Scope):
        profiles = list(
            db.scalars(select(m.Credential.name).where(m.Credential.id.in_(target.credential_ids)))
        )
        if profiles:
            paragraphs.append("Kullanılan SNMP profilleri: " + ", ".join(profiles) + ".")
        paragraphs.append(
            "Tarama hedefi: "
            + (
                f"açıkça seçilmiş {len(target.seeds)} IP adresi."
                if target.seeds
                else target.cidr + " ağındaki kullanılabilir adresler."
            )
        )
        if target.exclusions:
            paragraphs.append("Hariç tutulan adresler/ağlar: " + ", ".join(target.exclusions) + ".")
    if job.cancel_requested and job.status in ("queued", "running"):
        paragraphs.append("İptal istendi; devam eden işlem durduruluyor.")
    elif job.status == "queued":
        paragraphs.append(
            "Önceki deneme tamamlanamadı; yeniden deneme zamanı bekleniyor."
            if job.attempts and job.available_at > now()
            else "Çalıştırılmak üzere sırada. Uzun ağ keşifleri için ayrı kapasite sınırı uygulanır; diğer görevler eşzamanlı ilerleyebilir."
        )
    elif job.status == "running":
        paragraphs.append(
            f"Görev çalışıyor. {job.total} hedeften {job.progress} tanesi işlendi."
            if job.total
            else "Görev çalışıyor; hedef sistemin yanıtı alınıyor veya kayıtlar işleniyor."
        )
    elif job.status == "cancelled":
        paragraphs.append("Görev iptal edildi. Tamamlanan adımlardaki kayıtlar korunur.")
    elif job.status == "succeeded":
        paragraphs.append("Görev başarıyla tamamlandı.")
    elif job.status == "partial":
        paragraphs.append(
            "SQL kayıtları işlendi; bazı kaynak verileri eksik, eski veya çelişkili."
            if sql_only
            else "Görev kısmen tamamlandı. Bazı hedeflerden yanıt veya bilgi alınamadı."
        )
    else:
        paragraphs.append("Görev tamamlanamadı.")
    result = job.result or {}
    if job.kind in ("discovery", "ipam_ping", "ipam_discover", "ipam_address_scan") and "reachable" in result:
        paragraphs.append(
            f"Yanıt veren: {result['reachable']}. Yanıt alınamayan: {result.get('unresponsive', result.get('no_reply', 0))}."
        )
    if result.get("ping_failed"):
        paragraphs.append(
            f"Ping işlemi çalıştırılamayan: {result['ping_failed']}. Önceki ping durumları korundu."
        )
    if job.kind == "test_integration" and result.get("message"):
        paragraphs.append(result["message"])
    if job.kind == "integration" and "imported" in result:
        paragraphs.append(
            f"Okunan kayıt: {result.get('observed', 0)}. İşlenen IP kaydı: {result['imported']}."
        )
    if job.kind in ("ipam_discover", "ipam_address_scan") and result.get("network"):
        network = result["network"]
        paragraphs.append(
            "SQL kaynak kayıtları işlendi; canlı cihaz sorgusu yapılmadı."
            if network.get("mode") == "sql"
            else f"Gateway/switch kaynakları: {network.get('read', 0)} okundu, {network.get('failed', 0)} okunamadı."
        )
    if job.kind == "ipam_discover" and result.get("source_statuses"):
        statuses = result["source_statuses"].values()
        paragraphs.append(
            f"DHCP/VMware eşitlemeleri: {sum(s == 'succeeded' for s in statuses)} tamamlandı, {sum(s != 'succeeded' for s in statuses)} tamamlanamadı."
        )
    if job.kind == "ipam_discover" and result.get("matching"):
        match = result["matching"]
        paragraphs.append(
            f"Eşleştirilen {match['addresses']} IP içinde: {match['hostname']} hostname, {match['mac_address']} MAC, {match['connected_port']} cihaz/port, {match['operating_system']} VMware işletim sistemi. Belirsiz bağlantı: {match['ambiguous']}."
        )
    if job.kind == "compare" and "changed" in result:
        paragraphs.append(
            "Kayıtlı yedeğe göre değişiklik bulundu."
            if result["changed"]
            else "Kayıtlı yedeğe göre değişiklik bulunmadı."
        )
    if job.kind.startswith("test_") and result.get("message"):
        paragraphs.append(result["message"])
    if job.error:
        paragraphs.append(job.error)
    started = result.get("started_at")
    try:
        queue_seconds = (
            max(0, (datetime.fromisoformat(started) - job.created_at).total_seconds()) if started else None
        )
    except (ValueError, TypeError):
        started, queue_seconds = None, None
    if not started and job.status == "queued" and not job.attempts:
        queue_seconds = max(0, (now() - job.created_at).total_seconds())
    return {
        "id": job.id,
        "title": title,
        "target_label": job_target_label(job, target),
        "status": job.status,
        "paragraphs": paragraphs,
        "created_at": job.created_at.isoformat(),
        "started_at": started,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "queue_seconds": queue_seconds,
        "elapsed_seconds": max(0, ((job.finished_at or now()) - job.created_at).total_seconds()),
        "attempts": job.attempts,
        "progress": job.progress,
        "total": job.total,
        "requested_by": "Kullanıcı" if job.requested_by else "Zamanlama veya bağlı işlem",
    }
