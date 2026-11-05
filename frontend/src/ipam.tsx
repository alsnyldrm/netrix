import { hasAdminAccess, canOperate } from "./permissions";
import { useLiveQuery } from "./data";
import React, { useEffect, useRef, useState } from "react";
import {
  Info,
  ArrowLeft,
  Broadcast,
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
    manual: "Manuel",
    vcenter: "VMware vCenter",
    windows_dhcp: "Windows DHCP",
    dns: "DNS",
    icmp: "Ping",
    switch_mac_cache: "Switch MAC tablosu",
    gateway: "Gateway ARP/NDP",
    neighbors: "Komşuluklar",
    nic_teaming: "NIC-Teaming · SQL komşulukları",
    "gateway+vlan_fdb": "Gateway + switch MAC tablosu",
    "vcenter+vlan_fdb": "VMware + switch MAC tablosu",
    "vcenter_host+neighbors": "VMware host + komşuluk",
    "vcenter_host+lldp": "VMware host + LLDP",
    "vcenter_host+cdp": "VMware host + CDP",
    ipam_ssh_neighbors: "Komşuluklar · SSH LLDP/CDP",
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

// A selected connection remains visibly manual; it never becomes protocol evidence.
const manualConnection = (row: Row) =>
  !row.connected_device && !row.connection_ambiguous
    ? row.manual_connection
    : null;

export function useIPAMUpdates(vlanId?: string) {
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const update = () => {
      if (!document.hidden) setRevision((value) => value + 1);
    };
    const received = (event: Event) => {
      if (
        !vlanId ||
        (event as CustomEvent<string>).detail === vlanId ||
        (event as CustomEvent<string>).detail === "*"
      )
        update();
    };
    window.addEventListener("netrix:ipam-update", received);
    document.addEventListener("visibilitychange", update);
    const timer = setInterval(update, 10000);
    return () => {
      clearInterval(timer);
      window.removeEventListener("netrix:ipam-update", received);
      document.removeEventListener("visibilitychange", update);
    };
  }, [vlanId]);
  return revision;
}

