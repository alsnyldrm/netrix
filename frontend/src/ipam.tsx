import React, { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  GearSix,
  Columns,
  Funnel,
  Trash,
  Play,
  Stop,
  Plus,
  Waveform,
  PencilSimple,
  ArrowsClockwise,
} from "@phosphor-icons/react";
import {
  api,
  Badge,
  Dialog,
  date,
  speed,
  PAGES,
  resourceChoices,
  dependentChange,
} from "./main";
import { allRows, Filters, ColumnPicker } from "./inventory";
import "./ipam.css";

type Row = Record<string, any>;
const sourceName = (v: string) =>
  ({
    vcenter: "VMware vCenter",
    windows_dhcp: "Windows DHCP",
    inventory: "Envanter",
    dns: "DNS",
    icmp: "Ping",
  })[v] || v;
const stateName = (v: string) =>
  ({
    reachable: "Yanıt var",
    no_reply: "Yanıt yok",
    poweredOn: "Açık",
    poweredOff: "Kapalı",
    suspended: "Askıda",
    unassigned: "Atanmamış",
    network: "Ağ / yayın",
    active: "Aktif",
    reserved: "Ayrılmış",
    deprecated: "Kullanım dışı",
  })[v] ||
  v ||
  "Bilinmiyor";
const settingsKeys = [
  "dns_server_id",
  "vlan_device_id",
  "scan_authorized",
  "warning_threshold",
  "ping_enabled",
  "ping_interval",
  "discovery_enabled",
  "discovery_interval",
];
function ErrorNote({ error }: { error: string }) {
  return error ? (
    <div className="error" role="alert">
      {error}
    </div>
  ) : null;
}
function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="ipam-field">
      <span>{label}</span>
      {children}
    </label>
  );
}

function PrefixSettings({
  prefix,
  refs,
  close,
  saved,
}: {
  prefix: Row;
  refs: Record<string, Row[]>;
  close: () => void;
  saved: (row: Row) => void;
}) {
  const [values, setValues] = useState<Row>(
    Object.fromEntries(settingsKeys.map((k) => [k, prefix[k]])),
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (key: string, value: any) =>
    setValues((v) => ({ ...v, [key]: value }));
  const choices = (key: string, label: string, items: Row[]) => (
    <Field label={label}>
      <select
        value={values[key] || ""}
        onChange={(e) => set(key, e.target.value || null)}
      >
        <option value="">Seçilmedi</option>
        {items.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name || r.cidr}
          </option>
        ))}
      </select>
    </Field>
  );
  return (
    <Dialog title={`${prefix.cidr} · Ağ bloğu ayarları`} onClose={close}>
      <form
        className="ipam-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            const updated = await api(
              `/ipam/prefixes/${prefix.id}/settings`,
              "PUT",
              values,
            );
            saved(updated);
            close();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <ErrorNote error={error} />
        <div className="ipam-fields">
          {choices("dns_server_id", "DNS sunucusu", refs["dns-servers"] || [])}
          {choices(
            "vlan_device_id",
            "VLAN’ın bulunduğu cihaz",
            (refs.devices || []).filter((d) => d.vrf_id === prefix.vrf_id),
          )}
          <label className="ipam-check">
            <input
              type="checkbox"
              checked={!!values.scan_authorized}
              onChange={(e) => {
                set("scan_authorized", e.target.checked);
                if (!e.target.checked) {
                  set("ping_enabled", false);
                  set("discovery_enabled", false);
                }
              }}
            />
            <span>
              Bu ağ bloğunda keşif ve ping işlemleri yetkilendirilmiştir
            </span>
          </label>
          <Field label="IP kullanım uyarı eşiği (%)">
            <input
              type="number"
              min="1"
              max="100"
              required
              value={values.warning_threshold}
              onChange={(e) => set("warning_threshold", Number(e.target.value))}
            />
          </Field>
          <Field label="Ping aralığı (saniye)">
            <input
              type="number"
              min="30"
              max="86400"
              required
              value={values.ping_interval}
              onChange={(e) => set("ping_interval", Number(e.target.value))}
            />
          </Field>
          <Field label="Yeni sunucu keşif aralığı (saniye)">
            <input
              type="number"
              min="60"
              max="2592000"
              required
              value={values.discovery_interval}
              onChange={(e) =>
                set("discovery_interval", Number(e.target.value))
              }
            />
          </Field>
          <label className="ipam-check">
            <input
              type="checkbox"
              disabled={!values.scan_authorized}
              checked={values.ping_enabled}
              onChange={(e) => set("ping_enabled", e.target.checked)}
            />
            <span>IP durumunu düzenli kontrol et</span>
          </label>
          <label className="ipam-check">
            <input
              type="checkbox"
              disabled={!values.scan_authorized}
              checked={values.discovery_enabled}
              onChange={(e) => set("discovery_enabled", e.target.checked)}
            />
            <span>Yeni sunucuları düzenli ekle</span>
          </label>
        </div>
        <p className="ipam-hint">
          Ping kayıtlı IP’leri kontrol eder. Yeni sunucu keşfi yetkili kapsamda
          tarama yapar; seçili DNS’ten isimleri alır. MAC ve cihaz bilgileri
          envanter / entegrasyon gözlemleriyle tamamlanır. Yanıt alınamaması
          IP’nin boş veya cihazın kapalı olduğunu kanıtlamaz.
        </p>
        <div className="ipam-actions">
          <button type="button" className="secondary" onClick={close}>
            Vazgeç
          </button>
          <button className="primary" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Ayarları kaydet"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function TrafficChart({ items }: { items: Row[] }) {
  const values = items
    .flatMap((r) => [r.in_bps, r.out_bps])
    .filter((v) => v != null);
  const maximum = Math.max(1, ...values);
  return (
    <div className="ipam-chart">
      <svg
        viewBox="0 0 600 160"
        role="img"
        aria-label="Giriş ve çıkış trafik grafiği"
      >
        <line x1="0" y1="145" x2="600" y2="145" stroke="var(--border-strong)" />
        {(["in_bps", "out_bps"] as const).map((key, k) => (
          <g
            key={key}
            stroke={k ? "var(--chart-out)" : "var(--chart-in)"}
            fill="none"
            strokeWidth="2"
          >
            {items.map(
              (r, i) =>
                r[key] != null && (
                  <React.Fragment key={r.id}>
                    <circle
                      cx={10 + (i * 580) / Math.max(1, items.length - 1)}
                      cy={145 - (r[key] / maximum) * 130}
                      r="2"
                    />
                    {i > 0 && items[i - 1][key] != null && (
                      <line
                        x1={
                          10 + ((i - 1) * 580) / Math.max(1, items.length - 1)
                        }
                        y1={145 - (items[i - 1][key] / maximum) * 130}
                        x2={10 + (i * 580) / Math.max(1, items.length - 1)}
                        y2={145 - (r[key] / maximum) * 130}
                      />
                    )}
                  </React.Fragment>
                ),
            )}
          </g>
        ))}
      </svg>
      <div className="ipam-chart-legend">
        <span>Giriş: {speed(items.at(-1)?.in_bps)}</span>
        <span>Çıkış: {speed(items.at(-1)?.out_bps)}</span>
        <span>Ölçek: {speed(maximum)}</span>
      </div>
    </div>
  );
}

