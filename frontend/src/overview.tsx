import { useRef, useState } from "react";
import type { ComponentType, PointerEvent, ReactNode } from "react";
import {
  Pulse,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Bell,
  Check,
  Circuitry,
  ClockCounterClockwise,
  DotsSixVertical,
  GearSix,
  HardDrives,
  ListChecks,
  PlugsConnected,
  Plus,
  ShieldCheck,
  Stack,
  TreeStructure,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useLiveQuery } from "./data";
import { formatDate } from "./preferences";
import "./overview.css";

const widgets = {
  alarms: {
    title: "Aktif alarmlar",
    description: "Önem sırasına göre açık alarmlar ve görülme durumu.",
    icon: Bell,
    page: "alerts",
  },
  gaps: {
    title: "Eksikler ve inceleme",
    description: "Kurulum eksikleri ve inceleme bekleyen kayıtlar.",
    icon: ListChecks,
    page: null,
  },
  inventory: {
    title: "Cihaz envanteri",
    description: "Yönetilen cihazlar ve gözlemlenen erişilebilirlik.",
    icon: HardDrives,
    page: "devices",
  },
  ipam: {
    title: "IP adres yönetimi",
    description: "VLAN’lar, IP kayıtları ve çözümleme sorunları.",
    icon: TreeStructure,
    page: "vlans",
  },
  backups: {
    title: "Konfigürasyon",
    description: "Yedek sürümleri ve onay bekleyen değişiklikler.",
    icon: ShieldCheck,
    page: "backup-changes",
  },
  jobs: {
    title: "Görev merkezi",
    description: "Kuyruktaki, çalışan ve son 24 saatte başarısız işler.",
    icon: Stack,
    page: "jobs",
  },
  firmware: {
    title: "Firmware",
    description: "Planlar, hazır imajlar ve müdahale bekleyen hedefler.",
    icon: Circuitry,
    page: "firmware-plans",
  },
  system: {
    title: "Sistem sağlığı",
    description: "Veritabanı, Redis, işleyici ve zamanlayıcı durumu.",
    icon: Pulse,
    page: null,
  },
  events: {
    title: "Son hareketler",
    description: "En son kaydedilen ağ ve uygulama olayları.",
    icon: ClockCounterClockwise,
    page: "events",
  },
  discovery: {
    title: "Ağ keşfi",
    description: "Etkin kapsamlar ve tamamlanan keşifler.",
    icon: TreeStructure,
    page: "discovery",
  },
  connections: {
    title: "Komşuluk kayıtları",
    description: "Güncel LLDP/CDP kayıtlarının sayısal özeti.",
    icon: PlugsConnected,
    page: "neighbors",
  },
  integrations: {
    title: "IPAM kaynakları",
    description: "Etkin entegrasyonlar ve tarama grupları.",
    icon: PlugsConnected,
    page: "integrations",
  },
  administration: {
    title: "Yönetim",
    description: "Erişim profilleri ve etkin alarm kuralları.",
    icon: GearSix,
    page: "rules",
  },
} as const;

type Widget = keyof typeof widgets;
type Entry = { id: string; message: string; created_at: string };
type AlarmEntry = Entry & { severity: string; acknowledged_at: string | null };
type WidgetData = {
  counts: Record<string, number>;
  alerts: AlarmEntry[];
  events: Entry[];
  server_time: string;
};
type Dashboard = { counts?: Record<string, number>; server_time?: string };
const catalog = Object.keys(widgets) as Widget[];
const defaults: Widget[] = [
  "alarms",
  "gaps",
  "inventory",
  "ipam",
  "backups",
  "jobs",
  "firmware",
  "system",
  "connections",
  "administration",
  "events",
];
const number = new Intl.NumberFormat("tr-TR");

function storedLayout(key: string) {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    if (Array.isArray(saved))
      return [
        ...new Set(saved.filter((id): id is Widget => catalog.includes(id))),
      ];
  } catch {
    // A blocked or malformed storage entry uses the default layout.
  }
  return defaults;
}

