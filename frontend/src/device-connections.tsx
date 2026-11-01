import { useLiveQuery } from "./data";
import { useState } from "react";
import { ArrowUpRight, PlugsConnected } from "@phosphor-icons/react";
import { date } from "./main";
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
  local_aggregate?: { name: string; type: string } | null;
  remote_aggregate?: { name: string; type: string } | null;
  direction_basis?: string;
  members?: { local_port: string | null; remote_port: string | null }[];
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
  const [retry, setRetry] = useState(0);
  const query = useLiveQuery<{ items: Connection[] }>(
    `/devices/${deviceId}/connections`,
    refresh + retry,
  );
  const items = query.data?.items || null;
  const error = query.error;
  function cards(rows: Connection[]) {
    return (
      <ul className="connection-cards">
        {rows.map((row) => (
          <li className="connection-card" key={row.id}>
            <div className="connection-card-heading">
              <span className="connection-direction">
                <PlugsConnected size={18} aria-hidden="true" />
                {row.direction_basis === "stp"
                  ? "Üst bağlantı · STP kök portu"
                  : directions[row.direction]}
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
                <dd className="mono">
                  {row.local_aggregate
                    ? `${row.local_aggregate.name} · ${row.local_aggregate.type}`
                    : row.local_port || "Port bilinmiyor"}
                </dd>
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
                <dd className="mono">
                  {row.remote_aggregate?.name ||
                    (row.members?.length
                      ? "Üye portlar aşağıda"
                      : row.remote_port || "Port bilinmiyor")}
                </dd>
              </div>
            </dl>
            {row.members?.length ? (
              <div className="connection-members">
                <span className="muted">
                  Üye portlar · Bu cihaz → Karşı cihaz
                </span>
                <ul>
                  {row.members.map((member) => (
                    <li key={`${member.local_port}:${member.remote_port}`}>
                      <span className="mono">
                        {member.local_port || "Port bilinmiyor"}
                      </span>
                      <span aria-hidden="true">→</span>
                      <span className="mono">
                        {member.remote_port || "Port bilinmiyor"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
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
        Portlar CDP/LLDP gözlemlerinden, TRK üyeleri cihazın bağlantı grubundan
        alınır. STP kök portu varsa yönü belirler; diğer durumlarda topolojiden
        çıkarılan yön aday olarak gösterilir.
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
          Üst akış bağlantısı henüz belirlenemedi. Bilgileri cihazdan al veya
          Ölçüm al ile güncel komşuluk ve kök portu bilgilerini okuyabilirsiniz.
        </p>
      ) : null}
      {cards(upstream)}
    </section>
  );
}
