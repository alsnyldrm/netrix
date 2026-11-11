import { Dialog, date } from "./main";
import "./audit.css";

type Row = Record<string, any>;
const fields: Record<string, string> = {
  name: "Ad",
  code: "Kod",
  description: "Açıklama",
  email: "E-posta",
  display_name: "Kullanıcı adı",
  role: "Uygulama rolü",
  ssh_access: "SSH yetkisi",
  is_active: "Hesap durumu",
  institution_id: "Kurum",
  site_id: "Lokasyon",
  sub_site_id: "Oda",
  parent_id: "Üst lokasyon",
  timezone: "Saat dilimi",
  units: "Kabin yüksekliği",
  cabinet_id: "Kabin",
  device_id: "Cihaz",
  start_unit: "Başlangıç ünitesi",
  kind: "Tür",
  vrf_id: "VRF",
  vid: "VLAN numarası",
  domain: "VLAN alanı",
  cidr: "Ağ kapsamı",
  enabled: "Etkinlik",
  ping_enabled: "Periyodik ping",
  ping_interval: "Ping aralığı (sn)",
  interval_seconds: "Zamanlama aralığı (sn)",
  protocol: "Protokol",
  vendor: "Üretici",
  model: "Model",
  management_ip: "Yönetim IP adresi",
  hostname: "Hostname",
  mac_address: "MAC adresi",
  status: "Durum",
  interface_id: "Port",
  address: "IP adresi",
  location: "Konum",
  operating_system_id: "İşletim sistemi",
  lifecycle_status: "Yaşam döngüsü",
  archived: "Arşiv durumu",
  backup_interval: "Yedekleme aralığı",
  backup_group_id: "Yedekleme grubu",
  adapter: "Cihaz adaptörü",
  snmp_port: "SNMP portu",
  config_port: "Bağlantı portu",
  snmp_credential_id: "SNMP profili",
  config_credential_id: "Bağlantı profili",
  ssh_trust_host_key: "SSH anahtarına güven",
  identity_path: "Cihaz bilgisi yolu",
  is_gateway: "Gateway",
  is_vip: "VIP",
  credential_id: "Erişim profili",
  is_managed: "Yönetilen port",
  is_deleted: "Silinme durumu",
  admin_status: "Yönetim durumu",
  oper_status: "Çalışma durumu",
  dns_server_id: "DNS sunucusu",
  port: "Port",
  host: "Sunucu",
  username: "Kullanıcı adı",
  url: "Adres",
  verify_tls: "TLS doğrulaması",
  manual_remote_name: "Komşu cihaz adı",
  manual_remote_port: "Komşu port",
  remote_device_id: "Komşu cihaz",
  auto_add_excluded: "Keşif engeli",
  is_current: "Güncellik",
  base_snapshot_id: "Base config",
  acknowledged_at: "Onay zamanı",
  acknowledged_by: "Onaylayan",
  owner_id: "Sahibi",
  ssh_profile_id: "SSH profili",
  protected_values: "Gizli bilgiler",
  preferences: "Görünüm tercihleri",
  "preferences.palette": "Renk paleti",
  "preferences.ui_font": "Uygulama yazı tipi",
  "preferences.design": "Çalışma alanı düzeni",
  "preferences.timezone": "Saat dilimi",
  "preferences.locale": "Dil ve bölge",
  "preferences.hour12": "12 saat biçimi",
  "preferences.features": "Çalışma alanı özellikleri",
  "preferences.terminal.font": "Terminal yazı tipi",
  "preferences.terminal.font_size": "Terminal yazı boyutu",
  "preferences.terminal.font_weight": "Terminal yazı kalınlığı",
  "preferences.terminal.background": "Terminal arka planı",
  "preferences.terminal.commands_width": "Komut paneli genişliği",
  "preferences.terminal.commands_collapsed": "Komut paneli kapalı",
  operating_system: "İşletim sistemi",
  cabinet: "Kabin",
  frequency: "Tekrar sıklığı",
  repeat_every: "Tekrar aralığı",
  start_at: "Başlangıç zamanı",
  run_limit: "Çalıştırma sınırı",
  mode: "İşlem biçimi",
  available_at: "Planlanan zaman",
  cancel_requested: "İptal isteği",
  force_stop_requested: "Zorla durdurma isteği",
  deleted_at: "Listeden kaldırılma zamanı",
  severity: "Önem düzeyi",
  event_kind: "Olay türü",
  family: "Cihaz ailesi",
  version: "Sürüm",
  original_name: "Dosya adı",
  size_bytes: "Dosya boyutu (byte)",
  notes: "Notlar",
  target_version: "Hedef sürüm",
  strategy: "Strateji",
  concurrency: "Eşzamanlılık",
  scan_authorized: "Tarama yetkisi",
  dns_enabled: "DNS sorgulaması",
  vlan_id: "VLAN",
  vlan_vid: "VLAN numarası",
  scope_id: "Keşif kapsamı",
};
const values: Record<string, string> = {
  admin: "Yönetici",
  super_admin: "Süper yönetici",
  operator: "Operatör",
  viewer: "Gözlemci",
  active: "Aktif",
  retired: "Kullanımdan kaldırıldı",
  up: "Açık",
  down: "Kapalı",
};
function value(item: any): string {
  if (item === null || item === undefined || item === "") return "—";
  if (typeof item === "boolean") return item ? "Evet" : "Hayır";
  if (typeof item === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:/.test(item))
    return date(item);
  return values[String(item)] || String(item);
}
function label(key: string) {
  return fields[key] || key.replaceAll("_", " ");
}

