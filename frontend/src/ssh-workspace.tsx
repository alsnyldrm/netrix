import React, { useEffect, useRef, useState } from "react";
import {
  TerminalWindow,
  Minus,
  ArrowsOut,
  ArrowsIn,
  ArrowSquareOut,
  X,
  Plus,
  Trash,
  Play,
  Stop,
  ArrowClockwise,
} from "@phosphor-icons/react";
import { api } from "./data";
import { Dialog } from "./main";
import { currentPreferences } from "./preferences";
import "./ssh-workspace.css";
type Row = Record<string, any>;
type Session = {
  id: string;
  device_id: string;
  device_name: string;
  management_ip: string;
  minimized: boolean;
};
export function openSSH(device: Row) {
  window.dispatchEvent(new CustomEvent("netrix:ssh-open", { detail: device }));
}
export function sendBulkCommand(devices: Row[]) {
  window.dispatchEvent(
    new CustomEvent("netrix:ssh-batch", { detail: devices }),
  );
}
const states: Record<string, string> = {
  queued: "Bekliyor",
  connected: "Bağlı",
  closed: "Kapandı",
  failed: "Başarısız",
  running: "Çalışıyor",
  succeeded: "Başarılı",
  cancelled: "İptal edildi",
  completed: "Tamamlandı",
  reconnecting: "Yeniden bağlanılıyor",
};

function Terminal({
  id,
  hidden,
  sendRef,
  onStatus,
}: {
  id: string;
  hidden: boolean;
  sendRef: React.MutableRefObject<((data: string) => void) | null>;
  onStatus: (state: string, error?: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const resize = useRef<(() => void) | null>(null);
  const statusCallback = useRef(onStatus);
  statusCallback.current = onStatus;
  useEffect(() => {
    let disposed = false;
    let terminal: import("@xterm/xterm").Terminal | undefined;
    let socket: WebSocket | undefined;
    let observer: ResizeObserver | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    Promise.all([
      import("@xterm/xterm"),
      import("@xterm/addon-fit"),
      import("@xterm/xterm/css/xterm.css"),
    ])
      .then(([{ Terminal }, { FitAddon }]) => {
        if (disposed || !host.current) return;
        terminal = new Terminal({
          cursorBlink: true,
          scrollback: 1000,
          fontFamily: '"IBM Plex Mono", monospace',
          fontSize: 13,
          allowProposedApi: false,
          theme: {
            background: "#0b1220",
            foreground: "#e2e8f0",
            cursor: "#93c5fd",
            selectionBackground: "#31415f",
          },
          screenReaderMode: true,
          allowTransparency: false,
        });
        const fit = new FitAddon();
        terminal.loadAddon(fit);
        terminal.open(host.current);
        // Terminal text is never inserted as HTML; clipboard and URL addons are deliberately absent.
        const fitVisible = () => {
          if (
            host.current &&
            host.current.clientWidth &&
            host.current.clientHeight
          ) {
            fit.fit();
            if (socket?.readyState === WebSocket.OPEN)
              socket.send(
                JSON.stringify({
                  type: "resize",
                  cols: terminal!.cols,
                  rows: terminal!.rows,
                }),
              );
          }
        };
        resize.current = fitVisible;
        observer = new ResizeObserver(fitVisible);
        observer.observe(host.current);
        fitVisible();
        sendRef.current = (data) => {
          if (socket?.readyState === WebSocket.OPEN)
            socket.send(JSON.stringify({ type: "input", data }));
        };
        terminal.onData((data) => sendRef.current?.(data));
        const connect = () => {
          if (disposed) return;
          socket = new WebSocket(
            `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/v1/access/sessions/${id}/ws`,
          );
          socket.onopen = () => {
            attempts = 0;
            terminal?.reset();
            fitVisible();
            terminal?.focus();
          };
          socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === "output") terminal?.write(data.data);
            if (data.type === "status")
              statusCallback.current(data.status, data.error);
          };
          socket.onclose = (event) => {
            if (disposed) return;
            if ([1008, 4001].includes(event.code)) {
              statusCallback.current(
                "closed",
                event.code === 4001
                  ? "Oturum başka bir pencerede açıldı."
                  : "Oturum veya erişim yetkisi sona erdi.",
              );
              return;
            }
            if (attempts++ < 3) {
              statusCallback.current("reconnecting");
              retry = setTimeout(connect, 1000 * attempts);
            } else
              statusCallback.current(
                "failed",
                "Terminal bağlantısı kesildi. Pencereyi kapatıp yeniden bağlanın.",
              );
          };
        };
        connect();
      })
      .catch(() =>
        statusCallback.current("failed", "Terminal bileşeni yüklenemedi."),
      );
    return () => {
      disposed = true;
      clearTimeout(retry);
      observer?.disconnect();
      socket?.close();
      terminal?.dispose();
      resize.current = null;
      sendRef.current = null;
    };
  }, [id, sendRef]);
  useEffect(() => {
    if (!hidden) requestAnimationFrame(() => resize.current?.());
  }, [hidden]);
  return <div className="ssh-terminal" ref={host} aria-label="SSH terminali" />;
}

