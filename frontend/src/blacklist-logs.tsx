import { useDeferredValue, useEffect, useState } from "react";
import { ArrowClockwise, Info, MagnifyingGlass } from "@phosphor-icons/react";
import { api, useLiveQuery } from "./data";
import { Dialog, date } from "./main";
import "./blacklist.css";
import "./blacklist-logs.css";

type LogRow = {
  id: string;
  device_id: string;
  device_name: string;
  management_ip: string;
  received_at: string;
  occurred_at: string | null;
  peer_address: string;
  transport: string;
  acl: string | null;
  source_address: string | null;
  destination_address: string | null;
  action: string;
  message: string;
};
type Cursor = { before: string; before_id: string };
type LogResult = {
  items: LogRow[];
  next: Cursor | null;
  receiver: {
    ready: boolean;
    host: string;
    port: number;
    transport: string;
    dropped: number;
    last_received_at: string | null;
    retention_days: number;
  };
};
const ACTIONS: Record<string, string> = {
  deny: "Engellendi",
  permit: "İzin verildi",
  unknown: "Belirsiz",
};

export default function BlacklistLogs({ refresh }: { refresh: number }) {
  const [q, setQ] = useState("");
  const search = useDeferredValue(q.trim());
  const [device, setDevice] = useState("");
  const [hours, setHours] = useState("24");
  const [cursors, setCursors] = useState<(Cursor | null)[]>([null]);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<LogRow>();
  const [refreshing, setRefreshing] = useState(false);
  const cursor = cursors[cursors.length - 1];
  const params = new URLSearchParams({ hours, q: search });
  if (device) params.set("device_id", device);
  if (cursor) {
    params.set("before", cursor.before);
    params.set("before_id", cursor.before_id);
  }
  const key = "/blacklist/logs?" + params;
  const query = useLiveQuery<LogResult>(key, refresh + revision);
  const devices = useLiveQuery<{
    items: { id: string; name: string; management_ip: string }[];
  }>("/blacklist/devices", refresh);
  useEffect(() => {
    if (cursor) return;
    const interval = window.setInterval(() => {
      if (!document.hidden) setRevision((value) => value + 1);
    }, 10000);
    return () => window.clearInterval(interval);
  }, [cursor]);
  async function reload() {
    setRefreshing(true);
    try {
      await api(key);
      setRevision((value) => value + 1);
    } finally {
      setRefreshing(false);
    }
  }
  function reset() {
    setCursors([null]);
  }
  const status = query.data?.receiver;
  return (
    <div className="acl-log-workspace">
      <div className="info-note acl-log-receiver" role="status">
        <Info size={18} aria-hidden="true" />
        <div>
          <strong>
            {status?.ready
              ? "Syslog alıcısı çalışıyor"
              : "Syslog alıcısı bekleniyor"}
          </strong>
          {status && (
            <span>
              {status.host
                ? `${status.host} · ${status.port}/UDP ve TCP`
                : "Alıcı adresi yapılandırılmalı"}
              {status.last_received_at
                ? ` · Son ACL kaydı ${date(status.last_received_at)}`
                : " · Henüz ACL kaydı alınmadı"}
            </span>
          )}
        </div>
      </div>
      {!!status?.dropped && (
        <p className="error" role="alert">
          Alıcıda {status.dropped} mesaj işlenemedi. Cihaz ve alıcı erişimini
          kontrol edin.
        </p>
      )}
      <section className="panel blacklist-panel" aria-label="Cihaz ACL logları">
        <div className="acl-log-filters">
          <label className="search-box">
            <MagnifyingGlass size={17} aria-hidden="true" />
            <input
              type="search"
              name="acl-log-search"
              aria-label="ACL loglarında ara"
              placeholder="Cihaz, IP, ACL veya mesaj ara…"
              value={q}
              onChange={(event) => {
                setQ(event.target.value);
                reset();
              }}
              autoComplete="off"
            />
          </label>
          <label>
            Cihaz
            <select
              aria-label="Cihaz"
              value={device}
              onChange={(event) => {
                setDevice(event.target.value);
                reset();
              }}
            >
              <option value="">Tüm cihazlar</option>
              {devices.data?.items.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.name} · {item.management_ip}
                </option>
              ))}
            </select>
          </label>
          <label>
            Zaman aralığı
            <select
              aria-label="Zaman aralığı"
              value={hours}
              onChange={(event) => {
                setHours(event.target.value);
                reset();
              }}
            >
              <option value="1">Son 1 saat</option>
              <option value="24">Son 24 saat</option>
              <option value="168">Son 7 gün</option>
              <option value="720">Son 30 gün</option>
            </select>
          </label>
          <button
            className="secondary"
            disabled={refreshing || query.loading}
            onClick={() =>
              void reload().catch(() => setRevision((value) => value + 1))
            }
          >
            <ArrowClockwise size={17} aria-hidden="true" />
            Yenile
          </button>
        </div>
        {query.error && (
          <p className="error" role="alert">
            {query.error}
          </p>
        )}
        {devices.error && (
          <p className="error" role="alert">
            {devices.error}
          </p>
        )}
        {query.loading && (
          <p className="blacklist-empty" role="status">
            ACL logları yükleniyor…
          </p>
        )}
        {!query.loading && !query.error && query.data?.items.length === 0 && (
          <div className="blacklist-empty">
            <strong>Bu filtrelerde ACL logu bulunamadı</strong>
            <p>
              Cihazların ürettiği eşleşme kayıtları burada görünür. Log
              üretimini açmak için ilgili IP kaydını Gönder ile yeniden
              uygulayın.
            </p>
            <a className="secondary" href="#blacklist">
              IP kayıtlarını aç
            </a>
          </div>
        )}
        {!!query.data?.items.length && (
          <div
            className="table-scroll acl-log-table"
            tabIndex={0}
            role="region"
            aria-label="ACL log tablosu"
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">Alınma zamanı</th>
                  <th scope="col">Cihaz</th>
                  <th scope="col">ACL</th>
                  <th scope="col">Kaynak IP</th>
                  <th scope="col">Hedef IP</th>
                  <th scope="col">Sonuç</th>
                  <th scope="col">İşlem</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((row) => (
                  <tr key={row.id}>
                    <td>{date(row.received_at)}</td>
                    <td>
                      <strong>{row.device_name}</strong>
                      <small className="mono">{row.management_ip}</small>
                    </td>
                    <td className="mono">{row.acl || "—"}</td>
                    <td className="mono">{row.source_address || "—"}</td>
                    <td className="mono">{row.destination_address || "—"}</td>
                    <td>{ACTIONS[row.action] || row.action}</td>
                    <td>
                      <button
                        className="secondary"
                        onClick={() => setSelected(row)}
                        aria-label={`${row.device_name} ${date(row.received_at)} log ayrıntısı`}
                      >
                        Ayrıntı
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="acl-log-footer">
          <span>30 gün saklanır · {cursors.length}. sayfa</span>
          <div>
            <button
              className="secondary"
              disabled={cursors.length === 1 || query.loading}
              onClick={() => setCursors((values) => values.slice(0, -1))}
            >
              Önceki
            </button>
            <button
              className="secondary"
              disabled={!query.data?.next || query.loading}
              onClick={() =>
                query.data?.next &&
                setCursors((values) => [...values, query.data!.next])
              }
            >
              Sonraki
            </button>
          </div>
        </div>
      </section>
      {selected && (
        <Dialog
          title="ACL log ayrıntısı"
          wide
          onClose={() => setSelected(undefined)}
        >
          <div className="acl-log-detail">
            <dl>
              <div>
                <dt>Cihaz</dt>
                <dd>{selected.device_name}</dd>
              </div>
              <div>
                <dt>Alınma zamanı</dt>
                <dd>{date(selected.received_at)}</dd>
              </div>
              <div>
                <dt>Cihaz olay zamanı</dt>
                <dd>
                  {selected.occurred_at
                    ? date(selected.occurred_at)
                    : "Logda saat dilimli zaman yok"}
                </dd>
              </div>
              <div>
                <dt>Aktarım</dt>
                <dd>
                  {selected.transport === "syslog_tcp"
                    ? "Syslog TCP"
                    : "Syslog UDP"}
                </dd>
              </div>
              <div>
                <dt>Gönderen adres</dt>
                <dd className="mono">{selected.peer_address}</dd>
              </div>
              <div>
                <dt>Sonuç</dt>
                <dd>{ACTIONS[selected.action]}</dd>
              </div>
            </dl>
            <div>
              <span>Cihaz mesajı</span>
              <pre>{selected.message}</pre>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