export function AuditSummary({ row }: { row: Row }) {
  const changes = Object.entries(row.details?.changes || {}) as [string, Row][];
  return (
    <div className="audit-summary">
      <span>{row.summary}</span>
      {changes.length > 0 && (
        <span className="audit-change-preview">
          {changes
            .slice(0, 2)
            .map(
              ([key, change]) =>
                `${label(key)}: ${value(change.previous)} → ${value(change.current)}`,
            )
            .join(" · ")}
          {changes.length > 2 && ` · +${changes.length - 2} alan`}
        </span>
      )}
    </div>
  );
}

export function AuditDetails({
  row,
  onClose,
}: {
  row: Row;
  onClose: () => void;
}) {
  const changes = Object.entries(row.details?.changes || {}) as [string, Row][];
  return (
    <Dialog title="İşlem ayrıntıları" onClose={onClose} wide>
      <div className="audit-details">
        <dl className="audit-metadata">
          {[
            ["Kullanıcı", row.actor_name],
            ["E-posta", row.actor_email],
            ["Zaman", date(row.created_at)],
            ["İşlem", row.action_label],
            ["Kaynak", row.resource_label],
            ["Etkilenen kayıt", row.target_label || "—"],
          ].map(([key, item]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{item || "—"}</dd>
            </div>
          ))}
        </dl>
        <p>{row.summary}</p>
        {changes.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Değişen alanlar"
          >
            <table className="audit-changes">
              <caption>Değişen alanların önceki ve sonraki değerleri</caption>
              <thead>
                <tr>
                  <th scope="col">Alan</th>
                  <th scope="col">Önceki değer</th>
                  <th scope="col">Yeni değer</th>
                </tr>
              </thead>
              <tbody>
                {changes.map(([key, change]) => (
                  <tr key={key}>
                    <th scope="row">{label(key)}</th>
                    <td>{value(change.previous)}</td>
                    <td>{value(change.current)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">
            Bu işlem için alan bazında önceki ve sonraki değer kaydedilmemiş.
            Mevcut işlem açıklaması yukarıda gösteriliyor.
          </p>
        )}
        <p className="muted audit-secret-note">
          Parola, anahtar, token ve konfigürasyon içeriği denetim izinde
          gösterilmez.
        </p>
        <div className="dialog-footer">
          <button className="secondary" onClick={onClose}>
            Kapat
          </button>
        </div>
      </div>
    </Dialog>
  );
}