export function AddressDetail({
  row,
  close,
  user,
}: {
  row: Row;
  close: () => void;
  user: Row;
}) {
  const [scanRevision, setScanRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [scanError, setScanError] = useState("");
  const ipamRevision = useIPAMUpdates(row.vlan_id);
  const query = useLiveQuery<Row>(
    "/ipam/addresses/" + row.id,
    ipamRevision + scanRevision,
  );
  const scan = useLiveQuery<Row | null>(
    "/ipam/addresses/" + row.id + "/scan",
    ipamRevision + scanRevision,
  );
  const job = scan.data;
  const running = job && ["queued", "running"].includes(job.status);
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => setScanRevision((n) => n + 1), 2000);
    return () => clearTimeout(timer);
  }, [running, scanRevision]);
  const detail = query.data || row;
  const currentJob =
    job &&
    (running ||
      !detail.scan_result?.completed_at ||
      !job.finished_at ||
      new Date(job.finished_at).getTime() >=
        new Date(detail.scan_result.completed_at).getTime());
  const error = scanError || query.error || scan.error;
  const manual = manualConnection(detail);
  const location = detail.rack_location || detail.manual_location;
  return (
    <Dialog title={`${row.address} · IP ayrıntıları`} onClose={close} wide>
      <div className="ipam-form">
        <ErrorNote error={error} />
        <div className="ipam-address-scan">
          <div role="status">
            {currentJob ? (
              <>
                <Badge value={job.status} />
                <span>
                  {(job.status === "partial"
                    ? "Tarama tamamlandı; sonuçta sorun var."
                    : "") ||
                    job.error ||
                    (job.status === "cancelled"
                      ? "IP taraması iptal edildi"
                      : job.status === "failed"
                        ? "IP taraması tamamlanamadı"
                        : "") ||
                    (
                      {
                        addresses: "IP ve DNS kontrol ediliyor",
                        gateway:
                          "Gateway üzerinde bu IP’nin MAC’i sorgulanıyor",
                        backbone: "Bu MAC’in switch ve port yolu doğrulanıyor",
                        dns: "Bu IP’nin DNS adı sorgulanıyor",
                        network: "Ağ kanıtları okunuyor",
                        dhcp: "DHCP bilgisi kontrol ediliyor",
                        vmware: "VMware bilgisi kontrol ediliyor",
                        complete: "IP bilgileri güncellendi",
                      } as Row
                    )[job.result?.scan_phase] ||
                    "IP taraması kuyruğa alındı"}
                </span>
              </>
            ) : (
              <span>Yalnız bu IP’nin bilgileri güncellenir.</span>
            )}
          </div>
          {canOperate(user) && (
            <div className="ipam-address-scan-buttons">
              {running && (
                <button
                  className="secondary"
                  disabled={busy || job.cancel_requested}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      await api("/jobs/" + job.id + "/cancel", "POST");
                      setScanRevision((n) => n + 1);
                    } catch (e: any) {
                      setScanError(e.message);
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  İptal et
                </button>
              )}
              <button
                className="secondary"
                aria-label={`${row.address} için tara`}
                disabled={busy || !!running || scan.loading}
                aria-busy={busy || !!running}
                onClick={async () => {
                  setBusy(true);
                  setScanError("");
                  try {
                    await api("/ipam/addresses/" + row.id + "/scan", "POST");
                    setScanRevision((n) => n + 1);
                  } catch (e: any) {
                    setScanError(e.message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Broadcast size={16} aria-hidden="true" />
                {busy || running ? "Taranıyor…" : "Tara"}
              </button>
            </div>
          )}
        </div>
        <>
          {detail.scan_result && (
            <section
              className="ipam-section ipam-result-panel"
              aria-labelledby="ip-scan-result-title"
            >
              <h3 id="ip-scan-result-title">Sonuç</h3>
              {detail.cached_import && (
                <p className="ipam-hint">
                  Mevcut kaynak gözlemlerinden işlendi; yeni ağ sorgusu
                  yapılmadı.
                </p>
              )}
              <p
                className={
                  detail.scan_result.status === "success"
                    ? "ipam-gateway"
                    : "ipam-not-gateway"
                }
              >
                {detail.scan_result.status === "success"
                  ? "Başarılı"
                  : "Sorunlu"}
                <span className="ipam-result-time">
                  {date(detail.scan_result.completed_at)}
                </span>
              </p>
              {detail.scan_result.issues?.length > 0 && (
                <ul className="ipam-result-issues">
                  {detail.scan_result.issues.map((issue: Row, i: number) => (
                    <li key={i}>{issue.message}</li>
                  ))}
                </ul>
              )}
              {detail.scan_result.retained && (
                <p className="ipam-hint">
                  Eksik veya hatalı kaynak yanıtı nedeniyle önceki doğrulanmış
                  alanlar korunuyor. Son başarılı tarama:{" "}
                  {date(detail.scan_result.last_success_at) || "—"}
                </p>
              )}
              <details className="ipam-result-steps">
                <summary>İşlem adımları</summary>
                <div
                  className="table-scroll"
                  role="region"
                  aria-label="IP tarama adımları"
                  tabIndex={0}
                >
                  <table>
                    <thead>
                      <tr>
                        <th>Kaynak</th>
                        <th>Sonuç</th>
                        <th>Zaman</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.scan_result.steps?.map((step: Row, i: number) => (
                        <tr key={i}>
                          <td>
                            {(
                              {
                                gateway: "Gateway",
                                vmware: "VMware",
                                backbone: "Backbone / Switch",
                                switch: "Switch",
                                dns: "DNS",
                                dhcp: "DHCP",
                              } as Row
                            )[step.source] || step.source}
                            {step.device && (
                              <small className="ipam-sub">{step.device}</small>
                            )}
                          </td>
                          <td>
                            {step.status === "skipped_nic_teaming"
                              ? "NIC-Teaming; sorgulanmadı"
                              : step.status === "skipped_identity"
                                ? "Gateway MAC’i yok; sorgulanmadı"
                                : step.status === "skipped_vm"
                                  ? "VMware kaydı bulundu; sorgulanmadı"
                                  : step.status === "error"
                                    ? "Okunamadı"
                                    : "Tamamlandı"}
                          </td>
                          <td>{step.at ? date(step.at) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </section>
          )}
          <dl className="ipam-summary">
            {[
              ["Hostname", detail.hostname, detail.field_sources?.hostname],
              ["NIC-Teaming", detail.nic_teaming ? "Etkin" : "Kapalı"],
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
              [
                "Bağlı switch",
                detail.connected_device || manual?.device_name,
                manual ? "manual" : "",
              ],
              [
                "Port grubu / Sanal ağ",
                detail.connection_type === "vcenter" ? detail.network : "",
              ],
              [
                "Bağlı port",
                detail.connected_port || manual?.port,
                manual?.port ? "manual" : "",
              ],
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
              ["Lokasyon", detail.location],
              [
                detail.vmware_host ? "Host güç durumu" : "VM güç durumu",
                stateName(detail.power_state),
              ],
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
                  {k === "MAC adresi" &&
                    source === "manual" &&
                    detail.automatic_mac_address &&
                    detail.automatic_mac_address !== detail.mac_address && (
                      <small className="ipam-sub">
                        Otomatik MAC: {detail.automatic_mac_address}
                      </small>
                    )}
                </dd>
              </div>
            ))}
          </dl>
          {detail.physical_nics?.length > 0 && (
            <section className="ipam-section" aria-labelledby="host-nics-title">
              <h3 id="host-nics-title">Fiziksel ağ kartları</h3>
              <p className="ipam-hint">
                {detail.vmware_host?.hostname || detail.hostname} ·{" "}
                {detail.vmware_host ? "VMware host" : "Güncel komşuluk"}
              </p>
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="Fiziksel ağ kartları tablosu"
              >
                <table>
                  <thead>
                    <tr>
                      {[
                        "Ağ kartı",
                        "MAC adresi",
                        "Bağlantı",
                        "Switch",
                        "Port",
                      ].map((label) => (
                        <th key={label} scope="col">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {detail.physical_nics.map((nic: Row) => {
                      const connections = detail.connection_ambiguous
                        ? []
                        : (detail.connections || []).filter(
                            (c: Row) => c.nic === nic.device,
                          );
                      return (
                        <tr key={nic.device}>
                          <td>{nic.device}</td>
                          <td>{nic.mac_address || "—"}</td>
                          <td>
                            {nic.link_up ? "Bağlı" : "Bağlı değil"}
                            {nic.carries_ip === false && (
                              <small className="ipam-sub">Diğer ağ</small>
                            )}
                          </td>
                          <td>
                            {connections.length
                              ? connections
                                  .map((c: Row) => c.device_name)
                                  .join(" / ")
                              : "—"}
                          </td>
                          <td>
                            {connections.length
                              ? connections.map((c: Row) => c.port).join(" / ")
                              : "—"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>
          )}
          <section className="ipam-section ipam-rack-location">
            <h3>Kabinet yerleşimi</h3>
            {detail.cabinet === "Sanal" ? (
              <p className="ipam-hint">Sanal</p>
            ) : location ? (
              <>
                {!detail.rack_location && (
                  <p className="ipam-hint">
                    Manuel konum bilgisi · U yerleşimi tanımlanmamış.
                  </p>
                )}
                <div
                  className="table-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label="Kabinet yerleşim tablosu"
                >
                  <table aria-label="Kabinet yerleşimi">
                    <thead>
                      <tr>
                        {[
                          "Lokasyon",
                          "Kat",
                          "Bölüm",
                          "Oda ismi",
                          "Kabin",
                          "U no",
                        ].map((label) => (
                          <th key={label} scope="col">
                            {label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        {[
                          location.site_name,
                          location.floor_number,
                          location.department_name,
                          location.room_name,
                          location.cabinet_number,
                          location.start_unit ? `${location.start_unit}U` : "",
                        ].map((value, index) => (
                          <td key={index}>{value || "—"}</td>
                        ))}
                      </tr>
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="ipam-hint">
                {detail.cabinet
                  ? `Kabinet notu: ${detail.cabinet}`
                  : "Kabinet yerleşimi tanımlanmamış."}
              </p>
            )}
          </section>
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
  onVLANChange,
  initialVLAN,
  page,
  refs,
  refresh,
  user,
  onEdit,
  onSaved,
}: {
  initialVLAN?: Row | null;
  onVLANChange: (vlan: Row | null) => void;
  page: string;
  refs: Record<string, Row[]>;
  refresh: number;
  user: Row;
  onEdit: (resource: string, row: Row) => void;
  onSaved: () => void;
}) {
  const [prefix, setVLAN] = useState<Row | null>(null);
  useEffect(() => {
    onVLANChange(prefix);
  }, [prefix, onVLANChange]);
  useEffect(() => {
    if (initialVLAN) {
      setVLAN(initialVLAN);
      setOffset("0");
      setQuery("");
      setActiveOnly(true);
    }
  }, [initialVLAN]);
  const [offset, setOffset] = useState("0");
  const [query, setQuery] = useState("");
  const [activeOnly, setActiveOnly] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<Row | null>(null);
  const [job, setJob] = useState<Row | null>(null);
  const [scanRevision, setScanRevision] = useState(0);
  const [rules, setRules] = useState<any[]>([]);
  const [filterOpen, setFilterOpen] = useState(false);
  const [columnOpen, setColumnOpen] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [deleteVLANs, setDeleteVLANs] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const legacyStorageKey = `netrix.ipam.columns.${user.id}`;
  const storageKey = `${legacyStorageKey}.v2`;
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
      if (Array.isArray(value) && value.length) return value;
      const legacy = JSON.parse(
        localStorage.getItem(legacyStorageKey) || "null",
      );
      // Upgrade old layouts once so saved metadata is visible; subsequent choices persist.
      return Array.isArray(legacy) && legacy.length
        ? [
            ...new Set([
              ...legacy,
              "hostname",
              "operating_system",
              "cabinet",
              "location",
            ]),
          ]
        : defaults;
    } catch {
      return defaults;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(shown));
    } catch {
      // Storage may be disabled; keep the current session's column choices.
    }
  }, [shown, storageKey]);
  useEffect(() => {
    const revealSaved = (event: Event) => {
      const saved = (event as CustomEvent<Row>).detail;
      if (saved.created_in_vlan) {
        setActiveOnly(false);
        setOffset("0");
        setQuery(saved.address);
        setRules([]);
      }
      const fields = [
        saved.hostname && "hostname",
        saved.mac_address && "mac_address",
        saved.operating_system && "operating_system",
        saved.cabinet && "cabinet",
        (saved.site_id || saved.sub_site_id || saved.location) && "location",
        saved.device_id && "connected_device",
        saved.interface_id && "connected_port",
      ].filter(Boolean) as string[];
      setShown((current) => [...new Set([...current, ...fields])]);
    };
    window.addEventListener("netrix:ipam-saved", revealSaved);
    return () => window.removeEventListener("netrix:ipam-saved", revealSaved);
  }, []);
  const canWrite = user.role !== "viewer";
  const isBlocks = page === "vlans" && !prefix;
  const params = `offset=${offset}&limit=100&q=${encodeURIComponent(query)}&filters=${encodeURIComponent(JSON.stringify(rules))}`;
  const path = prefix
    ? `/ipam/vlans/${prefix.id}/addresses?active_only=${activeOnly}&${params}`
    : `/vlans?limit=100&offset=${offset}&q=${encodeURIComponent(query)}`;
  const ipamRevision = useIPAMUpdates(prefix?.id);
  const listing = useLiveQuery(
    path,
    refresh + ipamRevision + scanRevision,
    undefined,
    query ? 200 : 0,
  );
  const latestScan = useLiveQuery<Row | null>(
    prefix ? `/ipam/vlans/${prefix.id}/scan` : null,
    refresh + ipamRevision,
  );
  const rows: Row[] = listing.data?.items || [];
  const total = String(listing.data?.total || 0);
  const loaded = !listing.loading;
  const registeredSearch = !!listing.data?.registered_search;
  const columns: { key: string; label: string }[] = listing.data?.columns || [
    { key: "scan_status", label: "Sonuç" },
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
  const visible = columns.filter(
    (c) => c.key === "scan_status" || shown.includes(c.key),
  );
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
          setScanRevision((value) => value + 1);
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
  const chooseVLAN = (row: Row | null) => {
    setVLAN(row);
    setActiveOnly(true);
    setJob(null);
    setOffset("0");
    setQuery("");
    setRules([]);
  };
  const jobActive =
    job?.target_id === prefix?.id &&
    ["queued", "running"].includes(job?.status);
  const startScan = async (action: "discover" | "ping") => {
    if (!prefix || busy || jobActive) return;
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
  const scanOrigin =
    (
      {
        schedule: "Zamanlanmış tarama",
        group_manual: "Manuel grup taraması",
        manual: job?.kind === "ipam_ping" ? "Manuel ping" : "Manuel tarama",
        vlan_create: "Yeni VLAN’ın ilk taraması",
        ping_timer: "Periyodik ping",
      } as Row
    )[job?.result?.ipam_origin] || "Tarama kaynağı bilinmiyor";
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
    if (key === "scan_status")
      return r.scan_result ? (
        <span
          className={
            r.scan_result.status === "success"
              ? "ipam-gateway"
              : "ipam-not-gateway"
          }
        >
          {r.scan_result.status === "success" ? "Başarılı" : "Sorunlu"}
        </span>
      ) : (
        <span className="muted">—</span>
      );
    if (key === "status") return stateName(r.status);
    if (key === "sources") return r.sources?.map(sourceName).join(", ") || "—";
    if (["connected_device", "connected_port"].includes(key)) {
      const manual = manualConnection(r);
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
            r[key] ||
            (manual && (
              <>
                {key === "connected_device"
                  ? manual.device_name
                  : manual.port || "—"}
                {(key === "connected_device" || manual.port) && (
                  <small className="ipam-sub">Manuel</small>
                )}
              </>
            )) ||
            "—"
          )}
          {key === "connected_device" && r.connection_ambiguous && (
            <small className="ipam-sub">Bağlantı doğrulanamadı</small>
          )}
        </>
      );
    }
    if (
      key === "cabinet" &&
      r.manual_location &&
      !r.rack_location &&
      r.cabinet !== "Sanal"
    ) {
      const place = r.manual_location;
      return (
        <>
          {r.cabinet || "—"}
          <small className="ipam-sub">
            {[
              place.site_name,
              place.floor_number,
              place.department_name,
              place.room_name,
            ]
              .filter(Boolean)
              .join(" / ")}
          </small>
        </>
      );
    }
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
          <div className="ipam-scan-controls">
            {canWrite && (
              <div
                className="ipam-scan-actions"
                aria-label="VLAN tarama işlemleri"
                aria-busy={busy}
              >
                <button
                  className="secondary"
                  disabled={busy || jobActive}
                  title="Kayıtlı IP adreslerine yalnız ping gönder"
                  onClick={() => startScan("ping")}
                >
                  <Waveform size={17} aria-hidden="true" />
                  Ping
                </button>
                <button
                  className="primary"
                  disabled={busy || jobActive}
                  title="VLAN’ı tara ve kaynak bilgilerini güncelle"
                  onClick={() => startScan("discover")}
                >
                  <Broadcast size={17} aria-hidden="true" />
                  Tara
                </button>
              </div>
            )}
            <div className="ipam-schedule-note">
              <span>Tam tarama: zamanlama</span>
              <small>
                {prefix.ping_enabled
                  ? `Ping: ${prefix.ping_interval || 30} sn`
                  : "Periyodik ping kapalı"}
              </small>
            </div>
          </div>
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
            <small className="ipam-sub ipam-job-origin">
              {scanOrigin} · Kuyruğa alınma:{" "}
              <time dateTime={job.created_at}>{date(job.created_at)}</time>
            </small>
            {job.result?.matching && (
              <small className="ipam-sub">
                {job.result.matching.hostname} hostname ·{" "}
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
            {hasAdminAccess(user) && (
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
                {canWrite && (!isBlocks || hasAdminAccess(user)) && (
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
                    {hasAdminAccess(user) && (
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
                              aria-label={`${r.cidr} düzenle`}
                              disabled={busy}
                              aria-busy={busy}
                              onClick={async () => {
                                setBusy(true);
                                setError("");
                                try {
                                  // The list may still be refreshing after a save.
                                  // Read the current SQL record before opening its editor.
                                  const current = await api(`/vlans/${r.id}`);
                                  onEdit("vlans", { ...r, ...current });
                                } catch (e: any) {
                                  setError(e.message);
                                } finally {
                                  setBusy(false);
                                }
                              }}
                            >
                              <PencilSimple size={18} />
                            </button>
                            {hasAdminAccess(user) && (
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
          columns={columns.filter((c) => c.key !== "scan_status")}
          shown={shown}
          onClose={() => setColumnOpen(false)}
          onSave={(v) => {
            setShown(v);
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
      {detail && (
        <AddressDetail row={detail} close={() => setDetail(null)} user={user} />
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
  const fields = ADDRESS_PAGE.fields!.filter(
    (f) => !["address", "mac_address"].includes(f.key),
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
  const [connectionTest, setConnectionTest] = useState<Row | null>(null);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState("");
  const testRequest = useRef(0);
  useEffect(() => {
    if (
      !editing ||
      !connectionTest ||
      !["queued", "running"].includes(connectionTest.status)
    )
      return;
    let active = true;
    const timer = setTimeout(async () => {
      try {
        const next = await api("/jobs/" + connectionTest.id);
        if (active) {
          setConnectionTest(next);
          if (!["queued", "running"].includes(next.status)) setTesting(false);
        }
      } catch (e: any) {
        if (active) {
          setTestError(e.message);
          setTesting(false);
        }
      }
    }, 1000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [connectionTest, editing]);
  const closeEditor = () => {
    testRequest.current++;
    if (connectionTest && ["queued", "running"].includes(connectionTest.status))
      void api("/jobs/" + connectionTest.id + "/cancel", "POST").catch(
        () => {},
      );
    setEditing(null);
    setConnectionTest(null);
    setTesting(false);
    setTestError("");
  };
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
    setConnectionTest(null);
    setTestError("");
    setTesting(false);
    setEditing(r);
    setChangeCredentials(false);
    setValues(
      Object.fromEntries(
        Object.keys(integrationDefaults).map((k) => [
          k,
          k === "username" || k === "password"
            ? ""
            : k === "interval_seconds"
              ? 0
              : (r[k] ?? (integrationDefaults as Row)[k]),
        ]),
      ),
    );
    setFormError("");
  };
  const set = (key: string, value: any) => {
    setConnectionTest(null);
    setTestError("");
    setValues((v) => ({ ...v, [key]: value }));
  };
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
          {hasAdminAccess(user) && (
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
                  <td>Zamanlanmış VLAN taraması</td>
                  <td>{date(r.last_success_at)}</td>
                  <td>
                    {hasAdminAccess(user) && (
                      <div className="ipam-actions">
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
          onClose={closeEditor}
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
            <fieldset
              className="integration-test-fields"
              disabled={busy || testing}
            >
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
                        setConnectionTest(null);
                        setTestError("");
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
                <p className="ipam-hint">
                  Bu kaynak yalnız Ayarlar → Tarama gruplarının zamanlamasıyla
                  okunur.
                </p>
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
                Bağlantıyı test et, bu formdaki ayarları kaydetmeden kontrol
                eder. Kaynak verileri VLAN taramalarıyla güncellenir.
              </p>
            </fieldset>
            {(connectionTest || testError || testing) && (
              <div
                className="integration-test-result"
                role={
                  testError || connectionTest?.status === "failed"
                    ? "alert"
                    : "status"
                }
                data-state={testError ? "failed" : connectionTest?.status}
              >
                <strong>
                  {testing
                    ? "Bağlantı test ediliyor…"
                    : connectionTest?.status === "succeeded"
                      ? "Bağlantı başarılı"
                      : connectionTest?.status === "cancelled"
                        ? "Test iptal edildi"
                        : "Bağlantı testi tamamlanamadı"}
                </strong>
                <p>
                  {testError ||
                    connectionTest?.result?.message ||
                    connectionTest?.error ||
                    "Sunucu bağlantısı ve okuma erişimi kontrol ediliyor."}
                </p>
                {testing && connectionTest?.id && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={connectionTest.cancel_requested}
                    onClick={async () => {
                      try {
                        setConnectionTest(
                          await api(
                            "/jobs/" + connectionTest.id + "/cancel",
                            "POST",
                          ),
                        );
                      } catch (e: any) {
                        setTestError(e.message);
                      }
                    }}
                  >
                    {connectionTest.cancel_requested
                      ? "İptal ediliyor…"
                      : "Testi iptal et"}
                  </button>
                )}
              </div>
            )}
            <div className="ipam-actions integration-form-actions">
              <button type="button" className="secondary" onClick={closeEditor}>
                Vazgeç
              </button>
              <button
                type="button"
                className="secondary integration-test-button"
                disabled={busy || testing}
                onClick={async (e) => {
                  if (!e.currentTarget.form?.reportValidity()) return;
                  const request = ++testRequest.current;
                  setTesting(true);
                  setTestError("");
                  setConnectionTest(null);
                  setFormError("");
                  try {
                    const next = await api(
                      "/integrations" +
                        (editing.id ? "/" + editing.id : "") +
                        "/connection-tests",
                      "POST",
                      {
                        ...values,
                        username: credentialsRequired ? values.username : "",
                        password: credentialsRequired ? values.password : "",
                      },
                    );
                    if (request !== testRequest.current) {
                      void api("/jobs/" + next.id + "/cancel", "POST").catch(
                        () => {},
                      );
                      return;
                    }
                    setConnectionTest(next);
                  } catch (e: any) {
                    if (request !== testRequest.current) return;
                    setTestError(e.message);
                    setTesting(false);
                  }
                }}
              >
                <Broadcast size={18} aria-hidden="true" />
                {testing ? "Test ediliyor…" : "Bağlantıyı test et"}
              </button>
              <button className="primary" disabled={busy || testing}>
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
