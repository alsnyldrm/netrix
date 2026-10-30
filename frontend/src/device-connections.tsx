import { useEffect, useState } from "react";
import { ArrowUpRight, PlugsConnected } from "@phosphor-icons/react";
import { api, date } from "./main";
import "./device-connections.css";

type Peer = { id: string; name: string; management_ip: string };
type Connection = {
  id: string;
  local_port: string | null;
  remote_port: string | null;
  remote_device: Peer | null;
  remote_name: string;
  direction: "upstream" | "downstream" | "peer" | "unknown";
  sources: string[];
  confidence: number;
  last_seen_at: string | null;
};
const directions = {
  upstream: "Üst akış adayı",
  downstream: "Alt bağlantı adayı",
  peer: "Aynı seviye bağlantı",
  unknown: "Yön belirlenemedi",
};

export function DeviceConnections({
  deviceId,
  refresh,
  onDevice,
}: {
  deviceId: string;
  refresh: number;
  onDevice: (device: Peer) => void;
}) {
  const [items, setItems] = useState<Connection[] | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    api(`/devices/${deviceId}/connections`)
      .then((data) => {
        if (active) {
          setItems(data.items);
          setError("");
        }
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [deviceId, refresh, retry]);
  function cards(rows: Connection[]) {
    return (
      <ul className="connection-cards">
        {rows.map((row) => (
          <li className="connection-card" key={row.id}>
            <div className="connection-card-heading">
              <span className="connection-direction">
                <PlugsConnected size={18} aria-hidden="true" />
                {directions[row.direction]}
              </span>
              <span className="connection-evidence">
                {row.sources
                  .map((s) => (s === "manual" ? "Manuel" : s.toUpperCase()))
                  .join(" + ")}
                {" · "}
                {row.confidence >= 1
                  ? "Doğrulanmış bağlantı"
                  : `Eşleşme adayı · %${Math.round(row.confidence * 100)} güven`}
              </span>
            </div>
            <dl className="connection-endpoints">
              <div>
                <dt>Bu cihazın portu</dt>
                <dd className="mono">{row.local_port || "Port bilinmiyor"}</dd>
              </div>
              <div>
                <dt>Karşı cihaz</dt>
                <dd>
                  {row.remote_device ? (
                    <button
                      className="text-button connection-device"
                      onClick={() => onDevice(row.remote_device!)}
                    >
                      <span>{row.remote_name}</span>
                      <ArrowUpRight size={16} aria-hidden="true" />
                    </button>
                  ) : (
                    row.remote_name || "Cihaz bilinmiyor"
                  )}
                  <span className="connection-address mono">
                    {row.remote_device?.management_ip ||
                      "Envanter eşleşmesi yok"}
                  </span>
                </dd>
              </div>
              <div>
                <dt>Karşı cihazın portu</dt>
                <dd className="mono">{row.remote_port || "Port bilinmiyor"}</dd>
              </div>
            </dl>
            <p className="connection-time">
              {row.last_seen_at
                ? `Son gözlem: ${date(row.last_seen_at)}`
                : "Gözlem zamanı yok"}
            </p>
          </li>
        ))}
      </ul>
    );
  }
  const upstream = items?.filter((r) => r.direction === "upstream") || [];
  const others = items?.filter((r) => r.direction !== "upstream") || [];
  return (
    <section
      className="device-connections"
      aria-labelledby="device-connections-title"
    >
      <h3 id="device-connections-title">
        Üst akış bağlantıları{" "}
        <span className="count-pill">{upstream.length}</span>
      </h3>
      <p className="muted">
        Üst akış yönü cihaz türü ve topolojiden çıkarılır; gerçek trafik yönünü
        göstermez. İki uçtaki portlar keşif kaydından alınır.
      </p>
      {error ? (
        <div className="connection-error" role="alert">
          <span>Bağlantılar güncellenemedi: {error}</span>
          <button className="secondary" onClick={() => setRetry((n) => n + 1)}>
            Tekrar dene
          </button>
        </div>
      ) : null}
      {!items && !error ? (
        <p role="status" className="muted">
          Bağlantılar yükleniyor…
        </p>
      ) : null}
      {items && !upstream.length ? (
        <p className="connection-empty">
          {items.length
            ? "Bu cihaz için üst akış bağlantısı bulunamadı. Diğer komşu bağlantılarını aşağıda inceleyebilirsiniz."
            : "Kayıtlı LLDP/CDP komşuluğu veya manuel bağlantı yok. Başarılı SNMP gözleminden sonra bağlantılar burada görünür."}
        </p>
      ) : null}
      {cards(upstream)}
      {others.length ? (
        <details
          className="connection-others"
          open={!upstream.length || undefined}
        >
          <summary>Diğer komşu bağlantıları ({others.length})</summary>
          {cards(others)}
        </details>
      ) : null}
    </section>
  );
}
