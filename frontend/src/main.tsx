import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useDeferredValue,
} from "react";
import { createRoot } from "react-dom/client";
import {
  SquaresFour,
  Stack,
  GlobeHemisphereWest,
  GitBranch,
  ChartLineUp,
  ShieldCheck,
  GearSix,
  ArrowUpRight,
  ArrowRight,
  Plus,
  MagnifyingGlass,
  Command,
  Clock,
  Check,
  WarningCircle,
  X,
  SignOut,
  ArrowsClockwise,
  Play,
  Stop,
  DownloadSimple,
  CaretRight,
  CaretLeft,
  DotsThree,
  Eye,
  PencilSimple,
  Trash,
  CheckCircle,
  Waveform,
  Key,
  TerminalWindow,
  PlugsConnected,
  Lightning,
  SlidersHorizontal,
  Users,
  Buildings,
  Link as LinkIcon,
  Circle,
  Info,
  ArrowDown,
  ArrowUp,
  LockKey,
  HardDrives,
  TreeStructure,
  ListNumbers,
  Rows,
  Path,
  Broadcast,
  Graph,
  ClockCounterClockwise,
  Bell,
  Sun,
  Moon,
  List,
  CaretDoubleLeft,
  CaretDown,
  CaretUp,
} from "@phosphor-icons/react";
import type { Icon as IconType } from "@phosphor-icons/react";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./style.css";
import {
  InventoryTable,
  InterfaceWorkspace,
  InterfacePicker,
} from "./inventory";
import { BackupWorkspace } from "./backups";

type Row = Record<string, any>;
type Field = {
  key: string;
  label: string;
  type?: string;
  options?: string[] | [string, string][];
  ref?: string;
  required?: boolean;
  default?: any;
  hint?: string;
};
type Page = {
  key: string;
  title: string;
  desc: string;
  group: string;
  icon: IconType;
  resource?: string;
  columns?: [string, string][];
  fields?: Field[];
};
const f = (key: string, label: string, extra: Partial<Field> = {}): Field => ({
  key,
  label,
  ...extra,
});
const ref = (key: string, label: string, resource: string, required = false) =>
  f(key, label, { type: "select", ref: resource, required });
const options = (
  key: string,
  label: string,
  values: string[],
  value?: string,
) =>
  f(key, label, {
    type: "select",
    options: values,
    default: value || values[0],
  });