function StatRows({
  rows,
}: {
  rows: [string, number | undefined, boolean?][];
}) {
  return (
    <dl className="overview-stat-rows">
      {rows.map(([label, value, attention]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className={attention && value ? "overview-attention" : undefined}>
            {value === undefined ? "—" : number.format(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function SystemStatus({ refresh }: { refresh: number }) {
  const { data, error } = useLiveQuery<{
    database: string;
    redis: string;
    worker: string | null;
    scheduler: string | null;
  }>("/system", refresh);
  if (error || !data)
    return (
      <p className="overview-empty" role="status">
        {error ? "Sistem durumu okunamadı." : "Sistem durumu yükleniyor…"}
      </p>
    );
  const services: [string, boolean][] = [
    ["Veritabanı", !!data.database],
    ["Redis", data.redis === "ok"],
    ["İşleyici", !!data.worker],
    ["Zamanlayıcı", !!data.scheduler],
  ];
  return (
    <dl className="overview-stat-rows">
      {services.map(([label, up]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className={up ? "overview-good" : "overview-attention"}>
            {up ? "Çalışıyor" : "Yanıt yok"}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function Overview({
  dashboard,
  refresh,
  userId,
  navigate,
  Dialog,
}: {
  dashboard?: Dashboard;
  refresh: number;
  userId: string;
  navigate: (page: string) => void;
  Dialog: ComponentType<{
    title: string;
    onClose: () => void;
    children: ReactNode;
    className?: string;
  }>;
}) {
  const storageKey = `netrix-overview-v1:${userId}`;
  const [layout, setLayout] = useState(() => storedLayout(storageKey));
  const [editing, setEditing] = useState(false);
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const [storageError, setStorageError] = useState(false);
  const [dropTarget, setDropTarget] = useState<Widget | null>(null);
  const drag = useRef<{ id: Widget; x: number; y: number } | null>(null);
  const grid = useRef<HTMLElement>(null);
  const catalogTrigger = useRef<HTMLButtonElement>(null);
  const api = useLiveQuery<WidgetData>(
    layout.some((item) => item !== "system") ? "/dashboard/widgets" : null,
    refresh,
  );
  const c = dashboard?.counts ?? {};
  const d = api.data?.counts ?? {};

  function save(next: Widget[], message: string) {
    setLayout(next);
    setAnnouncement(message);
    try {
      localStorage.setItem(storageKey, JSON.stringify(next));
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }
  function move(id: Widget, destination: number) {
    const position = layout.indexOf(id);
    if (
      destination < 0 ||
      destination >= layout.length ||
      destination === position
    )
      return;
    const reordered = layout.filter((item) => item !== id);
    reordered.splice(destination, 0, id);
    save(
      reordered,
      `${widgets[id].title}, ${destination + 1}. sıraya taşındı.`,
    );
  }
  function targetAt(event: PointerEvent) {
    const target = document
      .elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>("[data-overview-widget]");
    return grid.current?.contains(target ?? null)
      ? (target?.dataset.overviewWidget as Widget)
      : null;
  }
  function startDrag(event: PointerEvent<HTMLButtonElement>, id: Widget) {
    if (!event.isPrimary || event.button !== 0) return;
    drag.current = { id, x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function dragOver(event: PointerEvent<HTMLButtonElement>) {
    if (!drag.current) return;
    const { x, y } = drag.current;
    if (Math.hypot(event.clientX - x, event.clientY - y) < 8 && !dropTarget)
      return;
    if (event.clientY < 65) window.scrollBy(0, -18);
    if (event.clientY > window.innerHeight - 65) window.scrollBy(0, 18);
    setDropTarget(targetAt(event));
  }
  function clearDrag() {
    setDropTarget(null);
    drag.current = null;
  }
  function finishDrag(event: PointerEvent<HTMLButtonElement>) {
    const target = targetAt(event);
    if (
      drag.current &&
      target &&
      Math.hypot(
        event.clientX - drag.current.x,
        event.clientY - drag.current.y,
      ) >= 8
    ) {
      move(drag.current.id, layout.indexOf(target));
    }
    clearDrag();
  }

  const gaps = [
    [d.ip_problems, "sorunlu IP çözümlemesi", "vlans"],
    [
      d.firmware_attention,
      "müdahale bekleyen firmware hedefi",
      "firmware-plans",
    ],
    [
      d.no_backup,
      "konfigürasyon profili atanmış fakat yedeği bulunmayan cihaz",
      "configuration",
    ],
    [d.unplaced, "lokasyonu atanmamış aktif cihaz", "devices"],
    [d.no_cidr, "CIDR tanımı olmayan VLAN", "vlans"],
    [d.scopes === 0 ? 1 : 0, "Etkin keşif kapsamı tanımlı değil", "discovery"],
    [d.rules === 0 ? 1 : 0, "Etkin alarm kuralı tanımlı değil", "rules"],
  ] as const;

  function content(id: Widget) {
    switch (id) {
      case "alarms":
      case "events": {
        const entries = id === "alarms" ? api.data?.alerts : api.data?.events;
        if (!entries?.length)
          return (
            <p className="overview-empty">
              {id === "alarms" ? "Açık alarm yok." : "Henüz olay kaydı yok."}
            </p>
          );
        return (
          <ul className="overview-entry-list">
            {entries.map((entry) => (
              <li key={entry.id}>
                <strong>{entry.message}</strong>
                <span>
                  {"severity" in entry && "acknowledged_at" in entry && (
                    <span
                      className={
                        entry.severity === "critical"
                          ? "overview-attention"
                          : undefined
                      }
                    >
                      {entry.severity === "critical"
                        ? "Kritik"
                        : entry.severity === "warning"
                          ? "Uyarı"
                          : "Bilgi"}
                      {entry.acknowledged_at ? " · Görüldü" : " · Görülmedi"}{" "}
                      ·{" "}
                    </span>
                  )}
                  <time dateTime={entry.created_at}>
                    {formatDate(entry.created_at)}
                  </time>
                </span>
              </li>
            ))}
          </ul>
        );
      }
      case "gaps": {
        const issues = gaps.filter(([value]) => !!value);
        if (!issues.length)
          return (
            <p className="overview-empty">
              İzlenen kontrollerde açık eksik yok.
            </p>
          );
        return (
          <ul className="overview-gap-list">
            {issues.map(([value, label, page]) => (
              <li key={label}>
                <button type="button" onClick={() => navigate(page)}>
                  <WarningCircle size={18} aria-hidden="true" />
                  <span>
                    {label.startsWith("Etkin")
                      ? label
                      : `${number.format(value!)} ${label}`}
                  </span>
                  <ArrowRight size={16} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        );
      }
      case "inventory":
        return (
          <StatRows
            rows={[
              ["Envanterdeki cihaz", c.devices],
              ["Aktif cihaz", c.active_devices],
              ["Erişilebilir olarak kaydedilen", c.reachable],
              ["Erişilebilirliği doğrulanmamış", d.unverified, true],
              ["Lokasyon", c.sites],
            ]}
          />
        );
      case "ipam":
        return (
          <StatRows
            rows={[
              ["VLAN", c.vlans],
              ["Kayıtlı adres", c.addresses],
              ["Sorunlu IP çözümlemesi", d.ip_problems, true],
            ]}
          />
        );
      case "backups":
        return (
          <StatRows
            rows={[
              ["Konfigürasyon sürümü", c.snapshots],
              ["Onay bekleyen değişiklik", c.config_changes, true],
              ["Profili atanmış, yedeği olmayan cihaz", d.no_backup, true],
            ]}
          />
        );
      case "jobs":
        return (
          <StatRows
            rows={[
              ["Kuyrukta", d.queued],
              ["Çalışıyor", d.running],
              ["Başarısız · Son 24 saat", d.failed, true],
            ]}
          />
        );
      case "firmware":
        return (
          <StatRows
            rows={[
              ["Açık plan", d.firmware_plans],
              ["Hazır imaj", d.firmware_images],
              ["Müdahale bekleyen hedef", d.firmware_attention, true],
            ]}
          />
        );
      case "system":
        return <SystemStatus refresh={refresh} />;
      case "discovery":
        return (
          <StatRows
            rows={[
              ["Etkin keşif kapsamı", d.scopes],
              ["Sonuç üreten keşif görevi", c.successful_discoveries],
            ]}
          />
        );
      case "connections":
        return <StatRows rows={[["Güncel komşuluk kaydı", d.links]]} />;
      case "integrations":
        return (
          <StatRows
            rows={[
              ["Etkin entegrasyon", d.integrations],
              ["Etkin tarama grubu", d.scan_groups],
            ]}
          />
        );
      case "administration":
        return (
          <StatRows
            rows={[
              ["Kayıtlı erişim profili", d.credentials],
              ["Etkin alarm kuralı", d.rules],
            ]}
          />
        );
    }
  }

  return (
    <div className="overview-workspace">
      <header className="overview-command">
        <div>
          <h1>Genel bakış</h1>
          <p>NETRIX operasyon durumu</p>
        </div>
        <div className="overview-command-actions">
          <button
            type="button"
            className="secondary"
            aria-pressed={editing}
            onClick={() => setEditing(!editing)}
          >
            {editing ? (
              <Check size={18} aria-hidden="true" />
            ) : (
              <GearSix size={18} aria-hidden="true" />
            )}
            {editing ? "Düzenlemeyi bitir" : "Yerleşimi düzenle"}
          </button>
          <button
            ref={catalogTrigger}
            type="button"
            className="primary"
            onClick={() => setCatalogOpen(true)}
          >
            <Plus size={18} aria-hidden="true" /> Widget ekle
          </button>
        </div>
      </header>

      <div className="overview-status">
        <span>
          {editing
            ? "Widget’leri tutamacından sürükleyin veya oklarla taşıyın."
            : `${layout.length} widget`}
        </span>
        {(api.data?.server_time || dashboard?.server_time) && (
          <span>
            Son veri{" "}
            <time dateTime={api.data?.server_time || dashboard?.server_time}>
              {formatDate(api.data?.server_time || dashboard?.server_time)}
            </time>
          </span>
        )}
      </div>
      <span className="overview-announcement" role="status">
        {announcement}
      </span>
      {storageError && (
        <p className="overview-empty" role="alert">
          Tarayıcı depolamasına erişilemedi. Düzen bu sayfa açıkken korunur.
        </p>
      )}
      {api.error && (
        <p className="overview-empty overview-attention" role="alert">
          Widget verileri güncellenemedi.
          {api.data && " Son alınan veriler gösteriliyor."}
        </p>
      )}

      {layout.length === 0 && (
        <div className="panel overview-blank">
          <ListChecks size={30} aria-hidden="true" />
          <h2>Genel bakışınız boş</h2>
          <p>İzlemek istediğiniz bilgileri widget kataloğundan seçin.</p>
        </div>
      )}
      <section
        className="overview-grid"
        ref={grid}
        aria-label="Genel bakış widget’leri"
      >
        {layout.map((id, index) => {
          const { title, icon: Icon, page } = widgets[id];
          return (
            <article
              key={id}
              data-overview-widget={id}
              className={`panel overview-widget${dropTarget === id && drag.current?.id !== id ? " overview-drop-target" : ""}`}
            >
              <header className="overview-widget-header">
                <span className="overview-widget-icon">
                  <Icon size={21} aria-hidden="true" />
                </span>
                <h2>{title}</h2>
                {id === "alarms" && c.firing_alerts !== undefined && (
                  <span
                    className={`overview-alarm-count${c.firing_alerts ? " overview-attention" : ""}`}
                  >
                    {number.format(c.firing_alerts)}
                  </span>
                )}
              </header>
              {editing && (
                <div
                  className="overview-widget-tools"
                  aria-label={`${title} düzenleme araçları`}
                >
                  <button
                    className="overview-grip"
                    type="button"
                    tabIndex={-1}
                    aria-label={`${title} sürükle`}
                    title="Sürükle ve bırak"
                    onPointerDown={(event) => startDrag(event, id)}
                    onPointerMove={dragOver}
                    onPointerUp={finishDrag}
                    onPointerCancel={clearDrag}
                    onLostPointerCapture={clearDrag}
                  >
                    <DotsSixVertical size={20} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label={`${title} yukarı taşı`}
                    disabled={index === 0}
                    onClick={() => move(id, index - 1)}
                  >
                    <ArrowUp size={17} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label={`${title} aşağı taşı`}
                    disabled={index === layout.length - 1}
                    onClick={() => move(id, index + 1)}
                  >
                    <ArrowDown size={17} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    aria-label={`${title} kaldır`}
                    onClick={() => {
                      save(
                        layout.filter((item) => item !== id),
                        `${title} kaldırıldı.`,
                      );
                      catalogTrigger.current?.focus();
                    }}
                  >
                    <X size={17} aria-hidden="true" />
                  </button>
                </div>
              )}
              <div className="overview-widget-body">
                {id !== "system" && !api.data ? (
                  <p className="overview-empty" role="status">
                    {api.error ? "Veri alınamadı." : "Yükleniyor…"}
                  </p>
                ) : (
                  content(id)
                )}
              </div>
              {page && (
                <footer>
                  <button
                    type="button"
                    className="text-button overview-details"
                    aria-label={`Ayrıntıları aç · ${title}`}
                    onClick={() => navigate(page)}
                  >
                    Ayrıntıları aç <ArrowRight size={16} aria-hidden="true" />
                  </button>
                </footer>
              )}
            </article>
          );
        })}
      </section>
      {catalogOpen && (
        <Dialog
          title="Widget kataloğu"
          className="overview-catalog"
          onClose={() => setCatalogOpen(false)}
        >
          <ul className="overview-catalog-list">
            {catalog.map((id) => {
              const { title, description, icon: Icon } = widgets[id];
              const added = layout.includes(id);
              return (
                <li key={id}>
                  <span className="overview-widget-icon">
                    <Icon size={20} aria-hidden="true" />
                  </span>
                  <div>
                    <strong>{title}</strong>
                    <p>{description}</p>
                  </div>
                  <button
                    type="button"
                    className="secondary"
                    disabled={added}
                    aria-label={`${added ? "Eklendi" : "Ekle"} · ${title}`}
                    onClick={() => save([...layout, id], `${title} eklendi.`)}
                  >
                    {added ? (
                      <Check size={16} aria-hidden="true" />
                    ) : (
                      <Plus size={16} aria-hidden="true" />
                    )}
                    {added ? "Eklendi" : "Ekle"}
                  </button>
                </li>
              );
            })}
          </ul>
        </Dialog>
      )}
    </div>
  );
}