function SavedCommands({
  send,
  enabled,
}: {
  send: (value: string) => void;
  enabled: boolean;
}) {
  const [items, setItems] = useState<Row[]>([]);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/access/commands")
      .then((v) => setItems(v.items))
      .catch((e) => setError(e.message));
  }, []);
  const save = async (next: Row[]) => {
    setBusy(true);
    setError("");
    try {
      const saved = await api("/access/commands", "PUT", { items: next });
      setItems(saved.items);
      return true;
    } catch (e: any) {
      setError(e.message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="ssh-commands" aria-label="Hazır komutlar">
      <div className="ssh-commands-head">
        <h3>Hazır komutlar</h3>
        <button
          className="icon-button"
          aria-label="Hazır komut kaydet"
          aria-expanded={editing}
          onClick={() => setEditing((v) => !v)}
        >
          <Plus size={18} />
        </button>
      </div>
      {editing && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (
              await save([...items, { id: crypto.randomUUID(), name, command }])
            ) {
              setName("");
              setCommand("");
              setEditing(false);
            }
          }}
        >
          <label>
            Komut adı
            <input
              required
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Komut
            <textarea
              required
              maxLength={4000}
              rows={3}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
            />
          </label>
          <button className="secondary" disabled={busy || items.length >= 50}>
            Komutu kaydet
          </button>
        </form>
      )}
      <div className="ssh-command-list">
        {items.map((item) => (
          <div key={item.id}>
            <button
              className="ssh-command-run"
              title={item.command}
              disabled={!enabled || busy}
              onClick={() => send(item.command.replace(/\r?\n/g, "\r") + "\r")}
            >
              <Play size={15} />
              <span>{item.name}</span>
            </button>
            <button
              className="icon-button"
              disabled={busy}
              aria-label={`${item.name} komutunu sil`}
              onClick={() => void save(items.filter((v) => v.id !== item.id))}
            >
              <Trash size={15} />
            </button>
          </div>
        ))}
      </div>
      {!items.length && !editing && (
        <p className="muted">
          Sık kullandığınız komutları kaydedin; tek tıkla terminalde çalıştırın.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function SessionWindow({
  session,
  standalone,
  onClose,
  onMinimize,
  onDetach,
}: {
  session: Session;
  standalone?: boolean;
  onClose: () => void;
  onMinimize: () => void;
  onDetach: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [full, setFull] = useState(!!standalone);
  const [status, setStatus] = useState("queued");
  const [error, setError] = useState("");
  const [features, setFeatures] = useState(currentPreferences().features);
  const send = useRef<((data: string) => void) | null>(null);
  useEffect(() => {
    const handler = (e: Event) =>
      setFeatures((e as CustomEvent).detail.features);
    window.addEventListener("netrix:preferences", handler);
    return () => window.removeEventListener("netrix:preferences", handler);
  }, []);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    if (session.minimized) dialog.current?.close();
    else if (!dialog.current?.open) {
      dialog.current?.showModal();
    }
    return () => {
      if (!session.minimized) {
        dialog.current?.close();
        previous?.focus();
      }
    };
  }, [session.minimized]);
  return (
    <dialog
      ref={dialog}
      className={`ssh-dialog${full ? " ssh-full" : ""}`}
      aria-label={`${session.device_name} SSH bağlantısı`}
      onCancel={(event) => {
        event.preventDefault();
        if (features.includes("session_dock") && !standalone) onMinimize();
        else onClose();
      }}
    >
      <header className="ssh-header">
        <div className="ssh-heading">
          <TerminalWindow size={22} />
          <div>
            <h2>{session.device_name}</h2>
            <span className="mono">{session.management_ip}</span>
          </div>
        </div>
        <span className={`ssh-state state-${status}`} role="status">
          {states[status] || status}
        </span>
        <div className="ssh-window-actions">
          {!standalone && (
            <>
              <button
                className="icon-button"
                aria-label="Simge durumuna küçült"
                title="Simge durumuna küçült"
                disabled={!features.includes("session_dock")}
                onClick={onMinimize}
              >
                <Minus size={19} />
              </button>
              <button
                className="icon-button"
                aria-label="Yeni sekmede aç"
                title="Yeni sekmede aç"
                onClick={onDetach}
              >
                <ArrowSquareOut size={19} />
              </button>
            </>
          )}
          <button
            className="icon-button"
            aria-label={full ? "Pencereyi küçült" : "Tam ekran"}
            title={full ? "Pencereyi küçült" : "Tam ekran"}
            onClick={() => setFull((v) => !v)}
          >
            {full ? <ArrowsIn size={19} /> : <ArrowsOut size={19} />}
          </button>
          <button
            className="icon-button"
            aria-label="SSH bağlantısını kapat"
            title="Bağlantıyı sonlandır"
            onClick={onClose}
          >
            <X size={19} />
          </button>
        </div>
      </header>
      {error && (
        <p className="ssh-error" role="alert">
          {error}
        </p>
      )}
      <div
        className={`ssh-body${features.includes("saved_commands") ? " with-commands" : ""}`}
      >
        <Terminal
          id={session.id}
          hidden={session.minimized}
          sendRef={send}
          onStatus={(state, message) => {
            setStatus(state);
            setError(message || "");
          }}
        />
        {features.includes("saved_commands") && (
          <SavedCommands
            enabled={status === "connected"}
            send={(value) => send.current?.(value)}
          />
        )}
      </div>
      <footer className="ssh-footer">
        <span>SSH · Şifreli bağlantı</span>
        <span>15 dk hareketsizlikte kapanır</span>
      </footer>
    </dialog>
  );
}

function BulkCommand({
  devices,
  onClose,
}: {
  devices: Row[];
  onClose: () => void;
}) {
  const [command, setCommand] = useState("");
  const [timeout, setTimeoutValue] = useState(30);
  const [id, setId] = useState("");
  const [data, setData] = useState<Row>({
    status: "draft",
    targets: devices.map((d) => ({
      device_id: d.id,
      name: d.name,
      management_ip: d.management_ip,
      status: "queued",
      output: "",
    })),
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(devices[0]?.id || "");
  const running = ["queued", "running"].includes(data.status);
  const activeBatch = useRef({ id, running });
  activeBatch.current = { id, running };
  useEffect(
    () => () => {
      const value = activeBatch.current;
      if (value.id && value.running)
        void fetch(`/api/v1/access/batches/${value.id}`, {
          method: "DELETE",
          credentials: "same-origin",
          keepalive: true,
          headers: { "X-Netrix-Request": "1" },
        });
    },
    [],
  );
  useEffect(() => {
    if (!id) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await api("/access/batches/" + id);
        if (!stopped) {
          setData(value);
          if (["queued", "running"].includes(value.status))
            timer = setTimeout(poll, 700);
        }
      } catch (e: any) {
        if (!stopped) setError(e.message);
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [id]);
  const start = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api("/access/batches", "POST", {
        device_ids: devices.map((d) => d.id),
        command,
        timeout,
      });
      setData((v) => ({ ...v, status: result.status }));
      setId(result.id);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const target = data.targets?.find((t: Row) => t.device_id === active);
  return (
    <Dialog title="Toplu komut gönder" onClose={onClose} wide>
      <div className="ssh-batch">
        <p>{devices.length} seçili cihaz · Aynı anda en fazla dört bağlantı</p>
        <form onSubmit={start}>
          <label>
            Gönderilecek komut
            <textarea
              required
              rows={3}
              maxLength={4000}
              value={command}
              disabled={!!id || busy}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="Örnek: show version"
            />
          </label>
          <div className="batch-submit">
            <label>
              Cihaz başına süre (saniye)
              <input
                type="number"
                min={5}
                max={120}
                value={timeout}
                disabled={!!id || busy}
                onChange={(e) => setTimeoutValue(Number(e.target.value))}
              />
            </label>
            {!id ? (
              <button
                className="primary"
                disabled={busy || !devices.length || devices.length > 100}
              >
                <Play size={18} />
                {busy ? "Gönderiliyor…" : "Komutu gönder"}
              </button>
            ) : running ? (
              <button
                type="button"
                className="secondary"
                onClick={async () => {
                  try {
                    await api("/access/batches/" + id, "DELETE");
                  } catch (e: any) {
                    setError(e.message);
                  }
                }}
              >
                <Stop size={18} />
                İptal et
              </button>
            ) : (
              <span role="status">{states[data.status] || data.status}</span>
            )}
          </div>
        </form>
        {error && (
          <p className="error" role="alert">
            {error}
            <button
              className="text-button"
              onClick={async () => {
                if (id) {
                  try {
                    setData(await api("/access/batches/" + id));
                    setError("");
                  } catch (e: any) {
                    setError(e.message);
                  }
                }
              }}
            >
              Sonucu yenile
            </button>
          </p>
        )}
        <div className="batch-summary" role="status">
          {data.targets.filter((t: Row) => t.status === "succeeded").length}{" "}
          başarılı ·{" "}
          {
            data.targets.filter((t: Row) =>
              ["failed", "cancelled"].includes(t.status),
            ).length
          }{" "}
          başarısız / iptal ·{" "}
          {
            data.targets.filter((t: Row) =>
              ["queued", "running"].includes(t.status),
            ).length
          }{" "}
          bekleyen
        </div>
        <div className="batch-results">
          <nav aria-label="Komut gönderilen cihazlar">
            {data.targets.map((t: Row) => (
              <button
                key={t.device_id}
                className={active === t.device_id ? "selected" : ""}
                aria-current={active === t.device_id ? "true" : undefined}
                onClick={() => setActive(t.device_id)}
              >
                <b>{t.name}</b>
                <small className="mono">{t.management_ip}</small>
                <span className={`ssh-state state-${t.status}`}>
                  {states[t.status]}
                </span>
              </button>
            ))}
          </nav>
          <section aria-label="Seçili cihazın komut sonucu">
            <h3>{target?.name}</h3>
            <pre>
              {target?.output ||
                (id
                  ? "Cihazdan yanıt bekleniyor…"
                  : "Komut gönderildiğinde cihaz çıktısı burada görünür.")}
            </pre>
          </section>
        </div>
        <p className="muted">
          Sonuçlar 10 dakika tutulur. Otomatik tekrar yoktur. İptal, cihaza
          ulaşmış bir komutu geri almaz.
        </p>
      </div>
    </Dialog>
  );
}

export function SSHWorkspace({ standaloneId }: { standaloneId?: string }) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const sessionRef = useRef(sessions);
  sessionRef.current = sessions;
  const [batch, setBatch] = useState<Row[] | null>(null);
  const [error, setError] = useState("");
  const pending = useRef(false);
  useEffect(() => {
    if (standaloneId) {
      api("/access/sessions/" + standaloneId)
        .then((value) => setSessions([{ ...value, minimized: false }]))
        .catch((e) => setError(e.message));
      return;
    }
    const open = async (event: Event) => {
      if (pending.current) return;
      if (
        sessionRef.current.length >= 16 ||
        (sessionRef.current.filter((s) => s.minimized).length >= 15 &&
          sessionRef.current.some((s) => !s.minimized))
      ) {
        setError(
          "En fazla 15 küçültülmüş oturum açabilirsiniz. Önce bir oturumu kapatın.",
        );
        return;
      }
      pending.current = true;
      const device = (event as CustomEvent).detail;
      try {
        const saved = await api("/access/sessions", "POST", {
          device_id: device.id,
        });
        setSessions((values) => [
          ...values.map((v) => ({ ...v, minimized: true })),
          { ...saved, device_id: device.id, minimized: false },
        ]);
      } catch (e: any) {
        setError(e.message);
      } finally {
        pending.current = false;
      }
    };
    const bulk = (event: Event) => {
      setSessions((v) => v.map((s) => ({ ...s, minimized: true })));
      setBatch((event as CustomEvent).detail);
    };
    window.addEventListener("netrix:ssh-open", open);
    window.addEventListener("netrix:ssh-batch", bulk);
    return () => {
      window.removeEventListener("netrix:ssh-open", open);
      window.removeEventListener("netrix:ssh-batch", bulk);
    };
  }, [standaloneId]);
  useEffect(
    () => () => {
      for (const session of sessionRef.current)
        void fetch(`/api/v1/access/sessions/${session.id}`, {
          method: "DELETE",
          headers: { "X-Netrix-Request": "1" },
          credentials: "same-origin",
          keepalive: true,
        });
    },
    [],
  );
  const close = async (id: string) => {
    try {
      await api("/access/sessions/" + id, "DELETE");
      setSessions((v) => v.filter((s) => s.id !== id));
      if (standaloneId)
        setError("SSH oturumu kapatıldı. Bu sekmeyi kapatabilirsiniz.");
    } catch (e: any) {
      setError(e.message);
    }
  };
  const minimize = (id: string) => {
    if (sessionRef.current.filter((v) => v.minimized).length >= 15) {
      setError("En fazla 15 oturum küçültülebilir. Önce bir oturumu kapatın.");
      return;
    }
    setSessions((v) =>
      v.map((s) => (s.id === id ? { ...s, minimized: true } : s)),
    );
  };
  const detach = (id: string) => {
    const next = window.open(`/terminal/${id}`, "_blank");
    if (!next) {
      setError(
        "Tarayıcı yeni sekmeyi engelledi. Bu site için açılır pencerelere izin verin.",
      );
      return;
    }
    next.opener = null;
    setSessions((v) => v.filter((s) => s.id !== id));
  };
  return (
    <>
      {standaloneId && (
        <main className="standalone-terminal">
          <h1>NETRIX · SSH çalışma alanı</h1>
          <a href="/#devices">Cihaz envanterine dön</a>
        </main>
      )}
      {sessions.map((session) => (
        <SessionWindow
          key={session.id}
          session={session}
          standalone={!!standaloneId}
          onClose={() => void close(session.id)}
          onMinimize={() => minimize(session.id)}
          onDetach={() => detach(session.id)}
        />
      ))}
      {!!sessions.filter((s) => s.minimized).length && (
        <nav className="ssh-dock" aria-label="Küçültülmüş SSH oturumları">
          <span>{sessions.filter((s) => s.minimized).length}/15</span>
          {sessions
            .filter((s) => s.minimized)
            .map((session) => (
              <div key={session.id}>
                <button
                  title={session.management_ip}
                  aria-label={`${session.device_name} SSH oturumunu aç`}
                  onClick={() =>
                    setSessions((v) =>
                      v.map((s) => ({ ...s, minimized: s.id !== session.id })),
                    )
                  }
                >
                  <TerminalWindow size={18} />
                  <span>{session.device_name}</span>
                </button>
                <button
                  aria-label={`${session.device_name} SSH oturumunu kapat`}
                  onClick={() => void close(session.id)}
                >
                  <X size={15} />
                </button>
              </div>
            ))}
        </nav>
      )}
      {batch && <BulkCommand devices={batch} onClose={() => setBatch(null)} />}
      {error && (
        <Dialog title="SSH bağlantısı" onClose={() => setError("")}>
          <p role="alert">{error}</p>
          <div className="dialog-actions">
            <button className="secondary" onClick={() => setError("")}>
              Tamam
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