export const PAGES: Page[] = [
  {
    key: "overview",
    title: "Operasyon panoraması",
    desc: "Ağınızdaki her bağlantı, tek bir bakışta.",
    group: "Genel bakış",
    icon: SquaresFour,
  },
  {
    key: "devices",
    title: "Cihaz envanteri",
    desc: "Bütün modüllerin paylaştığı tek ve merkezi cihaz kaydı.",
    group: "Envanter",
    icon: HardDrives,
    resource: "devices",
    columns: [
      ["name", "Cihaz"],
      ["management_ip", "Yönetim adresi"],
      ["kind", "Tür"],
      ["vendor", "Üretici"],
      ["site_id", "Lokasyon"],
      ["reachability", "Erişim"],
      ["lifecycle_status", "Yaşam döngüsü"],
    ],
    fields: [
      f("name", "Cihaz adı", { required: true }),
      f("management_ip", "Yönetim IP adresi", { required: true }),
      ref("vrf_id", "VRF", "vrfs", true),
      ref("site_id", "Lokasyon", "sites"),
      options(
        "kind",
        "Cihaz türü",
        ["switch", "router", "firewall", "server", "other"],
        "other",
      ),
      f("vendor", "Üretici"),
      f("model", "Model"),
      options("lifecycle_status", "Yaşam döngüsü", [
        "active",
        "planned",
        "maintenance",
        "retired",
      ]),
      options("adapter", "Konfigürasyon adaptörü", [
        "ios",
        "junos",
        "fortios",
        "linux",
        "rest",
      ]),
      ref("snmp_credential_id", "SNMPv3 profili", "credentials"),
      ref("config_credential_id", "SSH / API profili", "credentials"),
      f("snmp_port", "SNMP portu", { type: "number", default: 161 }),
      f("config_port", "SSH / HTTPS portu", {
        type: "number",
        default: 22,
        hint: "REST adaptörü için HTTPS portunu girin.",
      }),
      f("ssh_trust_host_key", "Anahtara güven", {
        type: "checkbox",
        default: false,
        hint: "Bu cihazın sunduğu SSH host anahtarı kabul edilir. SSH testi, cihaz bilgisi okuma ve yedeklemede geçerlidir.",
      }),
      f("config_path", "REST konfigürasyon yolu", { default: "/api/config" }),
      f("identity_path", "REST cihaz bilgisi yolu", {
        default: "/api/system",
        hint: "Üretici, model ve cihaz türünü döndüren JSON endpoint'i. Cihazınızın API yoluna göre düzenleyin.",
      }),
      f("monitoring_enabled", "Zamanlanmış izleme", {
        type: "checkbox",
        default: false,
      }),
      f("monitor_interval", "İzleme aralığı (saniye)", {
        type: "number",
        default: 300,
      }),
      ref("backup_group_id", "Yedek grubu", "backup-groups"),
      f("backup_retention", "En fazla yedek sayısı", {
        type: "number",
        default: 0,
        hint: "Grupsuz cihazlarda uygulanır. 0: sınırsız.",
      }),
      f("backup_interval", "Yedekleme aralığı (saniye)", {
        type: "number",
        default: 0,
        hint: "0: kapalı. Etkinleştirmek için en az 300.",
      }),
    ],
  },
  {
    key: "interfaces",
    title: "Arayüzler",
    desc: "Port durumu, kapasite ve cihaz bağlantıları.",
    group: "Envanter",
    icon: PlugsConnected,
    resource: "interfaces",
    columns: [
      ["name", "Arayüz"],
      ["device_id", "Cihaz"],
      ["if_index", "ifIndex"],
      ["oper_status", "Durum"],
      ["speed_bps", "Kapasite"],
      ["mac_address", "MAC adresi"],
    ],
  },
  {
    key: "sites",
    title: "Lokasyonlar",
    desc: "Fiziksel ağınızı anlamlı çalışma alanlarına ayırın.",
    group: "Envanter",
    icon: Buildings,
    resource: "sites",
    columns: [
      ["name", "Lokasyon"],
      ["code", "Kod"],
      ["description", "Açıklama"],
      ["timezone", "Saat dilimi"],
    ],
    fields: [
      f("name", "Lokasyon adı", { required: true }),
      f("code", "Benzersiz kod", { required: true }),
      f("description", "Açıklama"),
      f("timezone", "Saat dilimi", { default: "Europe/Istanbul" }),
    ],
  },
  {
    key: "prefixes",
    title: "Ağ blokları",
    desc: "IPv4 ve IPv6 alanlarınızı görünür ve düzenli tutun.",
    group: "IP adres yönetimi",
    icon: TreeStructure,
    resource: "prefixes",
    columns: [
      ["cidr", "Ağ bloğu"],
      ["vrf_id", "VRF"],
      ["vlan_id", "VLAN"],
      ["site_id", "Lokasyon"],
      ["used", "Atanan IP"],
      ["utilization", "Kullanım"],
    ],
    fields: [
      f("cidr", "Ağ bloğu / CIDR", {
        required: true,
        hint: "Örnek: 192.0.2.0/24 veya 2001:db8::/64",
      }),
      ref("vrf_id", "VRF", "vrfs", true),
      ref("vlan_id", "VLAN", "vlans"),
      ref("site_id", "Lokasyon", "sites"),
      f("description", "Açıklama"),
    ],
  },
  {
    key: "addresses",
    title: "IP adresleri",
    desc: "Rezervasyonlar, atamalar ve IPv4 / IPv6 adres planınız.",
    group: "IP adres yönetimi",
    icon: ListNumbers,
    resource: "addresses",
    columns: [
      ["address", "IP adresi"],
      ["hostname", "Hostname"],
      ["prefix_id", "Ağ bloğu"],
      ["vrf_id", "VRF"],
      ["status", "Durum"],
      ["interface_id", "Arayüz"],
    ],
    fields: [
      f("address", "IP adresi", { required: true }),
      ref("vrf_id", "VRF", "vrfs", true),
      ref("prefix_id", "Ağ bloğu", "prefixes", true),
      f("hostname", "Hostname"),
      options("status", "Durum", ["reserved", "active", "deprecated"]),
      ref("interface_id", "Arayüz", "interfaces"),
    ],
  },
  {
    key: "vlans",
    title: "VLAN alanları",
    desc: "Aynı VLAN numarasını farklı domainlerde güvenle yönetin.",
    group: "IP adres yönetimi",
    icon: Rows,
    resource: "vlans",
    columns: [
      ["vid", "VLAN ID"],
      ["name", "Ad"],
      ["domain", "Domain"],
    ],
    fields: [
      f("name", "VLAN adı", { required: true }),
      f("vid", "VLAN ID (1–4094)", { type: "number", required: true }),
      f("domain", "Domain", { default: "default", required: true }),
    ],
  },
  {
    key: "vrfs",
    title: "Yönlendirme alanları",
    desc: "Çakışan adres alanlarını VRF ile birbirinden ayırın.",
    group: "IP adres yönetimi",
    icon: Path,
    resource: "vrfs",
    columns: [
      ["name", "VRF"],
      ["description", "Açıklama"],
    ],
    fields: [
      f("name", "VRF adı", { required: true }),
      f("description", "Açıklama"),
    ],
  },
  {
    key: "discovery",
    title: "Ağ keşfi",
    desc: "Yalnızca sizin tanımladığınız sınırlar içinde keşfedin.",
    group: "Keşif & bağlantı",
    icon: Broadcast,
    resource: "scopes",
    columns: [
      ["name", "Keşif kapsamı"],
      ["cidr", "Yetkili ağ"],
      ["vrf_id", "VRF"],
      ["enabled", "Etkin"],
      ["interval_seconds", "Zamanlama"],
      ["last_run_at", "Son çalışma"],
    ],
    fields: [
      f("name", "Kapsam adı", { required: true }),
      f("cidr", "Yetkilendirilen CIDR", {
        required: true,
        hint: "Kapsamı kaydetmek bu ağda işlem yapma yetkiniz olduğunu belirtir.",
      }),
      ref("vrf_id", "VRF", "vrfs", true),
      ref("credential_id", "SNMPv3 erişim profili", "credentials", true),
      ref("site_id", "Lokasyon", "sites"),
      f("exclusions", "Hariç tutulan CIDR listesi", {
        type: "array",
        hint: "Her satıra bir CIDR.",
      }),
      f("seeds", "Açık hedef IP listesi", {
        type: "array",
        hint: "IPv6 ve 1024 adresten büyük ağlar için zorunlu. Her satıra bir IP.",
      }),
      f("enabled", "Kapsam etkin", { type: "checkbox", default: true }),
      f("interval_seconds", "Zamanlama (saniye)", {
        type: "number",
        default: 0,
        hint: "0: yalnızca manuel. Zamanlama en az 300 saniye.",
      }),
    ],
  },
  {
    key: "topology",
    title: "Bağlantı haritası",
    desc: "LLDP / CDP kanıtlarından oluşan ağınızın görünümü.",
    group: "Keşif & bağlantı",
    icon: Graph,
    resource: "links",
    columns: [
      ["device_id", "Kaynak cihaz"],
      ["interface_name", "Yerel port"],
      ["remote_name", "Komşu"],
      ["remote_port", "Uzak port"],
      ["source", "Kaynak"],
      ["confidence", "Güven"],
    ],
  },
  {
    key: "events",
    title: "Değişiklik günlüğü",
    desc: "IP, hostname, port, bağlantı ve alarm değişikliklerinin geçmişi.",
    group: "Keşif & bağlantı",
    icon: ClockCounterClockwise,
    resource: "events",
    columns: [
      ["created_at", "Zaman"],
      ["kind", "Olay"],
      ["device_id", "Cihaz"],
      ["message", "Açıklama"],
    ],
  },
  {
    key: "jobs",
    title: "Görev merkezi",
    desc: "Kuyruktan sonuca, her işlemin izini sürün.",
    group: "Keşif & bağlantı",
    icon: Lightning,
    resource: "jobs",
    columns: [
      ["kind", "Görev"],
      ["status", "Durum"],
      ["progress", "İlerleme"],
      ["attempts", "Deneme"],
      ["created_at", "Başlangıç"],
      ["error", "Açıklama"],
    ],
  },
  {
    key: "configuration",
    title: "Cihaz yedekleri",
    desc: "Yedeklerini ve sürüm geçmişini görüntülemek için bir cihaz seçin.",
    group: "Yedekler",
    icon: TerminalWindow,
    resource: "snapshots",
    columns: [
      ["device_id", "Cihaz"],
      ["created_at", "Yedek zamanı"],
      ["size_bytes", "Boyut"],
      ["changed", "Değişiklik"],
      ["fingerprint", "SHA-256"],
    ],
  },
  {
    key: "backup-changes",
    title: "Değişenler",
    desc: "Konfigürasyonu değişen cihaz yedekleri.",
    group: "Yedekler",
    icon: ArrowsClockwise,
  },
  {
    key: "backup-compare",
    title: "Karşılaştır",
    desc: "Önce cihazı, ardından aktif konfigürasyonla karşılaştırılacak yedeği seçin.",
    group: "Yedekler",
    icon: GitBranch,
  },
  {
    key: "backup-settings",
    title: "Yedekleme ayarları",
    desc: "Cihaz veya gruba zamanlama ve saklama sınırı uygulayın. 0: kapalı / sınırsız.",
    group: "Yedekler",
    icon: GearSix,
  },
  {
    key: "backup-groups",
    title: "Gruplandırma ayarları",
    desc: "Firewall, switch, controller ve backbone gibi kendi yedek gruplarınızı oluşturun.",
    group: "Yedekler",
    icon: Stack,
    resource: "backup-groups",
    columns: [
      ["name", "Grup"],
      ["description", "Açıklama"],
      ["interval_seconds", "Aralık (sn)"],
      ["retention_count", "Saklama sınırı"],
    ],
    fields: [
      f("name", "Grup adı", { required: true }),
      f("description", "Açıklama"),
      f("interval_seconds", "Yedekleme aralığı (saniye)", {
        type: "number",
        default: 0,
        hint: "0: kapalı. Etkinleştirmek için en az 300.",
      }),
      f("retention_count", "En fazla yedek sayısı", {
        type: "number",
        default: 0,
        hint: "Cihaz başına. 0: sınırsız. Eski yedekler bu sınıra göre silinir.",
      }),
    ],
  },
  {
    key: "monitoring",
    title: "Trafik gözlemevi",
    desc: "SNMPv3 sayaçlarından doğrulanmış giriş ve çıkış hızları.",
    group: "Operasyon",
    icon: ChartLineUp,
  },
  {
    key: "alerts",
    title: "Alarm akışı",
    desc: "Eşik aşımlarını ve iyileşmeleri bağlamıyla takip edin.",
    group: "Operasyon",
    icon: Bell,
    resource: "alerts",
    columns: [
      ["message", "Alarm"],
      ["severity", "Önem"],
      ["state", "Durum"],
      ["device_id", "Cihaz"],
      ["created_at", "Başlangıç"],
      ["acknowledged_at", "Görüldü"],
    ],
  },
  {
    key: "rules",
    title: "Alarm kuralları",
    desc: "Eşikler, bekleme süreleri ve iyileşme davranışları.",
    group: "Operasyon",
    icon: SlidersHorizontal,
    resource: "rules",
    columns: [
      ["name", "Kural"],
      ["metric", "Metrik"],
      ["threshold", "Eşik"],
      ["severity", "Önem"],
      ["duration_seconds", "Bekleme"],
      ["enabled", "Etkin"],
    ],
    fields: [
      f("name", "Kural adı", { required: true }),
      options("metric", "Metrik", [
        "availability",
        "utilization",
        "config_change",
        "no_data",
      ]),
      f("threshold", "Alarm eşiği", {
        type: "number",
        default: 80,
        hint: "Kullanım: yüzde; veri yok: saniye. Erişim/değişiklik için otomatik.",
      }),
      f("recovery_threshold", "İyileşme eşiği", {
        type: "number",
        default: 70,
      }),
      f("duration_seconds", "Bekleme (saniye)", { type: "number", default: 0 }),
      options("severity", "Önem", ["warning", "critical", "info"]),
      f("enabled", "Kural etkin", { type: "checkbox", default: true }),
    ],
  },
  {
    key: "credentials",
    title: "Erişim kasası",
    desc: "SNMPv3, SSH ve API sırları uygulama katmanında şifrelenir.",
    group: "Yönetim",
    icon: Key,
    resource: "credentials",
    columns: [
      ["name", "Profil adı"],
      ["protocol", "Protokol"],
      ["key_version", "Anahtar sürümü"],
      ["updated_at", "Güncelleme"],
    ],
    fields: [
      f("name", "Profil adı", { required: true }),
      options("protocol", "Protokol", ["snmpv3", "ssh", "rest"]),
      f("username", "Kullanıcı adı"),
      f("password", "SSH parolası", { type: "password" }),
      f("auth_key", "SNMP auth anahtarı", {
        type: "password",
        hint: "En az 8 karakter",
      }),
      f("priv_key", "SNMP AES privacy anahtarı", {
        type: "password",
        hint: "En az 8 karakter",
      }),
      options("auth_protocol", "SNMP kimlik algoritması", ["sha256", "sha1"]),
      f("token", "API Bearer token", { type: "password" }),
    ],
  },
  {
    key: "audit",
    title: "Denetim izi",
    desc: "Kim, ne zaman, hangi işlemi yaptı.",
    group: "Yönetim",
    icon: ShieldCheck,
    resource: "audit",
    columns: [
      ["created_at", "Zaman"],
      ["actor_id", "Kullanıcı"],
      ["action", "İşlem"],
      ["entity_type", "Kaynak"],
      ["summary", "Açıklama"],
    ],
  },
  {
    key: "users",
    title: "Ekip & yetkiler",
    desc: "Yönetici, operatör ve izleyici erişimlerini yönetin.",
    group: "Yönetim",
    icon: Users,
    resource: "users",
    columns: [
      ["display_name", "Kullanıcı"],
      ["email", "E-posta"],
      ["role", "Yetki"],
      ["is_active", "Etkin"],
    ],
    fields: [
      f("display_name", "Ad soyad", { required: true }),
      f("email", "E-posta", { type: "email", required: true }),
      f("password", "İlk parola", {
        type: "password",
        required: true,
        hint: "En az 12 karakter",
      }),
      options("role", "Rol", ["viewer", "operator", "admin"]),
    ],
  },
  {
    key: "settings",
    title: "Sistem odası",
    desc: "Platform sağlığı, saklama politikası ve hesabınız.",
    group: "Yönetim",
    icon: GearSix,
  },
];
const GROUPS = [
  "Genel bakış",
  "Envanter",
  "Yedekler",
  "IP adres yönetimi",
  "Keşif & bağlantı",
  "Operasyon",
  "Yönetim",
];
type Theme = "light" | "dark";
const readPref = (key: string) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};
const writePref = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Tercih kaydedilemezse oturum içinde geçerli kalır. */
  }
};
function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "dark" ? "#0b1220" : "#f8fafc");
  }, [theme]);
  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      writePref("netrix-theme", next);
      return next;
    });
  }, []);
  return [theme, toggle];
}
function ThemeToggle({
  theme,
  onToggle,
}: {
  theme: Theme;
  onToggle: () => void;
}) {
  return (
    <button
      className="icon-button theme-toggle"
      onClick={onToggle}
      aria-label={theme === "dark" ? "Açık temaya geç" : "Koyu temaya geç"}
      title={theme === "dark" ? "Açık tema" : "Koyu tema"}
    >
      {theme === "dark" ? <Sun size={19} /> : <Moon size={19} />}
    </button>
  );
}
const LABELS: Record<string, string> = {
  hostname_change: "Hostname değişimi",
  ip_assignment_change: "IP ataması",
  management_ip_change: "Yönetim adresi",
  link_observed: "Komşuluk gözlemi",
  device_discovered: "Yeni cihaz",
  device_identity_change: "Cihaz bilgileri güncellendi",
  port_change: "Port durumu",
  alert_firing: "Yeni alarm",
  alert_resolved: "Alarm iyileşmesi",
  active: "Aktif",
  planned: "Planlandı",
  maintenance: "Bakımda",
  retired: "Arşiv",
  reachable: "Yanıt verdi",
  unreachable: "Yanıt alınamadı",
  unknown: "Gözlem yok",
  switch: "Switch",
  router: "Router",
  firewall: "Firewall",
  server: "Sunucu",
  other: "Diğer",
  up: "Açık",
  down: "Kapalı",
  reserved: "Rezerve",
  deprecated: "Kullanım dışı",
  queued: "Kuyrukta",
  running: "Çalışıyor",
  succeeded: "Tamamlandı",
  partial: "Kısmi sonuç",
  failed: "Başarısız",
  cancelled: "İptal",
  pending: "Beklemede",
  firing: "Alarm",
  resolved: "İyileşti",
  critical: "Kritik",
  warning: "Uyarı",
  info: "Bilgi",
  discovery: "Keşif",
  backup: "Yedekleme",
  compare: "Aktif config karşılaştırması",
  monitor: "İzleme",
  identify: "Cihaz bilgisi sorgusu",
  test_snmp: "SNMPv3 bağlantı testi",
  test_ssh: "SSH bağlantı testi",
  test_api: "API bağlantı testi",
  availability: "Erişilebilirlik",
  utilization: "Port kullanımı (%)",
  config_change: "Konfigürasyon değişimi",
  no_data: "Veri yok (sn)",
  viewer: "İzleyici",
  operator: "Operatör",
  admin: "Yönetici",
};
export const tag = (v: string) => LABELS[v] || v;
export const date = (v: any) =>
  v
    ? new Date(v).toLocaleString("tr-TR", {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
export const speed = (v: any) =>
  v == null
    ? "—"
    : v >= 1e9
      ? (v / 1e9).toFixed(2) + " Gbps"
      : v >= 1e6
        ? (v / 1e6).toFixed(1) + " Mbps"
        : v >= 1e3
          ? (v / 1e3).toFixed(1) + " Kbps"
          : Math.round(v) + " bps";
export async function api(path: string, method = "GET", body?: any) {
  const response = await fetch("/api/v1" + path, {
    method,
    headers: { "Content-Type": "application/json", "X-Netrix-Request": "1" },
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return null;
  const data = await response
    .json()
    .catch(() => ({ detail: "Sunucu yanıtı okunamadı" }));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("netrix:session-expired"));
    const message = Array.isArray(data.detail)
      ? data.detail.map((x: any) => x.loc.join(".") + ": " + x.msg).join(" · ")
      : data.detail || "İşlem tamamlanamadı";
    throw new Error(message);
  }
  return data;
}
export function Badge({
  value,
  tone,
}: {
  value: any;
  tone?: "success" | "danger";
}) {
  const appearance =
    tone === "success"
      ? "active"
      : tone === "danger"
        ? "failed"
        : String(value);
  return (
    <span className={"badge " + appearance}>
      <i />
      {tag(String(value))}
    </span>
  );
}
function Brand({ small = false }: { small?: boolean }) {
  return (
    <div className="brand">
      <img src="/favicon.svg" alt="" width="32" height="32" />
      {!small && (
        <span className="brand-text">
          <b>NETRIX</b>
          <small>Ağ keşif ve yönetim</small>
        </span>
      )}
    </div>
  );
}
function Empty({
  title,
  desc,
  action,
  icon: Icon = GlobeHemisphereWest,
}: {
  title: string;
  desc: string;
  action?: React.ReactNode;
  icon?: IconType;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon size={26} />
      </div>
      <h3>{title}</h3>
      <p>{desc}</p>
      {action}
    </div>
  );
}
export function Dialog({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      className={"dialog " + (wide ? "wide" : "")}
      ref={dialog}
      onCancel={onClose}
    >
      <div className="dialog-header">
        <h2>{title}</h2>
        <button
          className="icon-button"
          aria-label="Pencereyi kapat"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
function Auth({
  onLogin,
  theme,
  onTheme,
}: {
  onLogin: (u: Row) => void;
  theme: Theme;
  onTheme: () => void;
}) {
  const [setup, setSetup] = useState(false);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [values, setValues] = useState<Row>({
    email: "",
    password: "",
    display_name: "",
    setup_token: "",
  });
  useEffect(() => {
    api("/auth/status")
      .then((d) => setSetup(d.setup_required))
      .catch((e) => setError(e.message))
      .finally(() => setChecking(false));
  }, []);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (setup) await api("/auth/setup", "POST", { ...values, role: "admin" });
      onLogin(
        await api("/auth/login", "POST", {
          email: values.email,
          password: values.password,
        }),
      );
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="auth-shell">
      <main className="auth-main">
        <header className="auth-top">
          <Brand />
          <ThemeToggle theme={theme} onToggle={onTheme} />
        </header>
        <div className="auth-card">
          <span className="eyebrow">
            {setup ? "İlk kurulum" : "Güvenli giriş"}
          </span>
          <h1>{setup ? "İlk bağlantıyı kuralım." : "Tekrar hoş geldiniz."}</h1>
          <p className="auth-lead">
            {setup
              ? "Yönetici hesabınızı oluşturun ve çalışma alanınızı başlatın."
              : "Ağ operasyon merkezinize kurumsal hesabınızla giriş yapın."}
          </p>
          {checking ? (
            <div className="loading">Sunucuya bağlanılıyor…</div>
          ) : (
            <form onSubmit={submit}>
              {setup && (
                <>
                  <label>
                    Kurulum anahtarı
                    <input
                      type="password"
                      autoComplete="off"
                      required
                      value={values.setup_token}
                      onChange={(e) =>
                        setValues({ ...values, setup_token: e.target.value })
                      }
                    />
                    <small>
                      Dağıtımda oluşturulan güvenli kurulum dosyanızdaki
                      anahtar.
                    </small>
                  </label>
                  <label>
                    Ad soyad
                    <input
                      autoComplete="name"
                      required
                      value={values.display_name}
                      onChange={(e) =>
                        setValues({ ...values, display_name: e.target.value })
                      }
                    />
                  </label>
                </>
              )}
              <label>
                E-posta
                <input
                  type="email"
                  autoComplete="username"
                  required
                  value={values.email}
                  onChange={(e) =>
                    setValues({ ...values, email: e.target.value })
                  }
                  placeholder="adiniz@kurumunuz.com"
                />
              </label>
              <label>
                Parola
                <input
                  type="password"
                  autoComplete={setup ? "new-password" : "current-password"}
                  minLength={setup ? 12 : 1}
                  required
                  value={values.password}
                  onChange={(e) =>
                    setValues({ ...values, password: e.target.value })
                  }
                  placeholder={setup ? "En az 12 karakter" : "Parolanız"}
                />
              </label>
              {error && (
                <div className="error" role="alert">
                  <WarningCircle size={20} />
                  {error}
                </div>
              )}
              <button className="primary" disabled={busy}>
                {busy
                  ? "Bağlanılıyor…"
                  : setup
                    ? "Çalışma alanını oluştur"
                    : "Çalışma alanına gir"}
                <ArrowRight size={19} />
              </button>
            </form>
          )}
          <div className="secure-note">
            <LockKey size={16} /> Şifreli bağlantı · Merkezi yetkilendirme
          </div>
        </div>
        <footer className="auth-version">
          NETRIX v1.0 · Network Intelligence, Discovery &amp; Management
        </footer>
      </main>
      <aside className="auth-visual" aria-hidden="true">
        <svg className="auth-graph" viewBox="0 0 480 360">
          <g className="auth-links">
            <path d="M240 70L110 170M240 70L370 170M110 170L80 290M110 170L190 290M370 170L300 290M370 170L420 290M240 70V180M240 180L190 290M240 180L300 290" />
          </g>
          <g className="auth-nodes">
            <rect x="218" y="48" width="44" height="44" rx="10" />
            <rect x="90" y="150" width="40" height="40" rx="10" />
            <rect x="350" y="150" width="40" height="40" rx="10" />
            <circle cx="240" cy="180" r="10" />
            {[80, 190, 300, 420].map((x) => (
              <circle key={x} cx={x} cy="290" r="8" />
            ))}
          </g>
        </svg>
        <div className="auth-modules">
          {[
            [
              TreeStructure,
              "IPAM & keşif",
              "Subnet, VLAN ve LLDP/CDP komşulukları",
            ],
            [
              TerminalWindow,
              "Konfigürasyon",
              "Şifreli sürüm arşivi ve satır farkları",
            ],
            [ChartLineUp, "İzleme", "SNMPv3 trafik, port durumu ve alarmlar"],
          ].map(([Icon, title, desc]: any) => (
            <div key={title}>
              <Icon size={20} />
              <span>
                <b>{title}</b>
                <small>{desc}</small>
              </span>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
function ResourceForm({
  page,
  row,
  refs,
  onClose,
  onSaved,
}: {
  page: Page;
  row?: Row;
  refs: Record<string, Row[]>;
  onClose: () => void;
  onSaved: (saved: Row) => void;
}) {
  const [values, setValues] = useState<Row>(() =>
    Object.fromEntries(
      (page.fields || []).map((field) => [
        field.key,
        row?.[field.key] ??
          field.default ??
          (field.type === "checkbox"
            ? false
            : field.type === "array"
              ? []
              : field.required && field.ref
                ? refs[field.ref]?.[0]?.id || ""
                : ""),
      ]),
    ),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fields = (page.fields || [])
    .filter(
      (field) =>
        field.key !== "ssh_trust_host_key" || values.adapter !== "rest",
    )
    .filter(
      (field) =>
        page.key !== "devices" ||
        !["identity_path", "config_path"].includes(field.key) ||
        values.adapter === "rest",
    )
    .filter(
      (field) =>
        page.key !== "credentials" ||
        ![
          "username",
          "password",
          "auth_key",
          "priv_key",
          "auth_protocol",
          "token",
        ].includes(field.key) ||
        (values.protocol === "snmpv3" &&
          ["username", "auth_key", "priv_key", "auth_protocol"].includes(
            field.key,
          )) ||
        (values.protocol === "ssh" &&
          ["username", "password"].includes(field.key)) ||
        (values.protocol === "rest" && field.key === "token"),
    );
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      let data = { ...values };
      for (const field of page.fields || []) {
        if (field.ref && !data[field.key]) data[field.key] = null;
        if (field.type === "number") data[field.key] = Number(data[field.key]);
        if (field.type === "array")
          data[field.key] = data[field.key]
            .map((v: string) => v.trim())
            .filter(Boolean);
      }
      if (page.key === "credentials") {
        const secret: Row = {};
        for (const key of [
          "username",
          "password",
          "auth_key",
          "priv_key",
          "auth_protocol",
          "token",
        ]) {
          secret[key] = data[key];
          delete data[key];
        }
        data.secret = secret;
      }
      const saved = await api(
        "/" + page.resource + (row ? "/" + row.id : ""),
        row ? "PUT" : "POST",
        data,
      );
      onSaved(saved);
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={(row ? "Kaydı düzenle" : "Yeni kayıt") + " · " + page.title}
      onClose={onClose}
    >
      <form onSubmit={submit}>
        {page.key === "devices" && (
          <div className="info-note">
            <Info size={20} />
            <p>
              Kaydettiğinizde üretici, cihaz türü ve model, atanan SNMPv3 veya
              SSH/API profiliyle yetkili kapsam içinde sorgulanır. Cihazdan
              okunabilen alanlar güncellenir; okunamayan alanlarda girdiğiniz
              bilgiler korunur.
            </p>
          </div>
        )}
        <div className="form-grid">
          {fields.map((field) => (
            <label
              key={field.key}
              className={"form-field" + (field.type === "array" ? " full" : "")}
            >
              <span className="field-title">
                {field.label}
                {field.required && <span className="required"> *</span>}
              </span>
              {field.type === "checkbox" ? (
                <span className="checkbox-control">
                  <input
                    type="checkbox"
                    aria-label={field.label}
                    aria-describedby={
                      field.hint ? `hint-${field.key}` : undefined
                    }
                    checked={!!values[field.key]}
                    onChange={(e) =>
                      setValues({ ...values, [field.key]: e.target.checked })
                    }
                  />
                  <span aria-hidden="true">
                    {values[field.key] ? "Etkin" : "Kapalı"}
                  </span>
                </span>
              ) : (
                <>
                  {field.type === "select" ? (
                    <select
                      required={field.required}
                      value={values[field.key] || ""}
                      onChange={(e) =>
                        setValues({ ...values, [field.key]: e.target.value })
                      }
                    >
                      {field.ref && <option value="">Seçiniz</option>}
                      {(field.ref
                        ? (refs[field.ref] || [])
                            .filter(
                              (r) =>
                                page.key !== "devices" ||
                                ![
                                  "snmp_credential_id",
                                  "config_credential_id",
                                ].includes(field.key) ||
                                (field.key === "snmp_credential_id"
                                  ? r.protocol === "snmpv3"
                                  : r.protocol ===
                                    (values.adapter === "rest"
                                      ? "rest"
                                      : "ssh")),
                            )
                            .map((r) => [r.id, r.name || r.cidr || r.address])
                        : field.options || []
                      ).map((option: any) => {
                        const [key, label] = Array.isArray(option)
                          ? option
                          : [option, tag(option)];
                        return (
                          <option key={key} value={key}>
                            {label}
                          </option>
                        );
                      })}
                    </select>
                  ) : field.type === "array" ? (
                    <textarea
                      rows={3}
                      value={values[field.key].join("\n")}
                      onChange={(e) =>
                        setValues({
                          ...values,
                          [field.key]: e.target.value.split("\n"),
                        })
                      }
                    />
                  ) : (
                    <input
                      type={field.type || "text"}
                      required={field.required}
                      autoComplete={
                        field.type === "password" ? "new-password" : "off"
                      }
                      value={values[field.key] ?? ""}
                      onChange={(e) =>
                        setValues({ ...values, [field.key]: e.target.value })
                      }
                    />
                  )}
                </>
              )}
              {field.hint && (
                <small id={`hint-${field.key}`}>{field.hint}</small>
              )}
            </label>
          ))}
        </div>
        {page.key === "credentials" && (
          <p className="form-note">
            <ShieldCheck size={16} /> Sırlar kayıttan sonra okunamaz. Düzenleme
            mevcut sırları yenileriyle değiştirir.
          </p>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div className="dialog-footer">
          <button type="button" className="secondary" onClick={onClose}>
            Vazgeç
          </button>
          <button className="primary" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Kaydı kaydet"}
            <Check size={17} />
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function Topology({
  devices,
  links,
  onDevice,
  compact = false,
}: {
  devices: Row[];
  links: Row[];
  onDevice: (row: Row) => void;
  compact?: boolean;
}) {
  const nodes = devices.slice(0, 12);
  const positions = nodes.map((_, i) => ({
    x:
      400 +
      Math.cos((i * 2 * Math.PI) / Math.max(nodes.length, 1) - Math.PI / 2) *
        (nodes.length > 1 ? 240 : 0),
    y:
      180 +
      Math.sin((i * 2 * Math.PI) / Math.max(nodes.length, 1) - Math.PI / 2) *
        110,
  }));
  if (!nodes.length)
    return (
      <div className={"topology-empty " + (compact ? "compact" : "")}>
        <svg className="orbit-grid" viewBox="0 0 800 350" aria-hidden="true">
          <defs>
            <pattern
              id="dots"
              width="22"
              height="22"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="1" cy="1" r="1" />
            </pattern>
          </defs>
          <rect width="800" height="350" fill="url(#dots)" />
          <ellipse cx="400" cy="175" rx="220" ry="90" />
          <ellipse cx="400" cy="175" rx="145" ry="145" />
          <path d="M150 100L400 175L650 90M400 175L560 290M400 175L210 275" />
          {[
            [150, 100],
            [650, 90],
            [560, 290],
            [210, 275],
          ].map(([x, y], i) => (
            <g key={i}>
              <rect x={x - 12} y={y - 12} width="24" height="24" rx="6" />
              <circle cx={x} cy={y} r="3" />
            </g>
          ))}
        </svg>
        <div className="network-seed">
          <Graph size={26} />
          <span>İlk sinyali bekliyor</span>
          <small>Keşfedilen bağlantılar burada hayat bulacak.</small>
        </div>
        <span className="diagram-label">
          Başlangıç şeması · henüz cihaz yok
        </span>
      </div>
    );
  return (
    <div className="topology-real">
      <svg
        viewBox="0 0 800 370"
        role="group"
        aria-label={`${devices.length} cihaz, ${links.length} gözlemlenen komşuluk`}
      >
        <defs>
          <pattern
            id="networkdots"
            width="22"
            height="22"
            patternUnits="userSpaceOnUse"
          >
            <circle cx="1" cy="1" r="1" />
          </pattern>
        </defs>
        <rect width="800" height="370" fill="url(#networkdots)" />
        {links.map((link, i) => {
          const from = nodes.findIndex((n) => n.id === link.device_id);
          const to = nodes.findIndex((n) => n.id === link.remote_device_id);
          if (from < 0) return null;
          const a = positions[from];
          const b = to >= 0 ? positions[to] : { x: a.x + 60, y: a.y + 45 };
          return (
            <g key={i}>
              <line
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                className="topo-link"
                strokeDasharray={link.confidence < 0.9 ? "5 6" : undefined}
              />
              {to < 0 && (
                <>
                  <circle cx={b.x} cy={b.y} r="6" className="topo-remote" />
                  <text x={b.x + 10} y={b.y + 4} className="svg-label">
                    {link.remote_name}
                  </text>
                </>
              )}
            </g>
          );
        })}
        {nodes.map((node, i) => (
          <g
            className="network-node"
            key={node.id}
            onClick={() => onDevice(node)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") onDevice(node);
            }}
            tabIndex={0}
            role="button"
            aria-label={node.name + " cihazını görüntüle"}
          >
            <title>{node.name + " · " + node.management_ip}</title>
            <rect
              x={positions[i].x - 23}
              y={positions[i].y - 23}
              width="46"
              height="46"
              rx="12"
              className={
                "topo-node " +
                (node.reachability === "reachable" ? "reachable" : "")
              }
            />
            <path
              d={`M${positions[i].x - 9} ${positions[i].y - 6}h18v12h-18z`}
              className="topo-glyph"
            />
            <text
              x={positions[i].x}
              y={positions[i].y + 43}
              textAnchor="middle"
              className="svg-node-label"
            >
              {node.name.slice(0, 24)}
            </text>
            <text
              x={positions[i].x}
              y={positions[i].y + 60}
              textAnchor="middle"
              className="svg-label"
            >
              {node.management_ip}
            </text>
          </g>
        ))}
      </svg>
      {devices.length > 12 && (
        <small>
          Haritada ilk 12 cihaz gösteriliyor. Tüm ilişkiler aşağıdaki tabloda.
        </small>
      )}
    </div>
  );
}
function Overview({
  dashboard,
  refs,
  navigate,
  onAdd,
  onDevice,
}: {
  dashboard: Row;
  refs: Record<string, Row[]>;
  navigate: (key: string) => void;
  onAdd: (key: string) => void;
  onDevice: (row: Row) => void;
}) {
  const c = dashboard.counts || {};
  const steps = [
    {
      title: "Erişim profilini ekleyin",
      desc: "SNMPv3, SSH veya API",
      key: "credentials",
      done: !!refs.credentials?.length,
    },
    {
      title: "Ağınızın sınırlarını belirleyin",
      desc: "Yetkilendirilmiş keşif kapsamı",
      key: "discovery",
      done: !!refs.scopes?.length,
    },
    {
      title: "İlk keşfinizi başlatın",
      desc: "Cihazlar ve bağlantılar",
      key: "discovery",
      done: !!c.successful_discoveries,
    },
  ];
  return (
    <>
      <div className="overview-heading">
        <div>
          <span className="eyebrow">Operasyon panoraması</span>
          <h1>Ağınızın bütün resmi</h1>
          <p>Bağlantıları anlayın, değişimi yakalayın, güvenle yönetin.</p>
        </div>
        <div className="day-marker">
          <Clock size={18} />
          <span>
            {new Date().toLocaleDateString("tr-TR", {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}
          </span>
        </div>
      </div>
      <div className="metrics">
        {[
          {
            label: "Envanterdeki cihaz",
            value: c.devices || 0,
            note: (c.reachable || 0) + " cihazdan başarılı gözlem",
            icon: HardDrives,
            key: "devices",
          },
          {
            label: "IP adres alanı",
            value: c.prefixes || 0,
            note: (c.addresses || 0) + " adres kayıt altında",
            icon: TreeStructure,
            key: "prefixes",
          },
          {
            label: "Konfigürasyon sürümü",
            value: c.snapshots || 0,
            note: "Şifreli sürüm arşivi",
            icon: ShieldCheck,
            key: "configuration",
          },
          {
            label: "Aktif alarm",
            value: c.firing_alerts || 0,
            note: c.monitored
              ? c.monitored + " cihaz izleniyor"
              : "Henüz izlenen cihaz yok",
            icon: Bell,
            key: "alerts",
          },
        ].map((m, i) => (
          <button
            className={"metric metric-" + i}
            key={m.key}
            onClick={() => navigate(m.key)}
          >
            <div>
              <span className="metric-icon">
                <m.icon size={20} />
              </span>
              <span>{m.label}</span>
            </div>
            <strong>{m.value.toLocaleString("tr-TR")}</strong>
            <footer>
              {m.note}
              <ArrowUpRight size={16} />
            </footer>
          </button>
        ))}
      </div>
      <div className="dashboard-main">
        <section className="panel map-panel">
          <header className="panel-header">
            <div>
              <span className="eyebrow">Keşif</span>
              <h2>Bağlantı panoraması</h2>
            </div>
            <button
              className="text-button"
              onClick={() => navigate("topology")}
            >
              Haritayı aç <ArrowUpRight size={16} />
            </button>
          </header>
          <Topology
            devices={refs.devices || []}
            links={refs.links || []}
            onDevice={onDevice}
            compact
          />
          <footer className="map-footer">
            <span>
              <i className="legend-dot mint-bg" />
              Cihazlar <b>{c.devices || 0}</b>
            </span>
            <span>
              <i className="legend-line" />
              Gözlemlenen komşuluk <b>{refs.links?.length || 0}</b>
            </span>
            <span className="muted">LLDP / CDP</span>
          </footer>
        </section>
        <section className="panel setup-panel">
          <span className="eyebrow">Başlangıç</span>
          <h2>
            {c.devices
              ? "Operasyona devam edin."
              : "Büyük resim, ilk bağlantıyla başlar."}
          </h2>
          <p>
            {c.devices
              ? "Ağınızı keşif, yedekleme ve izleme araçlarıyla yönetin."
              : "Üç küçük adımla ağınızı görünür hale getirin."}
          </p>
          <div className="setup-steps">
            {steps.map((step, i) => (
              <button
                onClick={() =>
                  step.done ? navigate(step.key) : onAdd(step.key)
                }
                key={i}
              >
                <span className={"step-number " + (step.done ? "done" : "")}>
                  {step.done ? (
                    <Check size={15} />
                  ) : (
                    String(i + 1).padStart(2, "0")
                  )}
                </span>
                <span>
                  <b>{step.title}</b>
                  <small>{step.desc}</small>
                </span>
                <ArrowUpRight size={15} />
              </button>
            ))}
          </div>
          <div className="setup-note">
            <ShieldCheck size={16} /> Her keşif, sizin belirlediğiniz sınırlar
            içinde.
          </div>
        </section>
      </div>
      <div className="dashboard-bottom">
        <section className="panel">
          <header className="panel-header">
            <div>
              <span className="eyebrow">Takip</span>
              <h2>Son hareketler</h2>
            </div>
            <button className="text-button" onClick={() => navigate("jobs")}>
              Görev merkezi <ArrowUpRight size={16} />
            </button>
          </header>
          {refs.events?.length ? (
            <div className="activity-list">
              {refs.events.slice(0, 4).map((event) => (
                <div key={event.id}>
                  <span className="activity-dot" />
                  <div>
                    <b>{event.message}</b>
                    <small>
                      {date(event.created_at)} · {event.kind}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="quiet-state">
              <ClockCounterClockwise size={22} />
              <div>
                <b>Temiz bir başlangıç.</b>
                <p>Keşifler, değişiklikler ve ağ olayları burada yer alacak.</p>
              </div>
            </div>
          )}
        </section>
        <section className="quick-card">
          <span className="eyebrow">Sıradaki adım</span>
          <h2>Her cihazı tanıyın.</h2>
          <p>
            Merkezi envanterinizi oluşturarak ağınıza bir kimlik kazandırın.
          </p>
          <button className="secondary" onClick={() => onAdd("devices")}>
            <Plus size={17} /> Cihaz ekle
          </button>
        </section>
      </div>
    </>
  );
}
function ConnectionTestDialog({
  device,
  onClose,
}: {
  device: Row;
  onClose: () => void;
}) {
  const [options, setOptions] = useState<Row | null>(null);
  const [selected, setSelected] = useState("");
  const [job, setJob] = useState<Row | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [loadKey, setLoadKey] = useState(0);
  const pending =
    starting || (!!job && ["queued", "running"].includes(job.status));
  useEffect(() => {
    let active = true;
    api(`/devices/${device.id}/connection-tests`)
      .then((data) => {
        if (!active) return;
        setOptions(data);
        setSelected((current) =>
          data.protocols.some((p: Row) => p.protocol === current && p.enabled)
            ? current
            : data.protocols.find((p: Row) => p.enabled)?.protocol || "",
        );
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [device.id, loadKey]);
  useEffect(() => {
    if (!job?.id) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const current = await api(`/jobs/${job.id}`);
        if (!active) return;
        setJob(current);
        setError("");
        if (["queued", "running"].includes(current.status))
          timer = setTimeout(poll, 1000);
      } catch (e: any) {
        if (active) {
          setError(e.message);
          timer = setTimeout(poll, 3000);
        }
      }
    };
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [job?.id]);
  const current = options?.protocols.find((p: Row) => p.protocol === selected);
  return (
    <Dialog title={`Bağlantı testi · ${device.name}`} onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (!selected || !current?.enabled || !options?.can_test || pending)
            return;
          setStarting(true);
          setError("");
          setJob(null);
          try {
            setJob(
              await api(`/devices/${device.id}/connection-tests`, "POST", {
                protocol: selected,
              }),
            );
          } catch (e: any) {
            setError(e.message);
            setLoadKey((n) => n + 1);
          } finally {
            setStarting(false);
          }
        }}
      >
        <p className="muted">
          Kayıtlı erişim profiliyle yalnızca seçtiğiniz protokol test edilir.
        </p>
        <p className="mono">{options?.target || device.management_ip}</p>
        {!options && !error && (
          <div role="status">Erişim profilleri yükleniyor…</div>
        )}
        {options && (
          <>
            <fieldset className="connection-test-protocols">
              <legend>Test protokolü</legend>
              {options.protocols.map((option: Row) => (
                <label
                  key={option.protocol}
                  className={
                    !option.enabled
                      ? "unavailable"
                      : selected === option.protocol
                        ? "selected"
                        : ""
                  }
                >
                  <span>
                    <input
                      type="radio"
                      name="test-protocol"
                      value={option.protocol}
                      aria-label={option.label}
                      checked={selected === option.protocol}
                      disabled={!option.enabled || pending}
                      onChange={() => {
                        setSelected(option.protocol);
                        setJob(null);
                        setError("");
                      }}
                    />
                    <b>{option.label}</b>
                  </span>
                  <small>
                    {option.enabled ? "Profil atanmış" : "Profil atanmadı"}
                  </small>
                </label>
              ))}
            </fieldset>
            {current && (
              <div className="info-note">
                <PlugsConnected size={20} aria-hidden="true" />
                <p>
                  <b>{current.profile_name}</b>
                  <br />
                  {selected === "snmpv3" ? "UDP" : "TCP"} {current.port}
                  {selected === "rest" && (
                    <span className="mono"> · {current.path}</span>
                  )}
                </p>
              </div>
            )}
            {!options.can_test && (
              <p role="status" className="muted">
                {options.reason}
              </p>
            )}
          </>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {!options && error && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setError("");
              setLoadKey((n) => n + 1);
            }}
          >
            Profilleri yeniden yükle
          </button>
        )}
        {(starting || job) && (
          <section
            className="connection-test-result"
            data-state={pending ? "pending" : job?.status}
            role="status"
            aria-live="polite"
          >
            <h3>
              {pending
                ? job?.status === "running"
                  ? "Cihazda test çalışıyor…"
                  : "Test sıraya alınıyor…"
                : job?.status === "cancelled"
                  ? "Test iptal edildi"
                  : job?.status === "succeeded" && job?.result?.success === true
                    ? "Bağlantı başarılı"
                    : "Bağlantı başarısız"}
            </h3>
            <p>
              {pending
                ? "Sonuç cihaz yanıt verdikten sonra burada görünecek."
                : job?.result?.message || job?.error || "Test tamamlanmadı."}
            </p>
            {!pending && job?.result?.checked_at && (
              <p className="muted">
                {date(job.result.checked_at)} · {job.result.duration_ms} ms ·
                Port {job.result.port}
              </p>
            )}
          </section>
        )}
        <div className="dialog-footer">
          <button type="button" className="secondary" onClick={onClose}>
            Kapat
          </button>
          {pending && job && (
            <button
              type="button"
              className="secondary"
              disabled={job.cancel_requested}
              onClick={async () => {
                try {
                  setJob(await api(`/jobs/${job.id}/cancel`, "POST"));
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            >
              {job.cancel_requested ? "İptal ediliyor…" : "Testi iptal et"}
            </button>
          )}
          <button
            className="primary"
            disabled={!current?.enabled || !options?.can_test || pending}
          >
            <PlugsConnected size={18} aria-hidden="true" />
            {pending ? "Test ediliyor…" : "Test et"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function Traffic({
  refs,
  refresh,
}: {
  refs: Record<string, Row[]>;
  refresh: number;
}) {
  const [device, setDevice] = useState("");
  const [iface, setIface] = useState("");
  const [hours, setHours] = useState("24");
  const [items, setItems] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [limited, setLimited] = useState(false);
  const loadedQuery = useRef("");
  const ports = (refs.interfaces || []).filter(
    (p) => !device || p.device_id === device,
  );
  const selected = iface || ports[0]?.id;
  useEffect(() => {
    if (!selected) {
      loadedQuery.current = "";
      setItems([]);
      setLoading(false);
      return;
    }
    let active = true;
    const queryKey = JSON.stringify([selected, hours]);
    // Keep the current chart visible while refreshing the same selection.
    setLoading(loadedQuery.current !== queryKey);
    api(`/traffic?interface_id=${selected}&hours=${hours}`)
      .then((d) => {
        if (!active) return;
        loadedQuery.current = queryKey;
        setItems(d.items);
        setLimited(d.limited);
        setError("");
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selected, hours, refresh]);
  const valid = items.filter((i) => i.quality === "valid");
  const last = items[items.length - 1];
  const max = Math.max(
    ...valid.flatMap((i) => [i.in_bps || 0, i.out_bps || 0]),
    1,
  );
  const points = (key: string) => {
    if (!items.length) return "";
    const start = new Date(items[0].created_at).getTime();
    const end = new Date(items[items.length - 1].created_at).getTime();
    let drawing = false;
    return items
      .map((i) => {
        if (i.quality !== "valid" || i[key] == null) {
          drawing = false;
          return "";
        }
        const command = drawing ? "L" : "M";
        drawing = true;
        return `${command}${55 + ((new Date(i.created_at).getTime() - start) / Math.max(end - start, 1)) * 825},${240 - (i[key] / max) * 190}`;
      })
      .join(" ");
  };
  return (
    <>
      <div className="toolbar traffic-toolbar">
        <label>
          Cihaz
          <select
            value={device}
            onChange={(e) => {
              setDevice(e.target.value);
              setIface("");
            }}
          >
            <option value="">Tüm cihazlar</option>
            {refs.devices?.map((d) => (
              <option value={d.id} key={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Arayüz
          <select
            value={selected || ""}
            onChange={(e) => setIface(e.target.value)}
          >
            {ports.length ? (
              ports.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))
            ) : (
              <option value="">Henüz arayüz yok</option>
            )}
          </select>
        </label>
        <label>
          Zaman aralığı
          <select value={hours} onChange={(e) => setHours(e.target.value)}>
            <option value="1">Son 1 saat</option>
            <option value="24">Son 24 saat</option>
            <option value="168">Son 7 gün</option>
          </select>
        </label>
      </div>
      <div className="traffic-stats">
        {[
          { label: "Giriş", value: speed(last?.in_bps), icon: ArrowDown },
          { label: "Çıkış", value: speed(last?.out_bps), icon: ArrowUp },
          {
            label: "Örnek kalitesi",
            value: last
              ? last.quality === "valid"
                ? "Doğrulandı"
                : tag(last.quality)
              : "Veri yok",
            icon: CheckCircle,
          },
          { label: "Son gözlem", value: date(last?.created_at), icon: Clock },
        ].map((s) => (
          <div className="panel" key={s.label}>
            <s.icon size={20} />
            <span className="eyebrow">{s.label}</span>
            <strong>{s.value}</strong>
          </div>
        ))}
      </div>
      <section className="panel chart-panel">
        <header className="panel-header">
          <div>
            <span className="eyebrow">Trafik · bit/saniye</span>
            <h2>Bağlantınızın ritmi</h2>
          </div>
          <div className="chart-legend">
            <span>
              <i className="legend-dot mint-bg" />
              Giriş
            </span>
            <span>
              <i className="legend-dot blue-bg" />
              Çıkış
            </span>
          </div>
        </header>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {loading ? (
          <div className="loading">Örnekler yükleniyor…</div>
        ) : valid.length > 1 ? (
          <svg
            viewBox="0 0 920 290"
            className="traffic-chart"
            role="img"
            aria-label="Arayüz giriş ve çıkış trafik hızları"
          >
            <title>{valid.length} doğrulanmış trafik örneği</title>
            {[0, 1, 2, 3, 4].map((i) => (
              <g key={i}>
                <line
                  x1="55"
                  y1={50 + i * 47.5}
                  x2="880"
                  y2={50 + i * 47.5}
                  className="chart-grid"
                  strokeDasharray="3 5"
                />
                <text x="5" y={55 + i * 47.5}>
                  {speed(max * (1 - i / 4))}
                </text>
              </g>
            ))}
            <path d={points("in_bps")} className="chart-in" strokeWidth="2.5" />
            <path d={points("out_bps")} className="chart-out" strokeWidth="2" />
            <text x="55" y="275">
              {date(items[0].created_at)}
            </text>
            <text x="880" y="275" textAnchor="end">
              {date(items[items.length - 1].created_at)}
            </text>
          </svg>
        ) : (
          <Empty
            icon={ChartLineUp}
            title={
              items.length
                ? "İlk ölçüm alındı. Bir örnek daha gerekli."
                : "Henüz trafik gözlemi yok."
            }
            desc="Bir cihaza SNMPv3 profili atayın ve izlemeyi etkinleştirin. Geçerli iki sayaç örneğinden sonra trafik hızları hesaplanır."
          />
        )}
        {limited && (
          <div className="info-note">
            <Info size={16} />
            <p>
              Seçilen aralıktaki en son 2000 örnek gösteriliyor. Daha fazla
              ayrıntı için zaman aralığını daraltın.
            </p>
          </div>
        )}
        <footer className="chart-note">
          <Info size={15} /> Eksik veri sıfır trafik olarak gösterilmez. Sayaç
          sıfırlanmaları ve geçersiz aralıklar hesaplamadan çıkarılır.
        </footer>
      </section>
      {items.length > 0 && (
        <section className="panel table-panel">
          <div className="panel-header">
            <h2>Son örnekler</h2>
            <span className="muted">
              Son {Math.min(10, items.length)} kayıt
            </span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Zaman</th>
                  <th>Giriş</th>
                  <th>Çıkış</th>
                  <th>Giriş hatası</th>
                  <th>Çıkış hatası</th>
                  <th>Düşen (giriş)</th>
                  <th>Düşen (çıkış)</th>
                  <th>Kalite</th>
                </tr>
              </thead>
              <tbody>
                {items
                  .slice(-10)
                  .reverse()
                  .map((i) => (
                    <tr key={i.id}>
                      <td>{date(i.created_at)}</td>
                      <td>{speed(i.in_bps)}</td>
                      <td>{speed(i.out_bps)}</td>
                      <td>{i.in_errors}</td>
                      <td>{i.out_errors}</td>
                      <td>{i.quality}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
function Settings({ onLogout }: { onLogout: () => void }) {
  const [system, setSystem] = useState<Row>({});
  const [error, setError] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  useEffect(() => {
    api("/system")
      .then(setSystem)
      .catch((e) => setError(e.message));
  }, []);
  return (
    <div className="settings-grid">
      <section className="panel">
        <header className="panel-header">
          <h2>Platform durumu</h2>
          <span className="mono">v{system.version || "—"}</span>
        </header>
        <dl className="system-list">
          {[
            ["Veritabanı", system.database],
            ["Redis", system.redis],
            ["Worker", system.worker ? "Bağlı" : "Heartbeat bekleniyor"],
            [
              "Zamanlayıcı",
              system.scheduler ? "Bağlı" : "Heartbeat bekleniyor",
            ],
            ["Trafik saklama", (system.retention_days || "—") + " gün"],
            ["Dış adres", system.public_url],
          ].map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v || "—"}</dd>
            </div>
          ))}
        </dl>
        <div className="info-note">
          <ShieldCheck size={20} />
          <p>
            SSH bağlantıları kayıtlı host anahtarlarını doğrular. Cihaz formunda
            “Anahtara güven” seçiliyse o cihazın sunduğu anahtar kabul edilir.
          </p>
        </div>
      </section>
      <section className="panel">
        <header className="panel-header">
          <h2>Parolanızı değiştirin</h2>
          <Key size={20} />
        </header>
        <form
          className="settings-form"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/auth/password", "POST", {
                current_password: current,
                new_password: next,
              });
              onLogout();
            } catch (e: any) {
              setError(e.message);
            }
          }}
        >
          <label>
            Mevcut parola
            <input
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </label>
          <label>
            Yeni parola
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={12}
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <small>
              En az 12 karakter. Değişiklikten sonra bütün oturumlar kapanır.
            </small>
          </label>
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          <button className="primary">
            Parolayı güncelle
            <ArrowRight size={17} />
          </button>
        </form>
      </section>
    </div>
  );
}
function App() {
  const [user, setUser] = useState<Row | null>(null);
  const [boot, setBoot] = useState(true);
  const [current, setCurrent] = useState(
    () => location.hash.slice(1) || "overview",
  );
  const [group, setGroup] = useState(
    () =>
      PAGES.find((p) => p.key === (location.hash.slice(1) || "overview"))
        ?.group || "Genel bakış",
  );
  const [refs, setRefs] = useState<Record<string, Row[]>>({});
  const [dashboard, setDashboard] = useState<Row>({});
  const [items, setItems] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const search = useDeferredValue(query);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(false);
  const loadedQuery = useRef("");
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [connected, setConnected] = useState(false);
  const [form, setForm] = useState<{ page: Page; row?: Row } | null>(null);
  const [detail, setDetail] = useState<Row | null>(null);
  const [config, setConfig] = useState<{
    title: string;
    content: string;
  } | null>(null);
  const [command, setCommand] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [jobModal, setJobModal] = useState(false);
  const [jobKind, setJobKind] = useState("backup");
  const [jobTarget, setJobTarget] = useState("");
  const [jobBusy, setJobBusy] = useState(false);
  const [testDevice, setTestDevice] = useState<Row | null>(null);
  const [theme, toggleTheme] = useTheme();
  const [collapsed, setCollapsed] = useState(
    () => readPref("netrix-sidebar") === "collapsed",
  );
  const [drawer, setDrawer] = useState(false);
  const [closedGroups, setClosedGroups] = useState<string[]>([]);
  const page = PAGES.find((p) => p.key === current) || PAGES[0];
  useEffect(() => {
    // Komut paleti veya bağlantıyla gidilen sayfanın menüsü görünür kalsın.
    setClosedGroups((groups) => groups.filter((g) => g !== page.group));
  }, [current, page.group]);
  useEffect(() => {
    const expired = () => setUser(null);
    window.addEventListener("netrix:session-expired", expired);
    return () => window.removeEventListener("netrix:session-expired", expired);
  }, []);
  const canWrite = user?.role === "admin" || user?.role === "operator";
  const isAdmin = user?.role === "admin";
  const notify = useCallback((message: string) => {
    setToast(message);
  }, []);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 8000);
      return () => clearTimeout(t);
    }
  }, [toast]);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  const navigate = useCallback((key: string) => {
    const p = PAGES.find((p) => p.key === key);
    if (!p) return;
    location.hash = key;
    setCurrent(key);
    setGroup(p.group);
    setOffset(0);
    setQuery("");
    setError("");
    setCommand(false);
    setDrawer(false);
  }, []);
  useEffect(() => {
    const handler = () => {
      const p = PAGES.find((p) => p.key === location.hash.slice(1));
      if (p) {
        setCurrent(p.key);
        setGroup(p.group);
        setOffset(0);
        setQuery("");
      }
    };
    window.addEventListener("hashchange", handler);
    return () => window.removeEventListener("hashchange", handler);
  }, []);
  useEffect(() => {
    api("/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setBoot(false));
  }, []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setCommand((v) => !v);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    if (!user) return;
    let active = true;
    const load = async () => {
      try {
        const d = await api("/dashboard");
        if (active) setDashboard(d);
        const names = [
          "devices",
          "sites",
          "vrfs",
          "vlans",
          "prefixes",
          "credentials",
          "backup-groups",
          "interfaces",
          "scopes",
          "links",
          "events",
          "jobs",
          ...(user.role === "admin" ? ["users"] : []),
        ];
        const rows = await Promise.all(
          names.map(async (name) => [
            name,
            (await api("/" + name + "?limit=200")).items,
          ]),
        );
        if (active) setRefs(Object.fromEntries(rows));
      } catch (e: any) {
        if (active) setError(e.message);
      }
    };
    load();
    return () => {
      active = false;
    };
  }, [user, refresh]);
  useEffect(() => {
    if (
      !user ||
      !page.resource ||
      ["devices", "interfaces", "configuration"].includes(page.key)
    )
      return;
    let active = true;
    const queryKey = JSON.stringify([user.id, page.resource, offset, search]);
    // Live events and polling update rows in place without removing the table.
    setLoading(loadedQuery.current !== queryKey);
    api(
      "/" +
        page.resource +
        `?limit=25&offset=${offset}&q=${encodeURIComponent(search)}`,
    )
      .then((d) => {
        if (active) {
          loadedQuery.current = queryKey;
          setItems(d.items);
          setTotal(d.total);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [user, page.resource, offset, search, refresh]);
  useEffect(() => {
    if (!user) return;
    let socket: WebSocket | undefined;
    let reconnect: ReturnType<typeof setTimeout>;
    let closed = false;
    const connect = () => {
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/v1/ws`,
      );
      socket.onopen = () => setConnected(true);
      socket.onmessage = (e) => {
        if (JSON.parse(e.data).type === "refresh") reload();
      };
      socket.onclose = () => {
        setConnected(false);
        if (!closed) reconnect = setTimeout(connect, 10000);
      };
    };
    connect();
    const interval = setInterval(() => {
      if (!document.hidden) reload();
    }, 30000);
    return () => {
      closed = true;
      clearTimeout(reconnect);
      clearInterval(interval);
      socket?.close();
    };
  }, [user, reload]);
  const add = (key: string) => {
    const p = PAGES.find((p) => p.key === key);
    if (!p?.fields) return;
    if (!canWrite || ((key === "credentials" || key === "users") && !isAdmin)) {
      notify("Bu işlem için gerekli yetkiniz bulunmuyor.");
      return;
    }
    setForm({ page: p });
  };
  const runJob = async (kind: string, target_id: string) => {
    try {
      await api("/jobs", "POST", { kind, target_id });
      notify(
        kind === "identify"
          ? "Cihaz bilgileri sorgulanıyor. Okunamayan alanlarda mevcut bilgiler korunacak. Görev merkezinden takip edebilirsiniz."
          : "Görev kuyruğa alındı. Görev merkezinden takip edebilirsiniz.",
      );
      reload();
    } catch (e: any) {
      notify(e.message);
    }
  };
  const logout = async () => {
    try {
      await api("/auth/logout", "POST");
    } finally {
      setUser(null);
    }
  };
  const label = (resource: string, id: string) =>
    refs[resource]?.find((r) => r.id === id)?.name ||
    refs[resource]?.find((r) => r.id === id)?.cidr ||
    refs[resource]?.find((r) => r.id === id)?.display_name ||
    "—";
  const cell = (key: string, value: any, row: Row) => {
    if (key.endsWith("_at")) return date(value);
    if (key === "speed_bps") return speed(value);
    if (key === "size_bytes") return (value / 1024).toFixed(1) + " KB";
    if (key === "fingerprint")
      return (
        <span className="mono" title={value}>
          {value.slice(0, 16)}…
        </span>
      );
    if (key === "utilization")
      return (
        <span className="util">
          <span>
            <i style={{ width: Math.min(value, 100) + "%" }} />
          </span>
          {value}%
        </span>
      );
    if (key === "confidence")
      return (
        <span className="confidence">
          {Math.round(value * 100)}% · {value < 0.9 ? "Belirsiz" : "Doğrulandı"}
        </span>
      );
    if (key === "progress")
      return (
        <span className="mono">
          {value} / {row.total || "—"}
        </span>
      );
    if (key === "interval_seconds") return value ? value + " sn" : "Manuel";
    if (typeof value === "boolean")
      return (
        <span className={value ? "mint" : "muted"}>
          {key === "changed"
            ? value
              ? "Değişti"
              : "Değişmedi"
            : value
              ? "Etkin"
              : "Kapalı"}
        </span>
      );
    const relation: Record<string, string> = {
      site_id: "sites",
      vrf_id: "vrfs",
      vlan_id: "vlans",
      device_id: "devices",
      prefix_id: "prefixes",
      interface_id: "interfaces",
      actor_id: "users",
    };
    if (relation[key]) return label(relation[key], value);
    if (
      [
        "status",
        "state",
        "lifecycle_status",
        "reachability",
        "oper_status",
        "severity",
      ].includes(key)
    )
      return <Badge value={value} />;
    return value === null || value === undefined || value === ""
      ? "—"
      : tag(String(value));
  };
  const inspectDevice = (row: Row) => {
    setDetail({ ...row, ports: [], observations: [] });
  };
  useEffect(() => {
    if (!detail?.id || !user) return;
    let active = true;
    const id = detail.id;
    Promise.all([
      api("/devices/" + id),
      api("/interfaces?device_id=" + id + "&limit=200"),
      api("/observations?device_id=" + id + "&limit=5"),
    ])
      .then(([device, ports, obs]) => {
        if (active)
          setDetail({ ...device, ports: ports.items, observations: obs.items });
      })
      .catch((e: Error) => {
        if (active) notify(e.message);
      });
    return () => {
      active = false;
    };
  }, [detail?.id, refresh, user, notify]);
  if (boot)
    return (
      <div className="boot-screen" role="status">
        <Brand />
        <span className="boot-bar" aria-hidden="true" />
        <span>Çalışma alanınız hazırlanıyor…</span>
      </div>
    );
  if (!user)
    return (
      <Auth
        theme={theme}
        onTheme={toggleTheme}
        onLogin={(u) => {
          setUser(u);
          reload();
        }}
      />
    );
  return (
    <div
      className={
        "app-shell" +
        (collapsed ? " collapsed" : "") +
        (drawer ? " drawer-open" : "")
      }
    >
      <a className="skip-link" href="#main">
        İçeriğe atla
      </a>
      <aside className="sidebar" aria-label="Ana menü">
        <div className="sidebar-head">
          <button
            className="sidebar-brand"
            onClick={() => navigate("overview")}
            aria-label="NETRIX ana sayfa"
          >
            <Brand small={collapsed} />
          </button>
          <button
            className="icon-button sidebar-collapse"
            aria-label={collapsed ? "Menüyü genişlet" : "Menüyü daralt"}
            aria-expanded={!collapsed}
            onClick={() => {
              writePref("netrix-sidebar", collapsed ? "expanded" : "collapsed");
              setCollapsed(!collapsed);
            }}
          >
            <CaretDoubleLeft size={16} />
          </button>
          <button
            className="icon-button sidebar-close"
            aria-label="Menüyü kapat"
            onClick={() => setDrawer(false)}
          >
            <X size={18} />
          </button>
        </div>
        <nav className="sidebar-nav" aria-label="Sayfalar">
          {GROUPS.map((g, index) => (
            <div
              className={"nav-group" + (page.group === g ? " active" : "")}
              key={g}
            >
              <button
                type="button"
                className="nav-group-title"
                aria-expanded={!closedGroups.includes(g)}
                aria-controls={`nav-group-${index}`}
                onClick={() =>
                  setClosedGroups((groups) =>
                    groups.includes(g)
                      ? groups.filter((item) => item !== g)
                      : [...groups, g],
                  )
                }
              >
                <span>{g}</span>
                {closedGroups.includes(g) ? (
                  <CaretDown size={15} aria-hidden="true" />
                ) : (
                  <CaretUp size={15} aria-hidden="true" />
                )}
              </button>
              <div
                id={`nav-group-${index}`}
                className="nav-group-items"
                hidden={closedGroups.includes(g)}
              >
                {PAGES.filter(
                  (p) =>
                    p.group === g &&
                    (!["users", "audit"].includes(p.key) || isAdmin),
                ).map((p) => (
                  <button
                    key={p.key}
                    className={
                      "nav-item" + (current === p.key ? " selected" : "")
                    }
                    aria-current={current === p.key ? "page" : undefined}
                    title={collapsed ? p.title : undefined}
                    onClick={() => navigate(p.key)}
                  >
                    <p.icon
                      size={19}
                      weight={current === p.key ? "fill" : "regular"}
                    />
                    <span>{p.title}</span>
                    {p.key === "alerts" &&
                      !!dashboard.counts?.firing_alerts && (
                        <b className="nav-count">
                          {dashboard.counts.firing_alerts}
                        </b>
                      )}
                    {p.key === "jobs" && !!dashboard.counts?.running_jobs && (
                      <b className="nav-count neutral">
                        {dashboard.counts.running_jobs}
                      </b>
                    )}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="sidebar-user">
          <span className="avatar" aria-hidden="true">
            {user.display_name
              ?.split(" ")
              .map((n: string) => n[0])
              .slice(0, 2)
              .join("")}
          </span>
          <span className="sidebar-user-text">
            <b>{user.display_name}</b>
            <small>{tag(user.role)}</small>
          </span>
          <button
            className="icon-button"
            onClick={logout}
            aria-label="Güvenli çıkış"
            title="Güvenli çıkış"
          >
            <SignOut size={18} />
          </button>
        </div>
      </aside>
      <div
        className="sidebar-scrim"
        aria-hidden="true"
        onClick={() => setDrawer(false)}
      />
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button menu-button"
            aria-label="Menüyü aç"
            aria-expanded={drawer}
            onClick={() => setDrawer(true)}
          >
            <List size={20} />
          </button>
          <div className="breadcrumbs">
            <span>{page.group}</span>
            <CaretRight size={12} />
            <b>{page.title}</b>
          </div>
          <div className="topbar-actions">
            <button
              className="command-trigger"
              aria-label="Komut paletini aç (Ctrl K)"
              onClick={() => {
                setCommandQuery("");
                setCommand(true);
              }}
            >
              <MagnifyingGlass size={17} />
              <span>Sayfa veya cihaz ara</span>
              <kbd>Ctrl K</kbd>
            </button>
            <div className="connection-label" title="Canlı bildirim bağlantısı">
              <span
                className={"connection-dot " + (connected ? "online" : "")}
              />
              {connected ? "Bağlı" : "Yeniden bağlanıyor"}
            </div>
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
            <button
              className="icon-button"
              aria-label="Verileri yenile"
              title="Verileri yenile"
              onClick={reload}
            >
              <ArrowsClockwise size={19} />
            </button>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          <div className="page-view" key={current}>
            {page.key !== "overview" && (
              <div className="page-heading">
                <div>
                  <h1>{page.title}</h1>
                  <p>{page.desc}</p>
                </div>
                {canWrite && (
                  <div className="page-actions">
                    {page.fields &&
                      (isAdmin ||
                        !["credentials", "users"].includes(page.key)) && (
                        <button
                          className="primary"
                          onClick={() => add(page.key)}
                        >
                          <Plus size={18} />
                          Yeni kayıt
                        </button>
                      )}
                    {["configuration", "monitoring"].includes(page.key) && (
                      <button
                        className="primary"
                        onClick={() => {
                          setJobKind(
                            page.key === "monitoring" ? "monitor" : "backup",
                          );
                          setJobTarget("");
                          setJobModal(true);
                        }}
                      >
                        <Play size={16} />
                        {page.key === "configuration" ? "Yedek al" : "Ölçüm al"}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
            {error && (
              <div className="error page-error" role="alert">
                <WarningCircle size={18} />
                {error}
                <button className="text-button" onClick={reload}>
                  Yeniden dene
                </button>
              </div>
            )}
            {page.key === "overview" ? (
              <Overview
                dashboard={dashboard}
                refs={refs}
                navigate={navigate}
                onAdd={add}
                onDevice={inspectDevice}
              />
            ) : page.key === "devices" ? (
              <InventoryTable
                key="devices"
                refresh={refresh}
                user={user!}
                onSaved={reload}
                onDevice={inspectDevice}
                onEdit={(row) =>
                  setForm({
                    page: PAGES.find((p) => p.key === "devices")!,
                    row,
                  })
                }
                onTest={setTestDevice}
              />
            ) : page.key === "interfaces" ? (
              <InterfaceWorkspace
                refresh={refresh}
                user={user!}
                onSaved={reload}
              />
            ) : [
                "configuration",
                "backup-changes",
                "backup-compare",
                "backup-settings",
              ].includes(page.key) ? (
              <BackupWorkspace
                key={page.key}
                page={page.key}
                refresh={refresh}
                user={user!}
                onSaved={reload}
              />
            ) : page.key === "monitoring" ? (
              <Traffic refs={refs} refresh={refresh} />
            ) : page.key === "settings" ? (
              <Settings onLogout={() => setUser(null)} />
            ) : (
              <>
                {page.key === "topology" && (
                  <section className="panel topology-panel">
                    <Topology
                      devices={refs.devices || []}
                      links={refs.links || []}
                      onDevice={inspectDevice}
                    />
                    <div className="info-note">
                      <Info size={19} />
                      <p>
                        Kesik çizgiler aday komşulukları gösterir. İsim
                        eşleşmeleri fiziksel bağlantı kanıtı sayılmaz; güven
                        düzeyi tabloda belirtilir. Son gözlem tarihi kayıt
                        ayrıntılarındadır.
                      </p>
                    </div>
                  </section>
                )}
                {page.key === "discovery" && (
                  <div className="scope-banner">
                    <div className="scope-banner-icon">
                      <Broadcast size={24} />
                    </div>
                    <div>
                      <b>Keşfin sınırlarını siz çizin.</b>
                      <p>
                        Açık hedefler, hariç tutulan ağlar ve SNMPv3 ile
                        kontrollü veri toplama.
                      </p>
                    </div>
                    <span className="scope-limit">
                      4 eşzamanlı hedef · 1024 adres sınırı
                    </span>
                  </div>
                )}
                {page.key === "configuration" && (
                  <div className="info-note config-note">
                    <LockKey size={20} />
                    <p>
                      Konfigürasyonlar şifreli saklanır. Görüntülenen sürümlerde
                      ve farklarda hassas satırlar otomatik maskelenir.
                    </p>
                  </div>
                )}
                <section className="panel table-panel">
                  <div className="toolbar">
                    <div className="table-title">
                      <page.icon size={19} />
                      <b>{page.title}</b>
                      <span className="count-pill">{total}</span>
                    </div>
                    <label className="search-box">
                      <MagnifyingGlass size={17} />
                      <input
                        aria-label="Kayıtlarda ara"
                        placeholder="Kayıtlarda ara…"
                        value={query}
                        onChange={(e) => {
                          setQuery(e.target.value);
                          setOffset(0);
                        }}
                      />
                    </label>
                  </div>
                  {loading ? (
                    <div className="loading">
                      <ArrowsClockwise size={22} />
                      Kayıtlar yükleniyor…
                    </div>
                  ) : items.length ? (
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            {page.columns?.map(([key, title]) => (
                              <th key={key}>{title}</th>
                            ))}
                            <th className="actions-heading">İşlemler</th>
                          </tr>
                        </thead>
                        <tbody>
                          {items.map((row) => (
                            <tr key={row.id}>
                              {page.columns?.map(([key]) => (
                                <td
                                  key={key}
                                  className={
                                    [
                                      "management_ip",
                                      "cidr",
                                      "address",
                                      "if_index",
                                    ].includes(key)
                                      ? "mono"
                                      : ""
                                  }
                                >
                                  {key === "name" && page.key === "devices" ? (
                                    <button
                                      className="device-link"
                                      onClick={() => inspectDevice(row)}
                                    >
                                      <span className="device-icon">
                                        <Stack size={18} />
                                      </span>
                                      <span>
                                        <b>{row.name}</b>
                                        <small>
                                          {row.model || "Model belirtilmedi"}
                                        </small>
                                      </span>
                                    </button>
                                  ) : (
                                    cell(key, row[key], row)
                                  )}
                                </td>
                              ))}
                              <td>
                                <div className="row-actions">
                                  {page.key === "devices" && (
                                    <button
                                      className="icon-button"
                                      aria-label={row.name + " ayrıntıları"}
                                      onClick={() => inspectDevice(row)}
                                    >
                                      <Eye size={17} />
                                    </button>
                                  )}
                                  {page.key === "discovery" && canWrite && (
                                    <button
                                      className="icon-button mint"
                                      aria-label={row.name + " keşfini başlat"}
                                      disabled={!row.enabled}
                                      onClick={() =>
                                        runJob("discovery", row.id)
                                      }
                                    >
                                      <Play size={18} />
                                    </button>
                                  )}
                                  {page.key === "jobs" &&
                                    canWrite &&
                                    ["queued", "running"].includes(
                                      row.status,
                                    ) && (
                                      <button
                                        className="icon-button"
                                        aria-label="Görevi iptal et"
                                        onClick={async () => {
                                          try {
                                            await api(
                                              "/jobs/" + row.id + "/cancel",
                                              "POST",
                                            );
                                            reload();
                                          } catch (e: any) {
                                            notify(e.message);
                                          }
                                        }}
                                      >
                                        <Stop size={17} />
                                      </button>
                                    )}
                                  {page.key === "configuration" && canWrite && (
                                    <>
                                      <button
                                        className="icon-button"
                                        aria-label="Konfigürasyonu görüntüle"
                                        onClick={async () => {
                                          try {
                                            const d = await api(
                                              "/snapshots/" +
                                                row.id +
                                                "/content",
                                            );
                                            setConfig({
                                              title:
                                                "Maskelenmiş konfigürasyon",
                                              content: d.content,
                                            });
                                          } catch (e: any) {
                                            notify(e.message);
                                          }
                                        }}
                                      >
                                        <Eye size={17} />
                                      </button>
                                      <button
                                        className="icon-button"
                                        aria-label="Sürüm farkını görüntüle"
                                        onClick={async () => {
                                          try {
                                            const d = await api(
                                              "/snapshots/" + row.id + "/diff",
                                            );
                                            setConfig({
                                              title: "Konfigürasyon farkı",
                                              content:
                                                d.diff ||
                                                "Bu sürümde görünür bir satır değişikliği yok.",
                                            });
                                          } catch (e: any) {
                                            notify(e.message);
                                          }
                                        }}
                                      >
                                        <GitBranch size={17} />
                                      </button>
                                    </>
                                  )}
                                  {page.key === "alerts" &&
                                    canWrite &&
                                    !row.acknowledged_at && (
                                      <button
                                        className="icon-button"
                                        aria-label="Alarmı görüldü işaretle"
                                        onClick={async () => {
                                          try {
                                            await api(
                                              "/alerts/" +
                                                row.id +
                                                "/acknowledge",
                                              "POST",
                                            );
                                            reload();
                                          } catch (e: any) {
                                            notify(e.message);
                                          }
                                        }}
                                      >
                                        <Check size={18} />
                                      </button>
                                    )}
                                  {page.key === "users" &&
                                    isAdmin &&
                                    row.id !== user.id && (
                                      <button
                                        className="icon-button"
                                        aria-label="Hesap erişimini değiştir"
                                        onClick={async () => {
                                          try {
                                            await api(
                                              "/users/" + row.id + "/toggle",
                                              "POST",
                                            );
                                            reload();
                                          } catch (e: any) {
                                            notify(e.message);
                                          }
                                        }}
                                      >
                                        <LockKey size={17} />
                                      </button>
                                    )}
                                  {page.fields &&
                                    page.key !== "users" &&
                                    canWrite &&
                                    (page.key !== "credentials" || isAdmin) && (
                                      <button
                                        className="icon-button"
                                        aria-label="Kaydı düzenle"
                                        onClick={() => setForm({ page, row })}
                                      >
                                        <PencilSimple size={17} />
                                      </button>
                                    )}
                                  {page.fields &&
                                    isAdmin &&
                                    !["users", "vrfs"].includes(page.key) && (
                                      <button
                                        className="icon-button delete-button"
                                        aria-label={
                                          page.key === "devices"
                                            ? "Cihazı arşivle"
                                            : "Kaydı sil"
                                        }
                                        onClick={async () => {
                                          if (
                                            !window.confirm(
                                              page.key === "devices"
                                                ? "Cihaz arşivlensin mi? Geçmişi korunur."
                                                : "Bu kayıt silinsin mi?",
                                            )
                                          )
                                            return;
                                          try {
                                            await api(
                                              "/" +
                                                page.resource +
                                                "/" +
                                                row.id,
                                              "DELETE",
                                            );
                                            reload();
                                            notify("İşlem tamamlandı.");
                                          } catch (e: any) {
                                            notify(e.message);
                                          }
                                        }}
                                      >
                                        <Trash size={17} />
                                      </button>
                                    )}
                                  {!page.fields &&
                                    ![
                                      "configuration",
                                      "jobs",
                                      "alerts",
                                    ].includes(page.key) && (
                                      <button
                                        className="icon-button"
                                        aria-label="Kayıt ayrıntıları"
                                        onClick={() =>
                                          setConfig({
                                            title: "Kayıt ayrıntıları",
                                            content: JSON.stringify(
                                              row,
                                              null,
                                              2,
                                            ),
                                          })
                                        }
                                      >
                                        <Eye size={17} />
                                      </button>
                                    )}
                                  {page.key === "devices" && canWrite && (
                                    <button
                                      className="text-button connection-test-trigger"
                                      aria-label={row.name + " bağlantı testi"}
                                      aria-haspopup="dialog"
                                      onClick={() => setTestDevice(row)}
                                    >
                                      <PlugsConnected
                                        size={17}
                                        aria-hidden="true"
                                      />
                                      Test
                                    </button>
                                  )}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <Empty
                      icon={page.icon}
                      title={
                        query
                          ? "Aramanızla eşleşen kayıt yok."
                          : "Henüz bir kayıt yok."
                      }
                      desc={
                        query
                          ? "Başka bir sözcük veya adres ile yeniden deneyin."
                          : page.key === "jobs"
                            ? "Başlattığınız keşif, yedekleme ve izleme görevleri burada listelenir."
                            : page.key === "alerts"
                              ? "Alarm kuralları oluşturun. Koşullar gerçekleştiğinde alarmlar burada görünür."
                              : "İlk kaydı ekleyin veya keşif ve toplama görevlerinden veri gelmesini bekleyin."
                      }
                      action={
                        page.fields &&
                        canWrite &&
                        (isAdmin ||
                          !["credentials", "users"].includes(page.key)) &&
                        !query ? (
                          <button
                            className="secondary"
                            onClick={() => add(page.key)}
                          >
                            <Plus size={17} />
                            İlk kaydı ekle
                          </button>
                        ) : undefined
                      }
                    />
                  )}
                  <footer className="table-footer">
                    <span>
                      {total
                        ? `${offset + 1}–${Math.min(offset + 25, total)} / ${total} kayıt`
                        : "0 kayıt"}
                      <span className="footer-divider">/</span>Merkezi envanter
                    </span>
                    <div>
                      <button
                        className="icon-button"
                        aria-label="Önceki sayfa"
                        disabled={offset === 0}
                        onClick={() => setOffset(Math.max(0, offset - 25))}
                      >
                        <CaretLeft size={17} />
                      </button>
                      <span className="mono">
                        {Math.floor(offset / 25) + 1}
                      </span>
                      <button
                        className="icon-button"
                        aria-label="Sonraki sayfa"
                        disabled={offset + 25 >= total}
                        onClick={() => setOffset(offset + 25)}
                      >
                        <CaretRight size={17} />
                      </button>
                    </div>
                  </footer>
                </section>
              </>
            )}
          </div>
        </main>
      </div>
      {toast && (
        <div className="toast" role="status">
          <Info size={20} />
          <span>{toast}</span>
          <button
            className="icon-button"
            aria-label="Bildirimi kapat"
            onClick={() => setToast("")}
          >
            <X size={16} />
          </button>
        </div>
      )}
      {form && (
        <ResourceForm
          key={form.page.key + (form.row?.id || "new")}
          page={form.page}
          row={form.row}
          refs={refs}
          onClose={() => setForm(null)}
          onSaved={(saved) => {
            reload();
            notify(
              "Kayıt kaydedildi. " + (saved.identification?.message || ""),
            );
          }}
        />
      )}
      {command && (
        <Dialog
          title="Çalışma alanında gezin"
          onClose={() => setCommand(false)}
        >
          <div className="command-body">
            <label className="command-input">
              <MagnifyingGlass size={21} />
              <input
                autoFocus
                placeholder="Sayfa veya cihaz ara…"
                aria-label="Sayfa veya cihaz ara"
                value={commandQuery}
                onChange={(e) => setCommandQuery(e.target.value)}
              />
            </label>
            <div className="command-results">
              {PAGES.filter(
                (p) =>
                  (isAdmin || !["audit", "users"].includes(p.key)) &&
                  (p.title + " " + p.group)
                    .toLocaleLowerCase("tr-TR")
                    .includes(commandQuery.toLocaleLowerCase("tr-TR")),
              ).map((p) => (
                <button key={p.key} onClick={() => navigate(p.key)}>
                  <p.icon size={20} />
                  <span>
                    <b>{p.title}</b>
                    <small>{p.group}</small>
                  </span>
                  <ArrowUpRight size={16} />
                </button>
              ))}
              {commandQuery &&
                refs.devices
                  ?.filter((d) =>
                    (d.name + " " + d.management_ip)
                      .toLowerCase()
                      .includes(commandQuery.toLowerCase()),
                  )
                  .slice(0, 5)
                  .map((d) => (
                    <button
                      key={d.id}
                      onClick={() => {
                        setCommand(false);
                        inspectDevice(d);
                      }}
                    >
                      <Stack size={20} />
                      <span>
                        <b>{d.name}</b>
                        <small>{d.management_ip}</small>
                      </span>
                      <Eye size={16} />
                    </button>
                  ))}
            </div>
          </div>
        </Dialog>
      )}
      {detail && (
        <Dialog title={detail.name} onClose={() => setDetail(null)} wide>
          <div className="device-detail">
            <div className="device-summary">
              <span className="device-icon large">
                <Stack size={32} />
              </span>
              <div>
                <h3>{detail.management_ip}</h3>
                <p>
                  {detail.vendor || "Üretici belirtilmedi"} ·{" "}
                  {detail.model || "Model belirtilmedi"}
                </p>
              </div>
              <Badge value={detail.reachability} />
            </div>
            <div className="detail-actions">
              {canWrite && (
                <>
                  <button
                    className="secondary"
                    disabled={
                      detail.lifecycle_status !== "active" ||
                      !(
                        detail.snmp_credential_id || detail.config_credential_id
                      )
                    }
                    onClick={() => runJob("identify", detail.id)}
                  >
                    <ArrowsClockwise size={18} />
                    Bilgileri cihazdan al
                  </button>
                  <button
                    className="secondary"
                    onClick={() => runJob("monitor", detail.id)}
                  >
                    <Waveform size={18} />
                    Ölçüm al
                  </button>
                  <button
                    className="secondary"
                    onClick={() => runJob("backup", detail.id)}
                  >
                    <DownloadSimple size={18} />
                    Yedek al
                  </button>
                  <button
                    className="text-button"
                    onClick={() => {
                      const row = detail;
                      setDetail(null);
                      setForm({
                        page: PAGES.find((p) => p.key === "devices")!,
                        row,
                      });
                    }}
                  >
                    Düzenle
                    <ArrowUpRight size={16} />
                  </button>
                </>
              )}
            </div>
            <dl className="detail-grid">
              {[
                ["Lokasyon", label("sites", detail.site_id)],
                ["VRF", label("vrfs", detail.vrf_id)],
                ["Son başarılı gözlem", date(detail.last_seen_at)],
                ["Son yedek", date(detail.last_backup_at)],
                ["Son izleme denemesi", date(detail.last_monitor_at)],
                ["Yaşam döngüsü", tag(detail.lifecycle_status)],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
            <InterfacePicker
              device={detail}
              canWrite={canWrite}
              onSaved={() => {
                reload();
                notify("Arayüz seçimi kaydedildi.");
              }}
            />
            <h3>Keşif kanıtı</h3>
            {detail.observations.length ? (
              <div className="evidence">
                <span className="eyebrow">
                  {date(detail.observations[0].created_at)} ·{" "}
                  {detail.observations[0].source === "identity"
                    ? "Cihaz bilgisi sorgusu"
                    : detail.observations[0].source?.toUpperCase()}
                </span>
                {detail.observations[0].source === "identity" ? (
                  (
                    [
                      ["vendor", "Üretici"],
                      ["model", "Model"],
                      ["kind", "Cihaz türü"],
                    ] as const
                  ).map(([key, title]) => (
                    <p key={key}>
                      <b>{title}:</b>{" "}
                      {detail.observations[0].evidence.identity?.[key]
                        ? tag(detail.observations[0].evidence.identity[key])
                        : "Okunamadı; mevcut değer korundu."}
                      {detail.observations[0].evidence.field_sources?.[key] && (
                        <span className="muted">
                          {" "}
                          ·{" "}
                          {detail.observations[0].evidence.field_sources[
                            key
                          ].toUpperCase()}
                        </span>
                      )}
                    </p>
                  ))
                ) : (
                  <>
                    <p>
                      <b>Gözlemlenen hostname:</b>{" "}
                      {detail.observations[0].evidence.hostname || "—"}
                    </p>
                    <p>{detail.observations[0].evidence.sys_description}</p>
                  </>
                )}
                <p className="muted">
                  Yönetilen cihaz adı, gözlemlenen hostname değiştiğinde
                  otomatik değiştirilmez.
                </p>
                <details>
                  <summary>Port eşleştirme adayları ve protokol kanıtı</summary>
                  <pre>
                    {JSON.stringify(detail.observations[0].evidence, null, 2)}
                  </pre>
                </details>
              </div>
            ) : (
              <p className="muted">
                Bu cihaz için henüz bir keşif gözlemi bulunmuyor.
              </p>
            )}
          </div>
        </Dialog>
      )}
      {config && (
        <Dialog title={config.title} onClose={() => setConfig(null)} wide>
          <pre className="config-code">{config.content}</pre>
        </Dialog>
      )}
      {testDevice && (
        <ConnectionTestDialog
          device={testDevice}
          onClose={() => setTestDevice(null)}
        />
      )}
      {jobModal && (
        <Dialog
          title={
            jobKind === "backup"
              ? "Konfigürasyon yedeği alın"
              : "SNMPv3 ölçümü başlatın"
          }
          onClose={() => setJobModal(false)}
        >
          <form
            className="job-form"
            onSubmit={async (e) => {
              e.preventDefault();
              setJobBusy(true);
              await runJob(jobKind, jobTarget);
              setJobBusy(false);
              setJobModal(false);
            }}
          >
            <label>
              Hedef cihaz
              <select
                value={jobTarget}
                required
                onChange={(e) => setJobTarget(e.target.value)}
              >
                <option value="">Bir cihaz seçin</option>
                {refs.devices
                  ?.filter(
                    (d) =>
                      d.lifecycle_status === "active" &&
                      (jobKind === "backup"
                        ? d.config_credential_id
                        : d.snmp_credential_id),
                  )
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} · {d.management_ip}
                    </option>
                  ))}
              </select>
            </label>
            <div className="info-note">
              <Info size={20} />
              <p>
                Yalnızca erişim profili atanmış aktif cihazlar listelenir.
                Hedefin etkin bir yetkili kapsamda bulunması gerekir.
              </p>
            </div>
            <div className="dialog-footer">
              <button
                type="button"
                className="secondary"
                onClick={() => setJobModal(false)}
              >
                Vazgeç
              </button>
              <button className="primary" disabled={!jobTarget || jobBusy}>
                <Play size={17} />
                Görevi başlat
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