function AddressDetail({
  row,
  close,
  canWrite,
}: {
  row: Row;
  close: () => void;
  canWrite: boolean;
}) {
  const [detail, setDetail] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState("");
  const [watching, setWatching] = useState(false);
  const [items, setItems] = useState<Row[]>([]);
  const [job, setJob] = useState<Row | null>(null);
  const liveJob = useRef<string | null>(null);
  useEffect(() => {
    let active = true;
    api("/ipam/addresses/" + row.id)
      .then((d) => {
        if (active) {
          setDetail(d);
          if (d.integrations.length === 1 && !d.interfaces.length)
            setSelection("v:" + d.integrations[0].integration_id);
          else if (d.interfaces.length === 1 && !d.integrations.length)
            setSelection("i:" + d.interfaces[0].interface_id);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [row.id]);
  useEffect(() => {
    if (!watching || !selection) return;
    let active = true,
      timer: ReturnType<typeof setTimeout>;
    const payload = selection.startsWith("i:")
      ? { interface_id: selection.slice(2) }
      : { integration_id: selection.slice(2) };
    const run = async () => {
      try {
        if (document.hidden) {
          timer = setTimeout(run, 5000);
          return;
        }
        let status = liveJob.current
          ? await api("/jobs/" + liveJob.current)
          : null;
        if (
          status &&
          ["failed", "cancelled", "partial"].includes(status.status)
        ) {
          throw new Error(status.error || "Canlı izleme durdu.");
        }
        if (!status || status.status === "succeeded") {
          status = await api(
            "/ipam/addresses/" + row.id + "/live",
            "POST",
            payload,
          );
          if (!active) {
            await api("/jobs/" + status.id + "/cancel", "POST");
            return;
          }
          liveJob.current = status.id;
        }
        const data = await api("/ipam/addresses/" + row.id + "/traffic");
        if (active) {
          setJob(status);
          setItems(
            data.items.filter((r: Row) =>
              selection.startsWith("i:")
                ? r.source_key === "interface:" + selection.slice(2)
                : r.source_key.startsWith(
                    "vcenter:" + selection.slice(2) + ":",
                  ),
            ),
          );
          timer = setTimeout(run, 5000);
        }
      } catch (e: any) {
        if (active) {
          setError(e.message);
          setWatching(false);
        }
      }
    };
    run();
    return () => {
      active = false;
      clearTimeout(timer);
      const id = liveJob.current;
      liveJob.current = null;
      if (id) api("/jobs/" + id + "/cancel", "POST").catch(() => {});
    };
  }, [watching, selection, row.id]);
  return (
    <Dialog title={`${row.address} · IP ayrıntıları`} onClose={close} wide>
      <div className="ipam-form">
        <ErrorNote error={error} />
        {detail ? (
          <>
            <dl className="ipam-summary">
              {[
                ["Hostname", detail.hostname],
                ["MAC adresi", detail.mac_address],
                ["Bağlı switch", detail.connected_device],
                [
                  "Port grubu / Sanal ağ",
                  detail.connection_type === "vcenter" ? detail.network : "",
                ],
                ["Bağlı port", detail.connected_port],
                ["İşletim sistemi", detail.operating_system],
                ["Kabinet no", detail.cabinet],
                ["Lokasyon", detail.location],
                ["VM güç durumu", stateName(detail.power_state)],
                ["Ping", stateName(detail.reachability)],
                ["Son gözlem", date(detail.last_observed_at)],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v || "—"}</dd>
                </div>
              ))}
            </dl>
            <section className="ipam-section">
              <h3>Bağlantı ve canlı trafik</h3>
              <p className="ipam-hint">
                {detail.connection_type === "routed"
                  ? "Firewall ARP/NDP kaydındaki ağ arayüzü gösteriliyor. Bu arayüzün trafiği ağın toplamıdır; cihazın fiziksel switch portu henüz belirlenmemiştir."
                  : "VMware bağlantısında sanal ağ kartının trafiği izlenir. Fiziksel switch bağlantısında ölçüm, doğrulanan portun toplam trafiğidir."}
              </p>
              <Field label="İzlenecek bağlantı">
                <select
                  value={selection}
                  disabled={watching}
                  onChange={(e) => {
                    setSelection(e.target.value);
                    setItems([]);
                  }}
                >
                  <option value="">Bağlantı seçin</option>
                  {detail.interfaces.map((v: Row) => (
                    <option key={v.interface_id} value={"i:" + v.interface_id}>
                      {v.device_name} / {v.interface_name} ·{" "}
                      {v.ambiguous ? "Belirsiz aday" : "Port eşleşmesi"} · %
                      {Math.round(v.confidence * 100)}
                    </option>
                  ))}
                  {detail.integrations.map((v: Row) => (
                    <option
                      key={v.integration_id}
                      value={"v:" + v.integration_id}
                    >
                      {v.switch_name || v.name} / {v.network || v.vm_id}
                      {v.dvport ? " / Port " + v.dvport : ""}
                    </option>
                  ))}
                </select>
              </Field>
              {!detail.interfaces.length && !detail.integrations.length && (
                <p className="ipam-hint">
                  Güncel port / vCenter eşleşmesi yok. Envanter ölçümlerini veya
                  entegrasyon eşitlemesini çalıştırın.
                </p>
              )}
              <div className="ipam-actions">
                {watching ? (
                  <button
                    className="secondary"
                    onClick={() => setWatching(false)}
                  >
                    <Stop size={16} aria-hidden="true" />
                    İzlemeyi durdur
                  </button>
                ) : (
                  <button
                    className="primary"
                    disabled={!selection || !canWrite}
                    onClick={() => {
                      setError("");
                      setWatching(true);
                    }}
                  >
                    <Waveform size={18} aria-hidden="true" />
                    Networkü izle
                  </button>
                )}
                <span role="status">
                  {watching
                    ? `5 sn yenileme · ${job?.status === "running" ? "Ölçüm alınıyor" : "Görev bekleniyor"}`
                    : "İzleme durduruldu"}
                </span>
              </div>
              <p className="ipam-hint">
                {selection.startsWith("v:")
                  ? `VMware ölçüm aralığı: ${items.at(-1)?.interval_seconds || "kaynak bekleniyor"}${items.length ? " sn" : ""}. Ekran 5 sn’de yenilenir; aynı kaynak ölçümü tekrar çizilmez.`
                  : "SNMP sayaçları 5 saniyede bir okunur; ilk örnek hız hesabının başlangıcıdır."}{" "}
                Son ölçüm: {date(items.at(-1)?.sampled_at)}.
              </p>
              {items.length ? (
                <>
                  <TrafficChart items={items} />
                  <details>
                    <summary>Ölçümleri tablo olarak göster</summary>
                    <div
                      className="table-scroll"
                      tabIndex={0}
                      role="region"
                      aria-label="IPAM kayıt tablosu"
                    >
                      <table>
                        <thead>
                          <tr>
                            <th>Zaman</th>
                            <th>Giriş</th>
                            <th>Çıkış</th>
                            <th>Aralık</th>
                          </tr>
                        </thead>
                        <tbody>
                          {items.slice(-12).map((r) => (
                            <tr key={r.id}>
                              <td>{date(r.sampled_at)}</td>
                              <td>{speed(r.in_bps)}</td>
                              <td>{speed(r.out_bps)}</td>
                              <td>{r.interval_seconds} sn</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </>
              ) : (
                <p className="ipam-hint">Henüz trafik ölçümü yok.</p>
              )}
            </section>
            <section className="ipam-section">
              <h3>Kaynak gözlemleri</h3>
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="IPAM kayıt tablosu"
              >
                <table>
                  <thead>
                    <tr>
                      <th>Kaynak</th>
                      <th>Hostname / MAC</th>
                      <th>İşletim sistemi / ağ</th>
                      <th>Gözlem zamanı</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.observations.map((o: Row) => (
                      <tr key={o.id}>
                        <td>{sourceName(o.source)}</td>
                        <td>
                          {o.data.hostname || "—"}
                          <small className="ipam-sub">
                            {o.data.mac_address || "—"}
                          </small>
                        </td>
                        <td>
                          {o.data.operating_system ||
                            o.data.network ||
                            stateName(o.data.reachability)}
                        </td>
                        <td>{date(o.observed_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : (
          <p>IP ayrıntıları yükleniyor…</p>
        )}
      </div>
    </Dialog>
  );
}

export function IPAMWorkspace({
  page,
  refs,
  refresh,
  user,
  onEdit,
  onSaved,
}: {
  page: string;
  refs: Record<string, Row[]>;
  refresh: number;
  user: Row;
  onEdit: (resource: string, row: Row) => void;
  onSaved: () => void;
}) {
  const [prefix, setPrefix] = useState<Row | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState("0");
  const [offset, setOffset] = useState("0");
  const [query, setQuery] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<Row | null>(null);
  const [detail, setDetail] = useState<Row | null>(null);
  const [job, setJob] = useState<Row | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [registeredSearch, setRegisteredSearch] = useState(false);
  const [rules, setRules] = useState<any[]>([]);
  const [filterOpen, setFilterOpen] = useState(false);
  const [columnOpen, setColumnOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [columns, setColumns] = useState<{ key: string; label: string }[]>([]);
  const storageKey = `netrix.ipam.columns.${user.id}`;
  const defaults = [
    "address",
    "hostname",
    "mac_address",
    "connected_device",
    "connected_port",
    "network",
    "vlan",
    "operating_system",
    "cabinet",
    "location",
    "availability",
    "sources",
  ];
  const [shown, setShown] = useState<string[]>(() => {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || "null");
      return Array.isArray(value) && value.length ? value : defaults;
    } catch {
      return defaults;
    }
  });
  const canWrite = user.role !== "viewer";
  const isBlocks = page === "prefixes" && !prefix;
  const visible = columns.filter((c) => shown.includes(c.key));
  const previousQuery = useRef(query);
  const previousScope = useRef("");
  useEffect(() => {
    let active = true;
    const scope = JSON.stringify([
      page,
      prefix?.id,
      offset,
      query,
      activeOnly,
      rules,
    ]);
    if (previousScope.current !== scope) setLoaded(false);
    previousScope.current = scope;
    const delay = previousQuery.current !== query ? 200 : 0;
    previousQuery.current = query;
    const timer = setTimeout(async () => {
      try {
        const params = `offset=${offset}&limit=100&q=${encodeURIComponent(query)}&filters=${encodeURIComponent(JSON.stringify(rules))}`;
        const result = prefix
          ? await api(
              `/ipam/prefixes/${prefix.id}/addresses?active_only=${activeOnly}&${params}`,
            )
          : page === "addresses"
            ? await api(`/ipam/addresses?${params}`)
            : await api(
                `/prefixes?limit=100&offset=${offset}&q=${encodeURIComponent(query)}`,
              );
        if (active) {
          setRows(result.items);
          setTotal(String(result.total));
          setColumns(result.columns || []);
          if (result.prefix) setPrefix(result.prefix);
          setRegisteredSearch(!!result.registered_search);
          setError("");
          setLoaded(true);
        }
      } catch (e: any) {
        if (active) {
          setError(e.message);
          setLoaded(true);
        }
      }
    }, delay);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [page, prefix?.id, offset, query, activeOnly, refresh, rules]);
  useEffect(() => {
    setSelected([]);
  }, [prefix?.id, query, rules, activeOnly]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let active = true;
    const timer = setTimeout(async () => {
      try {
        const next = await api("/jobs/" + job.id);
        if (active) {
          setJob(next);
          onSaved();
        }
      } catch (e: any) {
        if (active) setError(e.message);
      }
    }, 2000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [job]);
  const trigger = async (action: string) => {
    if (!prefix) return;
    setBusy(true);
    setError("");
    try {
      setJob(await api(`/ipam/prefixes/${prefix.id}/${action}`, "POST"));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const choosePrefix = (row: Row | null) => {
    setPrefix(row);
    setRows([]);
    setOffset("0");
    setQuery("");
    setRules([]);
  };
  const selectionDone = () => {
    setSelected([]);
    setBulkOpen(false);
    onSaved();
  };
  const renderCell = (r: Row, key: string) => {
    if (key === "address")
      return r.id ? (
        <button className="text-button mono" onClick={() => setDetail(r)}>
          {r.address}
        </button>
      ) : (
        <span className="mono">{r.address}</span>
      );
    if (key === "availability") {
      const state = r.availability || (r.id ? "unknown" : r.status);
      return (
        <span className={`ipam-state ${state}`}>
          <i aria-hidden="true" />
          {(
            {
              active: "Aktif",
              passive: "Pasif",
              unknown: "Bilinmiyor",
              unassigned: "Atanmamış",
              network: "Ağ / yayın",
            } as Row
          )[state] || stateName(state)}
        </span>
      );
    }
    if (key === "status") return stateName(r.status);
    if (key === "sources") return r.sources?.map(sourceName).join(", ") || "—";
    if (["connected_device", "connected_port"].includes(key))
      return (
        <>
          {r[key] || "—"}
          {key === "connected_device" && r.connection_ambiguous && (
            <small className="ipam-sub">Bağlantı doğrulanamadı</small>
          )}
        </>
      );
    return r[key] || "—";
  };
  return (
    <div className="ipam-workspace">
      <ErrorNote error={error} />
      {prefix && (
        <section className="panel ipam-block-header">
          <div className="ipam-actions">
            <button className="secondary" onClick={() => choosePrefix(null)}>
              <ArrowLeft size={17} aria-hidden="true" />
              Ağ blokları
            </button>
            <h2>{prefix.display_name || prefix.cidr}</h2>
          </div>
          <p>
            {prefix.used || 0} / {prefix.capacity} aktif IP · %
            {prefix.utilization || 0} kullanım · Uyarı eşiği %
            {prefix.warning_threshold}
          </p>
          <p className="ipam-hint">
            Doluluk, son ping kontrolünde yanıt veren aktif IP’lere göre
            hesaplanır. Yanıt vermeyen IP’ler doluluğa dahil edilmez.
          </p>
          <div className="ipam-actions">
            {canWrite && (
              <>
                <button
                  className="secondary"
                  onClick={() => onEdit("prefixes", prefix)}
                >
                  <PencilSimple size={17} />
                  Ağ bloğunu düzenle
                </button>
                <button
                  className="secondary"
                  onClick={() => setSettings(prefix)}
                >
                  <GearSix size={17} />
                  Ağ bloğu ayarları
                </button>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => trigger("ping")}
                >
                  IP durumunu kontrol et
                </button>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() => trigger("discover")}
                >
                  <Plus size={17} />
                  Yeni sunucuları ekle
                </button>
              </>
            )}
          </div>
          {prefix.threshold_exceeded && (
            <p className="ipam-warning" role="status">
              IP kullanımı %{prefix.utilization}: %{prefix.warning_threshold}{" "}
              uyarı eşiğine ulaşıldı.
            </p>
          )}
        </section>
      )}
      {job && (
        <div className="panel ipam-job" role="status">
          <Badge value={job.status} />
          <span>
            {job.progress}/{job.total} adres ·{" "}
            {job.error ||
              (job.status === "succeeded"
                ? "İşlem tamamlandı."
                : "Görev merkezinden de izleyebilirsiniz.")}
          </span>
          {canWrite && ["queued", "running"].includes(job.status) && (
            <button
              className="secondary"
              onClick={async () => {
                try {
                  setJob(await api("/jobs/" + job.id + "/cancel", "POST"));
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            >
              İptal et
            </button>
          )}
        </div>
      )}
      <section className="panel table-panel">
        <div className="toolbar">
          <div className="table-title">
            <b>
              {prefix
                ? activeOnly
                  ? "Ağ içindeki aktif IP adresleri"
                  : "Ağ içindeki tüm IP adresleri"
                : isBlocks
                  ? "Ağ blokları"
                  : "IP adresleri"}
            </b>
            <span className="count-pill">{total}</span>
          </div>
          <div className="ipam-table-tools">
            <label className="search-box">
              <input
                aria-label="IPAM kayıtlarında ara"
                placeholder={isBlocks ? "Ağ ara…" : "Tüm alanlarda ara…"}
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setOffset("0");
                }}
              />
            </label>
            {!isBlocks && (
              <>
                <button
                  className="secondary"
                  onClick={() => setFilterOpen(true)}
                >
                  <Funnel size={17} />
                  Filtreler{rules.length ? ` (${rules.length})` : ""}
                </button>
                <button
                  className="secondary"
                  onClick={() => setColumnOpen(true)}
                >
                  <Columns size={17} />
                  Sütunlar
                </button>
              </>
            )}
            {prefix && (
              <label className="ipam-check">
                <input
                  type="checkbox"
                  checked={activeOnly}
                  onChange={(e) => {
                    setActiveOnly(e.target.checked);
                    setOffset("0");
                  }}
                />
                Yalnızca aktif IP’ler
              </label>
            )}
          </div>
        </div>
        {registeredSearch && (
          <p className="ipam-hint ipam-notice">
            Büyük adres alanında arama ve filtreler kayıtlı IP’lerde uygulanır.
            Tüm adreslere dönmek için aramayı ve filtreleri temizleyin.
          </p>
        )}
        {!!selected.length && (
          <div
            className="ipam-bulkbar"
            role="region"
            aria-label="Seçilen IP işlemleri"
          >
            <strong>{selected.length} IP seçildi</strong>
            <button className="secondary" onClick={() => setBulkOpen(true)}>
              <PencilSimple size={17} />
              Düzenle
            </button>
            {user.role === "admin" && (
              <button
                className="secondary danger"
                disabled={busy}
                onClick={async () => {
                  if (
                    !window.confirm(
                      `${selected.length} IP kaydı silinsin mi? Kaynaklar tekrar keşfederse yeniden eklenebilir.`,
                    )
                  )
                    return;
                  setBusy(true);
                  try {
                    await api("/ipam/addresses/bulk", "POST", {
                      ids: selected,
                      action: "delete",
                    });
                    selectionDone();
                  } catch (e: any) {
                    setError(e.message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Trash size={17} />
                Sil
              </button>
            )}
            <button className="text-button" onClick={() => setSelected([])}>
              Seçimi temizle
            </button>
          </div>
        )}
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="IPAM kayıt tablosu"
        >
          <table className={!isBlocks ? "ipam-address-table" : undefined}>
            <thead>
              <tr>
                {!isBlocks && canWrite && (
                  <th className="ipam-select">
                    <input
                      type="checkbox"
                      aria-label="Sayfadaki IP kayıtlarını seç"
                      checked={
                        rows.some((r) => r.id) &&
                        rows
                          .filter((r) => r.id)
                          .every((r) => selected.includes(r.id))
                      }
                      onChange={(e) =>
                        setSelected(
                          e.target.checked
                            ? [
                                ...new Set([
                                  ...selected,
                                  ...rows.filter((r) => r.id).map((r) => r.id),
                                ]),
                              ]
                            : selected.filter(
                                (id) => !rows.some((r) => r.id === id),
                              ),
                        )
                      }
                    />
                  </th>
                )}
                {(isBlocks
                  ? ["Ağ bloğu", "VLAN", "Lokasyon", "Kullanım", "Uyarı eşiği"]
                  : visible.map((c) => c.label)
                ).map((label) => (
                  <th key={label}>{label}</th>
                ))}
                <th>İşlemler</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) =>
                isBlocks ? (
                  <tr key={r.id}>
                    <td>
                      <button
                        className="text-button mono"
                        onClick={() => choosePrefix(r)}
                      >
                        {r.cidr}
                      </button>
                      <small className="ipam-sub">{r.description}</small>
                    </td>
                    <td>{r.vlan || "VLAN belirtilmedi"}</td>
                    <td>
                      {refs.sites?.find((v) => v.id === r.site_id)?.name || "—"}
                    </td>
                    <td>
                      <span
                        className={r.threshold_exceeded ? "ipam-warning" : ""}
                      >
                        {r.used} / {r.capacity} · %{r.utilization}
                      </span>
                    </td>
                    <td>%{r.warning_threshold}</td>
                    <td>
                      <div className="ipam-actions">
                        {canWrite && (
                          <>
                            <button
                              className="icon-button"
                              aria-label={`${r.cidr} ayarları`}
                              onClick={() => setSettings(r)}
                            >
                              <GearSix size={18} />
                            </button>
                            <button
                              className="icon-button"
                              aria-label={`${r.cidr} düzenle`}
                              onClick={() => onEdit("prefixes", r)}
                            >
                              <PencilSimple size={18} />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ) : (
                  <tr key={r.id || r.address}>
                    {canWrite && (
                      <td className="ipam-select">
                        {r.id && (
                          <input
                            type="checkbox"
                            aria-label={`${r.address} seç`}
                            checked={selected.includes(r.id)}
                            onChange={(e) =>
                              setSelected(
                                e.target.checked
                                  ? [...selected, r.id]
                                  : selected.filter((id) => id !== r.id),
                              )
                            }
                          />
                        )}
                      </td>
                    )}
                    {visible.map((c) => (
                      <td
                        key={c.key}
                        className={c.key === "mac_address" ? "mono" : undefined}
                      >
                        {renderCell(r, c.key)}
                      </td>
                    ))}
                    <td>
                      <div className="ipam-actions ipam-row-actions">
                        {r.id && (
                          <button
                            className="icon-button"
                            aria-label={`${r.address} networkü izle`}
                            title="Networkü izle"
                            onClick={() => setDetail(r)}
                          >
                            <Waveform size={18} aria-hidden="true" />
                          </button>
                        )}
                        {canWrite && r.status !== "network" && (
                          <button
                            className="icon-button"
                            aria-label={`${r.address} ${r.id ? "düzenle" : "ata"}`}
                            onClick={() =>
                              onEdit(
                                "addresses",
                                r.id
                                  ? { ...r, ...r.managed }
                                  : { ...r, status: "reserved", id: undefined },
                              )
                            }
                          >
                            {r.id ? (
                              <PencilSimple size={18} />
                            ) : (
                              <Plus size={18} />
                            )}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
        {!rows.length && (
          <div className="empty-state">
            <p>{loaded ? "Gösterilecek kayıt yok." : "Kayıtlar yükleniyor…"}</p>
          </div>
        )}
        <div className="ipam-pagination">
          <span>
            {BigInt(total) > 0n
              ? `${BigInt(offset) + 1n}–${BigInt(offset) + BigInt(rows.length)} / ${total}`
              : "0 adres"}
          </span>
          <div className="ipam-actions">
            <button
              className="secondary"
              disabled={offset === "0"}
              onClick={() =>
                setOffset(
                  String(BigInt(offset) > 100n ? BigInt(offset) - 100n : 0n),
                )
              }
            >
              Önceki
            </button>
            <button
              className="secondary"
              disabled={BigInt(offset) + 100n >= BigInt(total)}
              onClick={() => setOffset(String(BigInt(offset) + 100n))}
            >
              Sonraki 100 adres
            </button>
          </div>
        </div>
      </section>
      {filterOpen && (
        <Filters
          wide
          columns={columns}
          rules={rules}
          onClose={() => setFilterOpen(false)}
          onSave={(v) => {
            setRules(v);
            setOffset("0");
          }}
        />
      )}
      {columnOpen && (
        <ColumnPicker
          columns={columns}
          shown={shown}
          onClose={() => setColumnOpen(false)}
          onSave={(v) => {
            setShown(v);
            localStorage.setItem(storageKey, JSON.stringify(v));
          }}
        />
      )}
      {bulkOpen && (
        <IPBulkEditor
          ids={selected}
          refs={refs}
          close={() => setBulkOpen(false)}
          saved={selectionDone}
        />
      )}
      {settings && (
        <PrefixSettings
          prefix={settings}
          refs={refs}
          close={() => setSettings(null)}
          saved={(updated) => {
            setRows((items) =>
              items.map((r) => (r.id === updated.id ? updated : r)),
            );
            setPrefix((current) =>
              current?.id === updated.id ? updated : current,
            );
            onSaved();
          }}
        />
      )}
      {detail && (
        <AddressDetail
          row={detail}
          close={() => setDetail(null)}
          canWrite={canWrite}
        />
      )}
    </div>
  );
}

function IPBulkEditor({
  ids,
  refs,
  close,
  saved,
}: {
  ids: string[];
  refs: Record<string, Row[]>;
  close: () => void;
  saved: () => void;
}) {
  const locationFields = ["institution_id", "site_id", "sub_site_id"];
  const [values, setValues] = useState<Row>({
    institution_id: "",
    site_id: "",
    sub_site_id: "",
  });
  const [enabled, setEnabled] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fields = PAGES.find((p) => p.key === "addresses")!.fields!.filter(
    (f) => f.key !== "address",
  );
  return (
    <Dialog title={`${ids.length} IP · Toplu düzenle`} onClose={close}>
      <form
        className="ipam-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            const changes = Object.fromEntries(
              enabled.map((key) => [
                key,
                values[key] ||
                  (fields.find((f) => f.key === key)?.ref ? null : ""),
              ]),
            );
            if (
              enabled.includes("device_id") &&
              !enabled.includes("interface_id")
            )
              changes.interface_id = null;
            await api("/ipam/addresses/bulk", "POST", {
              ids,
              action: "update",
              changes,
            });
            saved();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <p className="ipam-hint">
          İşaretlenen alanlar tüm seçili kayıtlara uygulanır. IP ve MAC
          adresleri korunur.
        </p>
        <ErrorNote error={error} />
        <div className="ipam-fields">
          {fields.map((f) => (
            <div className="ipam-bulk-field" key={f.key}>
              <label className="ipam-check">
                <input
                  type="checkbox"
                  checked={enabled.includes(f.key)}
                  onChange={(e) => {
                    if (locationFields.includes(f.key)) {
                      setEnabled(
                        e.target.checked
                          ? [...new Set([...enabled, ...locationFields])]
                          : enabled.filter(
                              (key) => !locationFields.includes(key),
                            ),
                      );
                    } else
                      setEnabled(
                        e.target.checked
                          ? [...enabled, f.key]
                          : enabled.filter((k) => k !== f.key),
                      );
                  }}
                />
                {f.label} değiştir
              </label>
              <label className="ipam-field">
                <span>{f.label}</span>
                {f.ref || f.suggestions || f.options ? (
                  <select
                    aria-label={f.label}
                    disabled={
                      !enabled.includes(f.key) ||
                      (f.key === "site_id" && !values.institution_id) ||
                      (f.key === "sub_site_id" && !values.site_id)
                    }
                    value={values[f.key] || ""}
                    onChange={(e) =>
                      setValues(dependentChange(values, f.key, e.target.value))
                    }
                  >
                    <option value="">Temizle / seçilmedi</option>
                    {(f.ref
                      ? resourceChoices(f, refs, values, "addresses").map(
                          (r) => [r.id, r.name || r.cidr || r.address],
                        )
                      : f.suggestions
                        ? (refs[f.suggestions] || []).map((r) => [
                            r.name,
                            r.name,
                          ])
                        : (f.options || []).map((r) =>
                            Array.isArray(r) ? r : [r, stateName(r)],
                          )
                    ).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    aria-label={f.label}
                    disabled={!enabled.includes(f.key)}
                    value={values[f.key] || ""}
                    onChange={(e) =>
                      setValues({ ...values, [f.key]: e.target.value })
                    }
                  />
                )}
              </label>
            </div>
          ))}
        </div>
        <div className="ipam-actions">
          <button type="button" className="secondary" onClick={close}>
            Vazgeç
          </button>
          <button className="primary" disabled={busy || !enabled.length}>
            Değişiklikleri uygula
          </button>
        </div>
      </form>
    </Dialog>
  );
}

const integrationDefaults = {
  name: "",
  kind: "vcenter",
  host: "",
  port: 443,
  username: "",
  password: "",
  enabled: false,
  verify_tls: true,
  prefix_ids: [],
  interval_seconds: 0,
};
export function Integrations({
  user,
  refresh,
  refs,
  onSaved,
}: {
  user: Row;
  refresh: number;
  refs: Record<string, Row[]>;
  onSaved: () => void;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [editing, setEditing] = useState<Row | null>(null);
  const [values, setValues] = useState<Row>(integrationDefaults);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Row | null>(null);
  useEffect(() => {
    let active = true;
    allRows("/integrations")
      .then((data) => {
        if (active) setRows(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [refresh]);
  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    let active = true;
    const t = setTimeout(async () => {
      try {
        const next = await api("/jobs/" + job.id);
        if (active) {
          setJob(next);
          onSaved();
        }
      } catch (e: any) {
        if (active) setError(e.message);
      }
    }, 2000);
    return () => {
      active = false;
      clearTimeout(t);
    };
  }, [job]);
  const edit = (r: Row) => {
    setEditing(r);
    setValues(
      Object.fromEntries(
        Object.keys(integrationDefaults).map((k) => [
          k,
          k === "username" || k === "password"
            ? ""
            : (r[k] ?? (integrationDefaults as Row)[k]),
        ]),
      ),
    );
    setFormError("");
  };
  const set = (key: string, value: any) =>
    setValues((v) => ({ ...v, [key]: value }));
  return (
    <div className="ipam-workspace">
      <ErrorNote error={error} />
      <section className="panel ipam-block-header">
        <div className="ipam-actions">
          <h2>Envanteri IPAM ile birleştirin</h2>
          {user.role === "admin" && (
            <button className="primary" onClick={() => edit({})}>
              <Plus size={18} aria-hidden="true" />
              Entegrasyon ekle
            </button>
          )}
        </div>
        <p>
          VMware vCenter’dan IP, MAC, işletim sistemi, güç durumu ve sanal port;
          Windows DHCP’den sabit IPv4 rezervasyonları ve aktif kiralamalar
          alınır. Yalnızca seçtiğiniz ağ bloklarına kayıt eklenir.
        </p>
      </section>
      {job && (
        <div className="panel ipam-job" role="status">
          <Badge value={job.status} />
          <span>
            {job.status === "succeeded"
              ? `${job.result?.imported || 0} IP gözlemi eşitlendi.`
              : job.error || "Eşitleme görevi çalışıyor…"}
          </span>
          {["queued", "running"].includes(job.status) && (
            <button
              className="secondary"
              onClick={async () => {
                try {
                  setJob(await api("/jobs/" + job.id + "/cancel", "POST"));
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            >
              İptal et
            </button>
          )}
        </div>
      )}
      <section className="panel table-panel">
        <div
          className="table-scroll"
          tabIndex={0}
          role="region"
          aria-label="IPAM kayıt tablosu"
        >
          <table>
            <thead>
              <tr>
                {[
                  "Entegrasyon",
                  "Sunucu",
                  "Yetkili ağlar",
                  "Zamanlama",
                  "Son başarılı eşitleme",
                  "İşlemler",
                ].map((v) => (
                  <th key={v}>{v}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>
                    <b>{r.name}</b>
                    <small className="ipam-sub">
                      {sourceName(r.kind)} · {r.enabled ? "Etkin" : "Kapalı"}
                    </small>
                  </td>
                  <td>
                    {r.host}:{r.port}
                  </td>
                  <td>
                    {r.prefix_ids
                      .map(
                        (id: string) =>
                          refs.prefixes?.find((p) => p.id === id)?.cidr ||
                          "Silinmiş ağ",
                      )
                      .join(", ") || "Seçilmedi"}
                  </td>
                  <td>
                    {r.interval_seconds ? `${r.interval_seconds} sn` : "Manuel"}
                  </td>
                  <td>{date(r.last_success_at)}</td>
                  <td>
                    {user.role === "admin" && (
                      <div className="ipam-actions">
                        <button
                          className="secondary"
                          disabled={!r.enabled || busy}
                          onClick={async () => {
                            setBusy(true);
                            setError("");
                            try {
                              setJob(
                                await api(
                                  "/integrations/" + r.id + "/sync",
                                  "POST",
                                ),
                              );
                            } catch (e: any) {
                              setError(e.message);
                            } finally {
                              setBusy(false);
                            }
                          }}
                        >
                          <ArrowsClockwise size={16} aria-hidden="true" />
                          Şimdi eşitle
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`${r.name} düzenle`}
                          onClick={() => edit(r)}
                        >
                          <PencilSimple size={18} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows.length && (
          <div className="empty-state">
            <p>Henüz entegrasyon tanımlanmamış.</p>
          </div>
        )}
      </section>
      {editing && (
        <Dialog
          title={editing.id ? "Entegrasyonu düzenle" : "Entegrasyon ekle"}
          onClose={() => setEditing(null)}
        >
          <form
            className="ipam-form"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setFormError("");
              try {
                await api(
                  "/integrations" + (editing.id ? "/" + editing.id : ""),
                  editing.id ? "PUT" : "POST",
                  values,
                );
                setEditing(null);
                onSaved();
              } catch (e: any) {
                setFormError(e.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <ErrorNote error={formError} />
            <div className="ipam-fields">
              <Field label="Entegrasyon adı">
                <input
                  required
                  maxLength={120}
                  value={values.name}
                  onChange={(e) => set("name", e.target.value)}
                />
              </Field>
              <Field label="Entegrasyon türü">
                <select
                  value={values.kind}
                  onChange={(e) => {
                    set("kind", e.target.value);
                    set("port", e.target.value === "vcenter" ? 443 : 5986);
                  }}
                >
                  <option value="vcenter">VMware vCenter</option>
                  <option value="windows_dhcp">Microsoft Windows DHCP</option>
                </select>
              </Field>
              <Field label="Sunucu adı veya IP">
                <input
                  required
                  value={values.host}
                  onChange={(e) => set("host", e.target.value)}
                />
              </Field>
              <Field label="HTTPS portu">
                <input
                  type="number"
                  min="1"
                  max="65535"
                  required
                  value={values.port}
                  onChange={(e) => set("port", Number(e.target.value))}
                />
              </Field>
              <Field label="Kullanıcı">
                <input
                  autoComplete="off"
                  required={!editing.id}
                  value={values.username}
                  onChange={(e) => set("username", e.target.value)}
                />
              </Field>
              <Field label="Parola">
                <input
                  type="password"
                  autoComplete="new-password"
                  required={!editing.id}
                  value={values.password}
                  onChange={(e) => set("password", e.target.value)}
                />
              </Field>
              <Field label="Eşitleme aralığı (sn; 0 = manuel)">
                <input
                  type="number"
                  min="0"
                  max="2592000"
                  required
                  value={values.interval_seconds}
                  onChange={(e) =>
                    set("interval_seconds", Number(e.target.value))
                  }
                />
              </Field>
              <label className="ipam-check">
                <input
                  type="checkbox"
                  checked={values.enabled}
                  onChange={(e) => set("enabled", e.target.checked)}
                />
                Entegrasyonu etkinleştir
              </label>
              <label className="ipam-check">
                <input
                  type="checkbox"
                  checked={values.verify_tls}
                  onChange={(e) => set("verify_tls", e.target.checked)}
                />
                TLS sertifikasını doğrula
              </label>
            </div>
            <fieldset className="ipam-prefix-picker">
              <legend>Yetkili ağ blokları</legend>
              {(refs.prefixes || []).map((p) => (
                <label className="ipam-check" key={p.id}>
                  <input
                    type="checkbox"
                    checked={values.prefix_ids.includes(p.id)}
                    onChange={(e) =>
                      set(
                        "prefix_ids",
                        e.target.checked
                          ? [...values.prefix_ids, p.id]
                          : values.prefix_ids.filter(
                              (id: string) => id !== p.id,
                            ),
                      )
                    }
                  />
                  {p.cidr} · {refs.vrfs?.find((v) => v.id === p.vrf_id)?.name}
                </label>
              ))}
              {!refs.prefixes?.length && (
                <p>Önce IP adres yönetiminden bir ağ bloğu ekleyin.</p>
              )}
            </fieldset>
            <p className="ipam-hint">
              {values.kind === "windows_dhcp"
                ? "Windows DHCP sunucusunda WinRM HTTPS (5986), DHCP PowerShell modülü, rezervasyon ve kiralama okuma yetkisi gerekir. Kullanıcı: DOMAIN\\kullanıcı."
                : "vCenter API için envanter ve performans okuma yetkisi gerekir. Konuk IP/OS bilgileri VMware Tools verilerine bağlıdır."}
              {editing.id
                ? " Kayıtlı kullanıcı/parolayı korumak için iki alanı da boş bırakın."
                : ""}{" "}
              Kaydetmek bağlantı testi başlatmaz; “Şimdi eşitle” veya zamanlama
              tetikler.
            </p>
            <div className="ipam-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => setEditing(null)}
              >
                Vazgeç
              </button>
              <button className="primary" disabled={busy}>
                {busy ? "Kaydediliyor…" : "Entegrasyonu kaydet"}
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </div>
  );
}
