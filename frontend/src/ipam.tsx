import { useLiveQuery } from "./data";
import React, { useEffect, useState } from "react";
import {
  Info,
  ArrowLeft,
  Broadcast,
  GearSix,
  Columns,
  Funnel,
  Trash,
  Play,
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
  ADDRESS_PAGE,
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
    dns: "DNS",
    icmp: "Ping",
    gateway: "Gateway ARP/NDP",
    neighbors: "Komşuluklar",
    "gateway+vlan_fdb": "Gateway + switch MAC tablosu",
    "vcenter+vlan_fdb": "VMware + switch MAC tablosu",
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

function VLANSettings({
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
    <Dialog title={`${prefix.cidr} · VLAN ayarları`} onClose={close}>
      <form
        className="ipam-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            const updated = await api(
              `/ipam/vlans/${prefix.id}/settings`,
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
              checked={values.ping_enabled}
              onChange={(e) => set("ping_enabled", e.target.checked)}
            />
            <span>IP durumunu düzenli kontrol et</span>
          </label>
          <label className="ipam-check">
            <input
              type="checkbox"
              checked={values.discovery_enabled}
              onChange={(e) => set("discovery_enabled", e.target.checked)}
            />
            <span>Yeni sunucuları düzenli ekle</span>
          </label>
        </div>
        <p className="ipam-hint">
          Ping kayıtlı IP’leri kontrol eder. Yeni sunucu keşfi VLAN’ın IP
          bloğunu tarar ve DNS’ten isimleri alır. MAC ve bağlantı bilgileri IPAM
          entegrasyonlarıyla tamamlanır. Yanıt alınamaması IP’nin boş veya
          cihazın kapalı olduğunu kanıtlamaz.
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

function AddressDetail({ row, close }: { row: Row; close: () => void }) {
  const query = useLiveQuery<Row>("/ipam/addresses/" + row.id);
  const detail = query.data || row;
  const error = query.error;
  return (
    <Dialog title={`${row.address} · IP ayrıntıları`} onClose={close} wide>
      <div className="ipam-form">
        <ErrorNote error={error} />
        <>
          <dl className="ipam-summary">
            {[
              ["Hostname", detail.hostname, detail.field_sources?.hostname],
              [
                "MAC adresi",
                detail.mac_address,
                detail.field_sources?.mac_address,
              ],
              [
                "Gateway Cihazı",
                <span
                  className={
                    detail.is_gateway ? "ipam-gateway" : "ipam-not-gateway"
                  }
                >
                  {detail.is_gateway ? "Evet" : "Hayır"}
                </span>,
              ],
              ["Bağlı switch", detail.connected_device],
              [
                "Port grubu / Sanal ağ",
                detail.connection_type === "vcenter" ? detail.network : "",
              ],
              ["Bağlı port", detail.connected_port],
              [
                "İşletim sistemi",
                detail.operating_system,
                detail.field_sources?.operating_system,
              ],
              [
                "Bağlantı durumu",
                detail.connection_reason ||
                  (detail.connected_port
                    ? "Güncel kanıtla eşleşti"
                    : "Bağlantı kanıtı yok"),
              ],
              ["Kabinet no", detail.cabinet],
              ["Lokasyon", detail.location],
              ["VM güç durumu", stateName(detail.power_state)],
              ["Ping", stateName(detail.reachability)],
              ["Son gözlem", date(detail.last_observed_at)],
            ].map(([k, v, source]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>
                  {v || "—"}
                  {source && (
                    <small className="ipam-sub">{sourceName(source)}</small>
                  )}
                </dd>
              </div>
            ))}
          </dl>
          {(detail.connections?.length > 0 ||
            detail.gateway_evidence?.length > 0) && (
            <section className="ipam-section">
              <h3>Bağlantı kanıtları</h3>
              {detail.connection_ambiguous && (
                <p className="ipam-hint">
                  Kanıtlar çeliştiği için aşağıdaki adaylardan bir bağlantı
                  seçilmedi.
                </p>
              )}
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="Bağlantı kanıt tablosu"
              >
                <table>
                  <thead>
                    <tr>
                      <th>Cihaz</th>
                      <th>Port / MAC</th>
                      <th>Kaynak</th>
                      <th>Gözlem zamanı</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detail.gateway_evidence || []).map(
                      (e: Row, i: number) => (
                        <tr key={`gateway-${i}`}>
                          <td>{e.device_name}</td>
                          <td>{e.mac_address}</td>
                          <td>{sourceName(e.source)}</td>
                          <td>{date(e.observed_at)}</td>
                        </tr>
                      ),
                    )}
                    {(detail.connections || []).map((e: Row, i: number) => (
                      <tr key={`port-${i}`}>
                        <td>{e.device_name}</td>
                        <td>{e.port}</td>
                        <td>{sourceName(e.source)}</td>
                        <td>{date(e.observed_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <section className="ipam-section">
            <h3>Kaynak gözlemleri</h3>
            {query.loading && (
              <p role="status">Kaynak gözlemleri yükleniyor…</p>
            )}
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
                  {(detail.observations || []).map((o: Row) => (
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
      </div>
    </Dialog>
  );
}

export function IPAMWorkspace({
  initialVLAN,
  page,
  refs,
  refresh,
  user,
  onEdit,
  onSaved,
}: {
  initialVLAN?: Row | null;
  page: string;
  refs: Record<string, Row[]>;
  refresh: number;
  user: Row;
  onEdit: (resource: string, row: Row) => void;
  onSaved: () => void;
}) {
  const [prefix, setVLAN] = useState<Row | null>(null);
  useEffect(() => {
    if (initialVLAN) {
      setVLAN(initialVLAN);
      setOffset("0");
      setQuery("");
      setActiveOnly(false);
    }
  }, [initialVLAN]);
  const [offset, setOffset] = useState("0");
  const [query, setQuery] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<Row | null>(null);
  const [detail, setDetail] = useState<Row | null>(null);
  const [job, setJob] = useState<Row | null>(null);
  const [rules, setRules] = useState<any[]>([]);
  const [filterOpen, setFilterOpen] = useState(false);
  const [columnOpen, setColumnOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [deleteVLANs, setDeleteVLANs] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
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
  const isBlocks = page === "vlans" && !prefix;
  const params = `offset=${offset}&limit=100&q=${encodeURIComponent(query)}&filters=${encodeURIComponent(JSON.stringify(rules))}`;
  const path = prefix
    ? `/ipam/vlans/${prefix.id}/addresses?active_only=${activeOnly}&${params}`
    : `/vlans?limit=100&offset=${offset}&q=${encodeURIComponent(query)}`;
  const listing = useLiveQuery(path, refresh, undefined, query ? 200 : 0);
  const latestScan = useLiveQuery<Row | null>(
    prefix ? `/ipam/vlans/${prefix.id}/scan` : null,
    refresh,
  );
  const rows: Row[] = listing.data?.items || [];
  const total = String(listing.data?.total || 0);
  const loaded = !listing.loading;
  const registeredSearch = !!listing.data?.registered_search;
  const columns: { key: string; label: string }[] = listing.data?.columns || [
    { key: "address", label: "IP adresi" },
    { key: "hostname", label: "Hostname" },
    { key: "mac_address", label: "MAC adresi" },
    { key: "connected_device", label: "Bağlı cihaz" },
    { key: "connected_port", label: "Port" },
    { key: "vlan", label: "VLAN" },
    { key: "operating_system", label: "İşletim sistemi" },
    { key: "cabinet", label: "Kabinet no" },
    { key: "location", label: "Lokasyon" },
    { key: "availability", label: "Durum" },
  ];
  const visible = columns.filter((c) => shown.includes(c.key));
  useEffect(() => {
    if (listing.data?.vlan) setVLAN(listing.data.vlan);
  }, [listing.data]);
  useEffect(() => {
    setError(listing.error);
  }, [listing.error]);
  useEffect(() => {
    setSelected([]);
  }, [prefix?.id, query, rules, activeOnly]);
  useEffect(() => {
    if (
      latestScan.data &&
      (!job || job.kind === "ipam_discover" || job.target_id !== prefix?.id)
    ) {
      setJob(latestScan.data);
    }
  }, [latestScan.data]);
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
      setJob(await api(`/ipam/vlans/${prefix.id}/${action}`, "POST"));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const chooseVLAN = (row: Row | null) => {
    setVLAN(row);
    setJob(null);
    setOffset("0");
    setQuery("");
    setRules([]);
  };
  const jobActive =
    job?.target_id === prefix?.id &&
    ["queued", "running"].includes(job?.status);
  const phaseName = (
    {
      addresses: "IP ve DNS taranıyor",
      network: "Gateway ve switch kaynakları okunuyor",
      dhcp: "DHCP kayıtları eşleştiriliyor",
      vmware: "VMware işletim sistemi ve ağ kartları eşleştiriliyor",
      dns: "Eklenen IP’lerin DNS isimleri tamamlanıyor",
      matching: "Cihaz ve port kanıtları eşleştiriliyor",
      complete: "Kaynak okumaları ve eşleştirme tamamlandı",
    } as Row
  )[job?.result?.scan_phase];
  const selectionDone = () => {
    setSelected([]);
    setBulkOpen(false);
    onSaved();
  };
  const renderCell = (r: Row, key: string) => {
    if (key === "address")
      return r.id ? (
        <>
          <button
            className={`text-button mono${r.is_gateway ? " ipam-gateway" : ""}`}
            onClick={() => setDetail(r)}
            aria-describedby={r.is_gateway ? `gateway-${r.id}` : undefined}
          >
            {r.address}
          </button>
          {r.is_gateway && (
            <small id={`gateway-${r.id}`} className="ipam-sub ipam-gateway">
              Gateway
            </small>
          )}
        </>
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
          {r.connection_groups?.length ? (
            <span className="ipam-connection-lines">
              {r.connection_groups.map((group: Row) => (
                <span key={group.device_id}>
                  {key === "connected_device"
                    ? group.device_name
                    : group.port_label}
                </span>
              ))}
            </span>
          ) : (
            r[key] || "—"
          )}
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
          <div className="ipam-block-overview">
            <div className="ipam-actions ipam-block-title">
              <button
                className="secondary ipam-block-back"
                aria-label="VLAN alanlarına dön"
                title="VLAN alanlarına dön"
                onClick={() => chooseVLAN(null)}
              >
                <ArrowLeft size={17} aria-hidden="true" />
              </button>
              <div className="ipam-block-heading">
                <h2>{prefix.vlan || `VLAN-${prefix.vid} / ${prefix.name}`}</h2>
                <span className="mono">{prefix.cidr}</span>
              </div>
            </div>
            <div
              className={`ipam-block-usage${prefix.threshold_exceeded ? " is-warning" : ""}`}
              aria-label="Ağ bloğu kullanımı"
            >
              <strong>
                {prefix.used || 0} / {prefix.capacity} <span>aktif IP</span>
              </strong>
              <span className="ipam-block-percentage">
                %{prefix.utilization || 0} kullanım
              </span>
            </div>
          </div>
          {canWrite && (
            <div className="ipam-scan-actions">
              <button
                className="secondary"
                disabled={busy || jobActive}
                title="Kayıtlı IP’lere ping gönder"
                onClick={() => trigger("ping")}
              >
                <Waveform size={17} aria-hidden="true" />
                Ping
              </button>
              <button
                className="primary"
                disabled={busy || jobActive}
                aria-busy={busy || jobActive}
                title="VLAN’ı tara ve kaynak bilgilerini eşleştir"
                onClick={() => trigger("discover")}
              >
                <Broadcast size={17} aria-hidden="true" />
                Tara
              </button>
            </div>
          )}
        </section>
      )}
      {prefix && job && job.target_id === prefix.id && (
        <div className="panel ipam-job" role="status">
          <Badge value={job.status} />
          <span>
            {job.progress}/{job.total} adres ·{" "}
            {job.error ||
              phaseName ||
              (job.status === "succeeded"
                ? "İşlem tamamlandı."
                : "Görev merkezinden de izleyebilirsiniz.")}
            {job.result?.matching && (
              <small className="ipam-sub">
                {job.result.matching.hostname} DNS ·{" "}
                {job.result.matching.mac_address} MAC ·{" "}
                {job.result.matching.connected_port} cihaz/port ·{" "}
                {job.result.matching.operating_system} VMware işletim sistemi
              </small>
            )}
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
                  ? "VLAN alanları"
                  : "IP adresleri"}
            </b>
            <span className="count-pill">{loaded ? total : "…"}</span>
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
                <div className="ipam-column-tools">
                  <button
                    className="secondary"
                    onClick={() => setColumnOpen(true)}
                  >
                    <Columns size={17} />
                    Sütunlar
                  </button>
                  {prefix && (
                    <button
                      type="button"
                      className="secondary ipam-active-toggle"
                      aria-label="Yalnızca aktif IP’ler"
                      title="Yalnızca aktif IP’leri göster"
                      aria-pressed={activeOnly}
                      onClick={() => {
                        setActiveOnly((active) => !active);
                        setOffset("0");
                      }}
                    >
                      Aktif IP’ler
                    </button>
                  )}
                </div>
              </>
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
            aria-label={
              isBlocks ? "Seçilen ağ bloğu işlemleri" : "Seçilen IP işlemleri"
            }
          >
            <strong>
              {selected.length} {isBlocks ? "ağ bloğu" : "IP"} seçildi
            </strong>
            {!isBlocks && (
              <button className="secondary" onClick={() => setBulkOpen(true)}>
                <PencilSimple size={17} />
                Düzenle
              </button>
            )}
            {user.role === "admin" && (
              <button
                className="secondary danger"
                disabled={busy}
                onClick={async () => {
                  if (isBlocks) {
                    setDeleteVLANs([...selected]);
                    return;
                  }
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
                {canWrite && (!isBlocks || user.role === "admin") && (
                  <th className="ipam-select">
                    <input
                      type="checkbox"
                      aria-label={
                        isBlocks
                          ? "Sayfadaki VLAN’ları seç"
                          : "Sayfadaki IP kayıtlarını seç"
                      }
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
                    {user.role === "admin" && (
                      <td className="ipam-select">
                        <input
                          type="checkbox"
                          aria-label={`${r.cidr} seç`}
                          checked={selected.includes(r.id)}
                          onChange={(e) =>
                            setSelected(
                              e.target.checked
                                ? [...selected, r.id]
                                : selected.filter((id) => id !== r.id),
                            )
                          }
                        />
                      </td>
                    )}
                    <td>
                      <button
                        className="text-button mono"
                        onClick={() =>
                          r.cidr ? chooseVLAN(r) : onEdit("vlans", r)
                        }
                      >
                        {r.cidr || "IP bloğu ekle"}
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
                              onClick={() => onEdit("vlans", r)}
                            >
                              <PencilSimple size={18} />
                            </button>
                            {user.role === "admin" && (
                              <button
                                className="icon-button danger"
                                aria-label={`${r.cidr} sil`}
                                title="VLAN’ı sil"
                                onClick={() => setDeleteVLANs([r.id])}
                              >
                                <Trash size={18} aria-hidden="true" />
                              </button>
                            )}
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
                            aria-label={`${r.address} IP ayrıntıları`}
                            title="IP ayrıntıları"
                            onClick={() => setDetail(r)}
                          >
                            <Info size={18} aria-hidden="true" />
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
            {!loaded
              ? "Yükleniyor…"
              : BigInt(total) > 0n
                ? `${BigInt(offset) + 1n}–${BigInt(offset) + BigInt(rows.length)} / ${total}`
                : isBlocks
                  ? "0 ağ bloğu"
                  : "0 adres"}
          </span>
          <div className="ipam-actions">
            <button
              className="secondary"
              disabled={!loaded || offset === "0"}
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
              disabled={!loaded || BigInt(offset) + 100n >= BigInt(total)}
              onClick={() => setOffset(String(BigInt(offset) + 100n))}
            >
              {isBlocks ? "Sonraki" : "Sonraki 100 adres"}
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
      {!!deleteVLANs.length && (
        <VLANDeleteDialog
          ids={deleteVLANs}
          close={() => setDeleteVLANs([])}
          saved={() => {
            setDeleteVLANs([]);
            setOffset("0");
            selectionDone();
          }}
        />
      )}
      {settings && (
        <VLANSettings
          prefix={settings}
          refs={refs}
          close={() => setSettings(null)}
          saved={(updated) => {
            setVLAN((current) =>
              current?.id === updated.id ? updated : current,
            );
            onSaved();
          }}
        />
      )}
      {detail && <AddressDetail row={detail} close={() => setDetail(null)} />}
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
  const fields = ADDRESS_PAGE.fields!.filter((f) => f.key !== "address");
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
                fields.find((f) => f.key === key)?.type === "checkbox"
                  ? !!values[key]
                  : values[key] ||
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
                ) : f.type === "checkbox" ? (
                  <input
                    type="checkbox"
                    aria-label={f.label}
                    disabled={!enabled.includes(f.key)}
                    checked={!!values[f.key]}
                    onChange={(e) =>
                      setValues({ ...values, [f.key]: e.target.checked })
                    }
                  />
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
  const listing = useLiveQuery<Row[]>("integrations:all", refresh, () =>
    allRows("/integrations"),
  );
  const rows = listing.data || [];
  const [editing, setEditing] = useState<Row | null>(null);
  const [values, setValues] = useState<Row>(integrationDefaults);
  const [changeCredentials, setChangeCredentials] = useState(false);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Row | null>(null);
  useEffect(() => {
    setError(listing.error);
  }, [listing.error]);
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
    setChangeCredentials(false);
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
  const targetChanged = Boolean(
    editing?.id &&
    (values.host.trim().toLowerCase() !== editing.host.toLowerCase() ||
      Number(values.port) !== Number(editing.port) ||
      values.kind !== editing.kind),
  );
  const credentialsRequired =
    !editing?.id || targetChanged || changeCredentials;
  return (
    <div className="ipam-workspace">
      <ErrorNote error={error} />
      <section className="panel ipam-block-header">
        <div className="ipam-actions">
          <h2>IPAM veri kaynakları</h2>
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
          alınır. Eklenen tüm VLAN’lar DHCP ve VMware entegrasyonlarıyla
          otomatik çalışır.
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
                  {
                    ...values,
                    username: credentialsRequired ? values.username : "",
                    password: credentialsRequired ? values.password : "",
                  },
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
            {editing.id && (
              <>
                <p
                  className="ipam-hint"
                  id="integration-credentials-hint"
                  role="status"
                >
                  {targetChanged
                    ? "Sunucu, port veya tür değiştiği için kullanıcı ve parolayı yeniden girin."
                    : changeCredentials
                      ? "Kayıtlı bilgileri değiştirmek için yeni kullanıcı ve parolayı birlikte girin."
                      : "Kayıtlı kullanıcı ve parola korunacak. Yeniden girmeniz gerekmiyor."}
                </p>
                <label className="ipam-check">
                  <input
                    type="checkbox"
                    checked={credentialsRequired}
                    disabled={targetChanged}
                    aria-describedby="integration-credentials-hint"
                    onChange={(e) => {
                      setChangeCredentials(e.target.checked);
                      if (!e.target.checked) {
                        setValues((v) => ({
                          ...v,
                          username: "",
                          password: "",
                        }));
                      }
                    }}
                  />
                  Kullanıcı/parolayı değiştir
                </label>
              </>
            )}
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
              <Field label="Bağlantı portu">
                <input
                  type="number"
                  min="1"
                  max="65535"
                  required
                  value={values.port}
                  onChange={(e) => set("port", Number(e.target.value))}
                />
              </Field>
              {credentialsRequired && (
                <>
                  <Field label="Kullanıcı">
                    <input
                      name="integration_username"
                      autoComplete="off"
                      spellCheck={false}
                      required
                      value={values.username}
                      onChange={(e) => set("username", e.target.value)}
                    />
                  </Field>
                  <Field label="Parola">
                    <input
                      type="password"
                      name="integration_password"
                      autoComplete="new-password"
                      required
                      value={values.password}
                      onChange={(e) => set("password", e.target.value)}
                    />
                  </Field>
                </>
              )}
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
            <p className="ipam-hint">
              {values.kind === "windows_dhcp"
                ? "Windows DHCP sunucusunda WinRM HTTPS (5986), DHCP PowerShell modülü, rezervasyon ve kiralama okuma yetkisi gerekir. Kullanıcı: DOMAIN\\kullanıcı."
                : "Konuk IP/OS bilgileri VMware Tools verilerine bağlıdır."}{" "}
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

function VLANDeleteDialog({
  ids,
  close,
  saved,
}: {
  ids: string[];
  close: () => void;
  saved: () => void;
}) {
  const [preview, setPreview] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    api("/ipam/vlans/delete-preview", "POST", { ids })
      .then((result) => {
        if (active) setPreview(result);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [ids]);
  return (
    <Dialog
      title={ids.length === 1 ? "VLAN’ı sil" : "Seçilen VLAN’ları sil"}
      onClose={() => {
        if (!busy) close();
      }}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (!preview || busy) return;
          setBusy(true);
          setError("");
          try {
            await api("/ipam/vlans/bulk-delete", "POST", {
              ids,
              confirmation: preview.confirmation,
            });
            saved();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <ErrorNote error={error} />
        {!preview && !error && (
          <p role="status">Silinecek kayıtlar hesaplanıyor…</p>
        )}
        {preview && (
          <div className="prefix-delete-summary">
            <p>
              <strong>{preview.vlans.length} VLAN</strong> ve bu VLAN’lara bağlı{" "}
              <strong>{preview.address_count} IP kaydı</strong> silinecek.
            </p>
            <ul aria-label="Silinecek VLAN’lar">
              {preview.vlans.map((p: Row) => (
                <li key={p.id} className="mono">
                  {p.cidr}
                </li>
              ))}
            </ul>
            <p>
              İlgili işler otomatik durdurulur. IP gözlemleri de silinir.
              Envanter ve kabinet kayıtları korunur.
            </p>
            <p>Bu işlem geri alınamaz.</p>
          </div>
        )}
        <div className="dialog-footer">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={close}
          >
            Vazgeç
          </button>
          <button
            type="submit"
            className="secondary prefix-delete-confirm"
            disabled={!preview || busy}
          >
            <Trash size={18} aria-hidden="true" />
            {busy ? "Siliniyor…" : "Sil"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
