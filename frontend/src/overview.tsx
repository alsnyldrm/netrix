import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { ComponentType, PointerEvent, ReactNode } from "react";
import {
  Pulse,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Bell,
  Check,
  Circuitry,
  ChartBar,
  ChartLineUp,
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
  "job-trend": {
    title: "Görev trendi",
    description: "Son yedi günde sonuçlanan görevler.",
    icon: ChartLineUp,
    page: "jobs",
  },
  "backup-trend": {
    title: "Yedekleme trendi",
    description: "Son yedi günde oluşturulan ve arşivde bulunan yedekler.",
    icon: ChartLineUp,
    page: "configuration",
  },
  "alarm-trend": {
    title: "Alarm trendi",
    description: "Son yedi günde açılan alarmlar.",
    icon: ChartLineUp,
    page: "alerts",
  },
  "device-mix": {
    title: "Cihaz türleri",
    description: "En çok cihaz kaydı bulunan sekiz tür.",
    icon: ChartBar,
    page: "devices",
  },
  "firmware-mix": {
    title: "Firmware hedefleri",
    description: "Silinmemiş planlardaki hedeflerin son durumları.",
    icon: ChartBar,
    page: "firmware-plans",
  },
  "vlan-problems": {
    title: "Sorunlu IP’ler · VLAN",
    description: "En çok sorunlu IP çözümlemesi olan altı VLAN.",
    icon: ChartBar,
    page: "vlans",
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
type DayPoint = { day: string; count: number };
type Category = { label: string; count: number };
type WidgetData = {
  charts?: {
    daily: Record<"jobs" | "backups" | "alarms", DayPoint[]>;
    device_types: Category[];
    firmware: Record<string, number>;
    vlan_problems: Category[];
  };
  counts: Record<string, number>;
  alerts: AlarmEntry[];
  events: Entry[];
  server_time: string;
};
type Dashboard = { counts?: Record<string, number>; server_time?: string };
const catalog = Object.keys(widgets) as Widget[];
const chartWidgets: Widget[] = [
  "job-trend",
  "backup-trend",
  "alarm-trend",
  "device-mix",
  "vlan-problems",
  "firmware-mix",
];
const defaults: Widget[] = [
  "alarms",
  "gaps",
  ...chartWidgets,
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
    const legacy = Array.isArray(saved);
    const items: unknown = legacy
      ? saved
      : (saved as { widgets?: unknown } | null)?.widgets;
    if (Array.isArray(items)) {
      const valid = [
        ...new Set(items.filter((id): id is Widget => catalog.includes(id))),
      ];
      if (legacy && valid.length) {
        valid.splice(2, 0, ...chartWidgets.filter((id) => !valid.includes(id)));
      }
      return valid;
    }
  } catch {
    // A blocked or malformed storage entry uses the default layout.
  }
  return defaults;
}

type Segment = [label: string, value: number | undefined, tone: string];

function Distribution({
  title,
  values,
  stacked = false,
}: {
  title: string;
  values: Segment[];
  stacked?: boolean;
}) {
  if (values.some(([, value]) => value === undefined)) return null;
  const sizes = values.map(([, value]) => value ?? 0);
  const max =
    (stacked
      ? sizes.reduce((sum, value) => sum + value, 0)
      : Math.max(...sizes)) || 1;
  return (
    <figure className="overview-chart">
      <figcaption>{title}</figcaption>
      {stacked && (
        <div
          className="overview-chart-track overview-chart-stack"
          aria-hidden="true"
        >
          {values.map(([label, value, tone]) => (
            <i
              key={label}
              data-tone={tone}
              style={{ width: `${((value ?? 0) / max) * 100}%` }}
            />
          ))}
        </div>
      )}
      <dl className={stacked ? "overview-chart-legend" : "overview-chart-bars"}>
        {values.map(([label, value, tone]) => (
          <div key={label}>
            <dt>
              <i data-tone={tone} aria-hidden="true" />
              {label}
            </dt>
            <dd>{number.format(value ?? 0)}</dd>
            {!stacked && (
              <div className="overview-chart-track" aria-hidden="true">
                <i
                  data-tone={tone}
                  style={{ width: `${((value ?? 0) / max) * 100}%` }}
                />
              </div>
            )}
          </div>
        ))}
      </dl>
    </figure>
  );
}

const shortDay = new Intl.DateTimeFormat("tr-TR", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

function Trend({
  points,
  label,
}: {
  points: DayPoint[] | undefined;
  label: string;
}) {
  if (!points?.length)
    return <p className="overview-empty">Grafik verisi alınamadı.</p>;
  const peak = Math.max(1, ...points.map(({ count }) => count));
  const line = points.map(
    ({ count }, index) => `${12 + index * 46},${94 - (count / peak) * 76}`,
  );
  const total = points.reduce((sum, { count }) => sum + count, 0);
  return (
    <figure className="overview-chart overview-trend">
      <figcaption>
        <strong>{number.format(total)}</strong>
        <span>{label} · 7 gün</span>
      </figcaption>
      {total > 0 ? (
        <svg viewBox="0 0 300 100" aria-hidden="true">
          {[18, 56, 94].map((y) => (
            <line
              key={y}
              x1="12"
              x2="288"
              y1={y}
              y2={y}
              className="overview-trend-gridline"
            />
          ))}
          <polygon
            points={`12,94 ${line.join(" ")} 288,94`}
            className="overview-trend-fill"
          />
          <polyline points={line.join(" ")} className="overview-trend-line" />
          {line.map((point) => {
            const [cx, cy] = point.split(",");
            return (
              <circle
                key={cx}
                cx={cx}
                cy={cy}
                r="3"
                className="overview-trend-point"
              />
            );
          })}
        </svg>
      ) : (
        <p className="overview-empty">Bu aralıkta kayıt yok.</p>
      )}
      <dl className="overview-trend-days">
        {points.map(({ day, count }) => (
          <div key={day}>
            <dt>
              <time dateTime={day}>{shortDay.format(new Date(day))}</time>
            </dt>
            <dd>{number.format(count)}</dd>
          </div>
        ))}
      </dl>
    </figure>
  );
}

const firmwareStates = [
  ["queued", "Kuyrukta", "accent"],
  ["running", "Çalışıyor", "accent"],
  ["checked", "Kontrol edildi", "success"],
  ["staged", "Hazırlandı", "success"],
  ["succeeded", "Tamamlandı", "success"],
  ["failed", "Başarısız", "danger"],
  ["attention", "Müdahale bekliyor", "warning"],
  ["cancelled", "İptal edildi", "accent"],
] as const;

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
  const drag = useRef<{
    id: Widget;
    x: number;
    y: number;
    active: boolean;
  } | null>(null);
  const pointer = useRef({ x: 0, y: 0 });
  const frame = useRef(0);
  const preview = useRef<HTMLDivElement>(null);
  const [dragged, setDragged] = useState<Widget | null>(null);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);
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
      localStorage.setItem(storageKey, JSON.stringify({ widgets: next }));
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
  function targetAt(x: number, y: number): Widget | null {
    if (
      !grid.current ||
      !document.elementFromPoint(x, y) ||
      y < 0 ||
      y >= window.innerHeight
    )
      return null;
    const bounds = grid.current.getBoundingClientRect();
    if (
      x < bounds.left - 16 ||
      x > bounds.right + 16 ||
      y < bounds.top - 16 ||
      y > bounds.bottom + 16
    )
      return null;
    let nearest: Widget | null = null;
    let distance = Infinity;
    for (const card of grid.current.querySelectorAll<HTMLElement>(
      "[data-overview-widget]",
    )) {
      const rect = card.getBoundingClientRect();
      const dx = Math.max(rect.left - x, 0, x - rect.right);
      const dy = Math.max(rect.top - y, 0, y - rect.bottom);
      if (dx * dx + dy * dy < distance) {
        distance = dx * dx + dy * dy;
        nearest = card.dataset.overviewWidget as Widget;
      }
      if (distance === 0) break;
    }
    return nearest;
  }
  function updateDrag() {
    const { x, y } = pointer.current;
    const edge = 100;
    const scroll =
      y < edge
        ? Math.max(-20, (y - edge) / 3)
        : Math.min(20, Math.max(0, (y - (window.innerHeight - edge)) / 3));
    if (scroll) window.scrollBy(0, scroll);
    if (preview.current)
      preview.current.style.transform = `translate(${Math.min(x + 14, window.innerWidth - preview.current.offsetWidth - 8)}px, ${Math.min(y + 14, window.innerHeight - 50)}px)`;
    setDropTarget(targetAt(x, y));
    frame.current = requestAnimationFrame(updateDrag);
  }
  function startDrag(event: PointerEvent<HTMLButtonElement>, id: Widget) {
    if (!event.isPrimary || event.button !== 0) return;
    drag.current = { id, x: event.clientX, y: event.clientY, active: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function dragOver(event: PointerEvent<HTMLButtonElement>) {
    if (!drag.current) return;
    const { x, y, id, active } = drag.current;
    pointer.current = { x: event.clientX, y: event.clientY };
    if (active || Math.hypot(event.clientX - x, event.clientY - y) < 6) return;
    drag.current.active = true;
    setDragged(id);
    frame.current = requestAnimationFrame(updateDrag);
  }
  function clearDrag() {
    cancelAnimationFrame(frame.current);
    setDropTarget(null);
    setDragged(null);
    drag.current = null;
  }
  function finishDrag(event: PointerEvent<HTMLButtonElement>) {
    const target = targetAt(event.clientX, event.clientY);
    if (drag.current?.active) {
      event.preventDefault();
      if (target) move(drag.current.id, layout.indexOf(target));
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
          <>
            {id === "alarms" && (
              <Distribution
                title="Açık alarmların önem dağılımı"
                stacked
                values={[
                  ["Kritik", d.alarm_critical, "danger"],
                  ["Uyarı", d.alarm_warning, "warning"],
                  ["Bilgi", d.alarm_info, "accent"],
                ]}
              />
            )}
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
          </>
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
          <>
            <Distribution
              title="Aktif cihazların erişilebilirliği"
              stacked
              values={[
                ["Erişilebilir", c.reachable, "success"],
                ["Doğrulanmamış", d.unverified, "warning"],
              ]}
            />
            <StatRows
              rows={[
                ["Envanterdeki cihaz", c.devices],
                ["Aktif cihaz", c.active_devices],
                ["Lokasyon", c.sites],
              ]}
            />
          </>
        );
      case "ipam":
        return (
          <>
            <Distribution
              title="Kayıtlı IP çözümleme sonuçları"
              stacked
              values={[
                ["Başarılı", d.ip_resolved, "success"],
                ["Sorunlu", d.ip_problems, "danger"],
              ]}
            />
            <StatRows
              rows={[
                ["VLAN", c.vlans],
                ["Kayıtlı adres", c.addresses],
              ]}
            />
          </>
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
          <>
            <Distribution
              title="Son 24 saatte sonuçlanan görevler"
              values={[
                ["Başarılı", d.succeeded, "success"],
                ["Kısmi", d.partial, "warning"],
                ["Başarısız", d.failed, "danger"],
              ]}
            />
            <StatRows
              rows={[
                ["Kuyrukta", d.queued],
                ["Çalışıyor", d.running],
              ]}
            />
          </>
        );
      case "job-trend":
        return (
          <Trend
            points={api.data?.charts?.daily.jobs}
            label="Sonuçlanan görev"
          />
        );
      case "backup-trend":
        return (
          <Trend
            points={api.data?.charts?.daily.backups}
            label="Kayıtlı yedek"
          />
        );
      case "alarm-trend":
        return (
          <Trend points={api.data?.charts?.daily.alarms} label="Açılan alarm" />
        );
      case "device-mix":
      case "vlan-problems": {
        const types = id === "device-mix";
        const rows = types
          ? api.data?.charts?.device_types
          : api.data?.charts?.vlan_problems;
        if (!rows?.length)
          return (
            <p className="overview-empty">
              {types ? "Henüz cihaz kaydı yok." : "Sorunlu IP çözümlemesi yok."}
            </p>
          );
        return (
          <Distribution
            title={
              types
                ? "Cihaz sayısına göre ilk 8 tür"
                : "Sorunlu adres sayısına göre ilk 6 VLAN"
            }
            values={rows.map(({ label, count }) => [
              label,
              count,
              types ? "accent" : "danger",
            ])}
          />
        );
      }
      case "firmware-mix": {
        const statuses = api.data?.charts?.firmware;
        const rows: Segment[] = firmwareStates
          .filter(([status]) => !!statuses?.[status])
          .map(([status, label, tone]) => [label, statuses?.[status], tone]);
        if (!rows.length)
          return <p className="overview-empty">Henüz firmware hedefi yok.</p>;
        return (
          <Distribution title="Planlardaki hedef durumları" values={rows} />
        );
      }
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
    <div className={`overview-workspace${dragged ? " overview-dragging" : ""}`}>
      {dragged &&
        createPortal(
          <div
            ref={preview}
            className="overview-drag-preview"
            aria-hidden="true"
          >
            <DotsSixVertical size={20} /> {widgets[dragged].title}
          </div>,
          document.body,
        )}
      <header className="overview-command">
        <div>
          <h1>Genel bakış</h1>
          <p>Ağ, sistem ve operasyon durumu</p>
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
            : `${layout.length} widget · Başlıktaki tutamaçtan sürükleyin`}
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
              className={`panel overview-widget${dragged === id ? " overview-drag-source" : ""}${dropTarget === id && dragged !== id ? " overview-drop-target" : ""}`}
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
                <button
                  className="overview-grip"
                  type="button"
                  onClick={(event) => {
                    if (!editing && event.detail === 0) setEditing(true);
                  }}
                  aria-label={`${title} sürükle`}
                  title="Sürükle ve bırak · Klavyeyle düzenlemek için Enter"
                  onPointerDown={(event) => startDrag(event, id)}
                  onPointerMove={dragOver}
                  onPointerUp={finishDrag}
                  onPointerCancel={clearDrag}
                  onLostPointerCapture={clearDrag}
                >
                  <DotsSixVertical size={20} aria-hidden="true" />
                </button>
              </header>
              {editing && (
                <div
                  className="overview-widget-tools"
                  aria-label={`${title} düzenleme araçları`}
                >
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
