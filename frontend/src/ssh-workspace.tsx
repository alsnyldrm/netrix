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
  PencilSimple,
  TextAa,
  CaretLeft,
  CaretRight,
  ListBullets,
  ArrowBendDownLeft,
} from "@phosphor-icons/react";
import { api } from "./data";
import { Dialog } from "./main";
import {
  applyPreferences,
  currentPreferences,
  defaultTerminalAppearance,
} from "./preferences";
import type { TerminalAppearance } from "./preferences";
import "@fontsource/ibm-plex-mono/700.css";
import "./ssh-workspace.css";
type Row = Record<string, any>;
type Session = {
  id: string;
  device_id: string;
  device_name: string;
  management_ip: string;
  idle_timeout_minutes?: number;
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

const terminalFonts = {
  ubuntu: '"Ubuntu Mono", monospace',
  plex: '"IBM Plex Mono", monospace',
  system: 'ui-monospace, "DejaVu Sans Mono", Consolas, monospace',
};
function terminalOptions(value: TerminalAppearance) {
  const rgb = value.background
    .slice(1)
    .match(/../g)!
    .map((c) => parseInt(c, 16) / 255);
  const luminance = rgb
    .map((c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    .reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0);
  const light = luminance < 0.179;
  const foreground = light ? "#ffffff" : "#000000";
  return {
    fontSize: value.font_size,
    fontWeight: value.font_weight,
    fontWeightBold: 700 as const,
    fontFamily: terminalFonts[value.font],
    cursorBlink: false,
    cursorStyle: "block" as const,
    cursorInactiveStyle: "outline" as const,
    theme: {
      background: value.background,
      foreground,
      cursor: foreground,
      cursorAccent: value.background,
      selectionBackground: light ? "#ffffff" : "#000000",
      selectionForeground: value.background,
    },
  };
}
async function loadTerminalFont(value: TerminalAppearance) {
  if (value.font !== "system")
    await document.fonts.load(
      `${value.font_weight} ${value.font_size}px ${terminalFonts[value.font].split(",")[0]}`,
    );
}

function Terminal({
  id,
  hidden,
  sendRef,
  onStatus,
  appearance,
}: {
  id: string;
  appearance: TerminalAppearance;
  hidden: boolean;
  sendRef: React.MutableRefObject<((data: string) => void) | null>;
  onStatus: (state: string, error?: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const resize = useRef<(() => void) | null>(null);
  const readyAppearance = useRef(appearance);
  const appearanceRef = useRef(appearance);
  appearanceRef.current = appearance;
  const statusCallback = useRef(onStatus);
  statusCallback.current = onStatus;
  useEffect(() => {
    let disposed = false;
    let terminal: import("@xterm/xterm").Terminal | undefined;
    let socket: WebSocket | undefined;
    let observer: ResizeObserver | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempts = 0;
    let frame = 0;
    let fontFrame = 0;
    let appliedFont = "";
    let lastCols = 0,
      lastRows = 0;
    Promise.all([
      import("@xterm/xterm"),
      import("@xterm/addon-fit"),
      import("@xterm/xterm/css/xterm.css"),
      loadTerminalFont(appearanceRef.current),
    ])
      .then(([{ Terminal }, { FitAddon }]) => {
        if (disposed || !host.current) return;
        terminal = new Terminal({
          ...terminalOptions(appearanceRef.current),
          scrollback: 1000,
          allowProposedApi: false,
          screenReaderMode: true,
          allowTransparency: false,
        });
        const fit = new FitAddon();
        terminal.loadAddon(fit);
        terminal.open(host.current);
        // Terminal text is never inserted as HTML; clipboard and URL addons are deliberately absent.
        const fitVisible = () => {
          cancelAnimationFrame(frame);
          frame = requestAnimationFrame(() => {
            if (
              disposed ||
              !host.current?.getClientRects().length ||
              !host.current.clientWidth ||
              !host.current.clientHeight
            )
              return;
            const value = readyAppearance.current;
            const signature = JSON.stringify([
              value.font,
              value.font_size,
              value.font_weight,
              value.background,
            ]);
            if (appliedFont !== signature) {
              appliedFont = signature;
              terminal!.options = terminalOptions(value);
              // Xterm 6 can cache the previous used font size while styles settle.
              // Wait for the measuring span, then invalidate via the equivalent
              // public weight option. No private renderer API or buffer reset.
              cancelAnimationFrame(fontFrame);
              let checks = 0;
              const settleFont = () => {
                if (disposed) return;
                if (!host.current?.getClientRects().length) {
                  appliedFont = "";
                  return;
                }
                const measure = host.current.querySelector(
                  ".xterm-char-measure-element",
                );
                const measuredFont = measure && getComputedStyle(measure);
                const primaryFont = (family: string) =>
                  family
                    .split(",")[0]
                    .replace(/["']/g, "")
                    .trim()
                    .toLowerCase();
                if (
                  measuredFont &&
                  (measuredFont.fontSize !== `${value.font_size}px` ||
                    primaryFont(measuredFont.fontFamily) !==
                      primaryFont(terminalFonts[value.font])) &&
                  checks++ < 120
                ) {
                  fontFrame = requestAnimationFrame(settleFont);
                  return;
                }
                terminal!.options.fontWeight =
                  value.font_weight === 700 ? "bold" : "normal";
                fitVisible();
              };
              fontFrame = requestAnimationFrame(settleFont);
              return;
            }
            fit.fit();
            if (
              socket?.readyState === WebSocket.OPEN &&
              (terminal!.cols !== lastCols || terminal!.rows !== lastRows)
            ) {
              lastCols = terminal!.cols;
              lastRows = terminal!.rows;
              socket.send(
                JSON.stringify({
                  type: "resize",
                  cols: lastCols,
                  rows: lastRows,
                }),
              );
            }
          });
        };
        resize.current = fitVisible;
        observer = new ResizeObserver(fitVisible);
        observer.observe(host.current);
        fitVisible();
        sendRef.current = (data) => {
          if (socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "input", data }));
            terminal?.focus();
          }
        };
        terminal.onData((data) => sendRef.current?.(data));
        const connect = () => {
          if (disposed) return;
          socket = new WebSocket(
            `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/api/v1/access/sessions/${id}/ws`,
          );
          socket.onopen = () => {
            attempts = 0;
            lastCols = 0;
            lastRows = 0;
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
      cancelAnimationFrame(frame);
      cancelAnimationFrame(fontFrame);
      socket?.close();
      terminal?.dispose();
      resize.current = null;
      sendRef.current = null;
    };
  }, [id, sendRef]);
  useEffect(() => {
    let active = true;
    void loadTerminalFont(appearance)
      .then(() => {
        if (active) {
          readyAppearance.current = appearance;
          resize.current?.();
        }
      })
      .catch(() =>
        statusCallback.current("failed", "Terminal yazı tipi yüklenemedi."),
      );
    return () => {
      active = false;
    };
  }, [
    appearance.font,
    appearance.font_size,
    appearance.font_weight,
    appearance.background,
  ]);
  useEffect(() => {
    if (!hidden) requestAnimationFrame(() => resize.current?.());
  }, [hidden]);
  return (
    <div
      className="ssh-terminal"
      style={{ background: appearance.background }}
      ref={host}
      aria-label="SSH terminali"
    />
  );
}

function SavedCommands({
  send,
  enabled,
  onCollapse,
  onResize,
  selectOnly = false,
}: {
  send: (value: string) => void;
  enabled: boolean;
  onCollapse: () => void;
  onResize: (delta: number) => void;
  selectOnly?: boolean;
}) {
  const [items, setItems] = useState<Row[]>([]);
  const [editing, setEditing] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/access/commands")
      .then((v) => setItems(v.items))
      .catch((e) => setError(e.message));
    const updated = (event: Event) => setItems((event as CustomEvent).detail);
    window.addEventListener("netrix:commands", updated);
    return () => window.removeEventListener("netrix:commands", updated);
  }, []);
  const save = async (next: Row[]) => {
    setBusy(true);
    setError("");
    try {
      const saved = await api("/access/commands", "PUT", { items: next });
      setItems(saved.items);
      window.dispatchEvent(
        new CustomEvent("netrix:commands", { detail: saved.items }),
      );
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
        <div className="ssh-command-tools">
          <button
            className="icon-button ssh-panel-resize-button"
            aria-label="Hazır komutları sola genişlet"
            title="Sola genişlet"
            onClick={() => onResize(60)}
          >
            <CaretLeft size={16} aria-hidden="true" />
          </button>
          <button
            className="icon-button ssh-panel-resize-button"
            aria-label="Hazır komutları daralt"
            title="Daralt"
            onClick={() => onResize(-60)}
          >
            <CaretRight size={16} aria-hidden="true" />
          </button>
          <button
            className="icon-button"
            aria-label="Hazır komut kaydet"
            title="Hazır komut ekle"
            aria-expanded={editing}
            disabled={busy}
            onClick={() => {
              setEditingId(null);
              setName("");
              setCommand("");
              setEditing(true);
              setError("");
            }}
          >
            <Plus size={18} aria-hidden="true" />
          </button>
          <button
            className="icon-button"
            aria-label="Hazır komutları gizle"
            title="Paneli daralt"
            onClick={onCollapse}
          >
            <ArrowsIn size={16} aria-hidden="true" />
          </button>
        </div>
      </div>
      {editing && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const item = {
              id: editingId || crypto.randomUUID(),
              name,
              command,
            };
            if (
              await save(
                editingId
                  ? items.map((v) => (v.id === editingId ? item : v))
                  : [...items, item],
              )
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
              autoFocus
              name="command-name"
              autoComplete="off"
              disabled={busy}
              required
              maxLength={80}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Komut
            <textarea
              aria-label="Komut"
              name="command-text"
              autoComplete="off"
              spellCheck={false}
              disabled={busy}
              required
              maxLength={4000}
              rows={3}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
            />
          </label>
          <div className="ssh-command-form-actions">
            <button
              className="secondary"
              disabled={busy || (!editingId && items.length >= 50)}
            >
              {busy
                ? "Kaydediliyor…"
                : editingId
                  ? "Değişiklikleri kaydet"
                  : "Komutu kaydet"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => {
                setEditing(false);
                setEditingId(null);
                setError("");
              }}
            >
              Vazgeç
            </button>
          </div>
        </form>
      )}
      <div className="ssh-command-list">
        {items.map((item) => (
          <div key={item.id}>
            <button
              className="ssh-command-run"
              title={item.command}
              aria-label={`${item.name} komutunu ${selectOnly ? "seç" : "çalıştır"}`}
              disabled={!enabled || busy}
              onClick={() =>
                send(
                  selectOnly
                    ? item.command
                    : item.command.replace(/\r?\n/g, "\r") + "\r",
                )
              }
            >
              {selectOnly ? (
                <ArrowBendDownLeft size={16} aria-hidden="true" />
              ) : (
                <Play size={16} aria-hidden="true" />
              )}
              <span>{item.name}</span>
            </button>
            <button
              className="icon-button"
              disabled={busy}
              title="Komutu düzenle"
              aria-label={`${item.name} komutunu düzenle`}
              onClick={() => {
                setEditingId(item.id);
                setName(item.name);
                setCommand(item.command);
                setEditing(true);
                setError("");
              }}
            >
              <PencilSimple size={16} aria-hidden="true" />
            </button>
            <button
              className="icon-button"
              disabled={busy}
              aria-label={`${item.name} komutunu sil`}
              onClick={() => void save(items.filter((v) => v.id !== item.id))}
            >
              <Trash size={16} aria-hidden="true" />
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
  const [appearance, setAppearance] = useState(currentPreferences().terminal);
  const [settings, setSettings] = useState(false);
  const [draft, setDraft] = useState(appearance);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const savingRef = useRef(false);
  const drag = useRef<{ x: number; width: number } | null>(null);
  const widthRef = useRef(appearance.commands_width);
  const persistAppearance = async (patch: Partial<TerminalAppearance>) => {
    if (savingRef.current) return false;
    savingRef.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    const next = { ...currentPreferences().terminal, ...patch };
    setAppearance(next);
    try {
      const saved = await api("/access/preferences/terminal", "PUT", next);
      applyPreferences(saved);
      setNotice("Terminal görünümü kaydedildi.");
      return true;
    } catch (e: any) {
      setAppearance(currentPreferences().terminal);
      setError(e.message);
      return false;
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };
  const boundedWidth = (value: number) =>
    Math.max(240, Math.min(560, Math.round(value)));
  const resizeCommands = (delta: number) => {
    if (savingRef.current) return;
    const width = boundedWidth(appearance.commands_width + delta);
    if (width === appearance.commands_width) return;
    void persistAppearance({
      commands_width: width,
    });
  };
  const send = useRef<((data: string) => void) | null>(null);
  useEffect(() => {
    const handler = (e: Event) => {
      setFeatures((e as CustomEvent).detail.features);
      setAppearance((e as CustomEvent).detail.terminal);
    };
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
          <button
            className="icon-button"
            aria-label="Terminal görünümü"
            title="Terminal görünümü"
            aria-expanded={settings}
            aria-controls={`ssh-appearance-${session.id}`}
            onClick={() => {
              setDraft(appearance);
              setSettings((v) => !v);
              setNotice("");
            }}
          >
            <TextAa size={20} aria-hidden="true" />
          </button>
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
      {settings && (
        <form
          className="ssh-appearance-panel"
          id={`ssh-appearance-${session.id}`}
          aria-label="Terminal görünüm ayarları"
          onSubmit={async (event) => {
            event.preventDefault();
            if (
              await persistAppearance({
                font: draft.font,
                font_size: draft.font_size,
                font_weight: draft.font_weight,
                background: draft.background,
              })
            )
              setSettings(false);
          }}
        >
          <div className="ssh-appearance-fields">
            <label>
              Yazı tipi
              <select
                aria-label="Yazı tipi"
                name="terminal-font"
                value={draft.font}
                disabled={saving}
                onChange={(e) =>
                  setDraft((v) => ({
                    ...v,
                    font: e.target.value as TerminalAppearance["font"],
                  }))
                }
              >
                <option value="ubuntu">Ubuntu Mono</option>
                <option value="plex">IBM Plex Mono</option>
                <option value="system">Sistem Monospace</option>
              </select>
            </label>
            <label>
              Yazı kalınlığı
              <select
                aria-label="Yazı kalınlığı"
                name="terminal-weight"
                value={draft.font_weight}
                disabled={saving}
                onChange={(e) =>
                  setDraft((v) => ({
                    ...v,
                    font_weight: Number(e.target.value) as 400 | 700,
                  }))
                }
              >
                <option value={400}>Normal (ince)</option>
                <option value={700}>Kalın</option>
              </select>
            </label>
            <label>
              Yazı boyutu
              <select
                aria-label="Yazı boyutu"
                name="terminal-size"
                value={draft.font_size}
                disabled={saving}
                onChange={(e) =>
                  setDraft((v) => ({ ...v, font_size: Number(e.target.value) }))
                }
              >
                {Array.from({ length: 19 }, (_, i) => i + 10).map((size) => (
                  <option key={size} value={size}>
                    {size} px
                  </option>
                ))}
              </select>
            </label>
            <label>
              Arka plan rengi
              <input
                name="terminal-background"
                type="color"
                value={draft.background}
                disabled={saving}
                onChange={(e) =>
                  setDraft((v) => ({ ...v, background: e.target.value }))
                }
              />
            </label>
          </div>
          <div className="ssh-appearance-actions">
            <span>Değişiklikleri terminalde canlı önizleyin.</span>
            <button
              type="button"
              className="secondary"
              disabled={saving}
              onClick={() =>
                setDraft({ ...draft, ...defaultTerminalAppearance })
              }
            >
              Ubuntu varsayılanı
            </button>
            <button
              type="button"
              className="secondary"
              disabled={saving}
              onClick={() => setSettings(false)}
            >
              Vazgeç
            </button>
            <button className="primary" disabled={saving}>
              {saving ? "Kaydediliyor…" : "Görünümü kaydet"}
            </button>
          </div>
        </form>
      )}
      {error && (
        <p className="ssh-error" role="alert">
          {error}
        </p>
      )}
      <div
        className={`ssh-body${features.includes("saved_commands") ? " with-commands" : ""}${appearance.commands_collapsed ? " commands-collapsed" : ""}`}
        style={
          {
            "--ssh-commands-width": `${appearance.commands_width}px`,
          } as React.CSSProperties
        }
      >
        <Terminal
          id={session.id}
          appearance={settings ? draft : appearance}
          hidden={session.minimized}
          sendRef={send}
          onStatus={(state, message) => {
            setStatus(state);
            setError(message || "");
          }}
        />
        {features.includes("saved_commands") && (
          <>
            <div
              className="ssh-command-separator"
              role="separator"
              aria-label="Hazır komut panelinin genişliği"
              aria-orientation="vertical"
              aria-valuemin={240}
              aria-valuemax={560}
              aria-valuenow={appearance.commands_width}
              tabIndex={appearance.commands_collapsed ? -1 : 0}
              onKeyDown={(e) => {
                if (
                  ["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)
                ) {
                  e.preventDefault();
                  resizeCommands(
                    e.key === "Home"
                      ? 240 - appearance.commands_width
                      : e.key === "End"
                        ? 560 - appearance.commands_width
                        : e.key === "ArrowLeft"
                          ? 20
                          : -20,
                  );
                }
              }}
              onPointerDown={(e) => {
                if (savingRef.current || e.button !== 0) return;
                e.preventDefault();
                const panel = e.currentTarget.nextElementSibling as HTMLElement;
                drag.current = {
                  x: e.clientX,
                  width: panel.getBoundingClientRect().width,
                };
                widthRef.current = appearance.commands_width;
                e.currentTarget.setPointerCapture(e.pointerId);
              }}
              onPointerMove={(e) => {
                if (!drag.current) return;
                widthRef.current = boundedWidth(
                  drag.current.width + drag.current.x - e.clientX,
                );
                setAppearance((v) => ({
                  ...v,
                  commands_width: widthRef.current,
                }));
              }}
              onPointerUp={(e) => {
                if (!drag.current) return;
                drag.current = null;
                e.currentTarget.releasePointerCapture(e.pointerId);
                if (
                  widthRef.current !==
                  currentPreferences().terminal.commands_width
                )
                  void persistAppearance({ commands_width: widthRef.current });
              }}
              onPointerCancel={() => {
                drag.current = null;
                setAppearance(currentPreferences().terminal);
              }}
              onLostPointerCapture={() => {
                if (drag.current) {
                  drag.current = null;
                  setAppearance(currentPreferences().terminal);
                }
              }}
            />
            <div
              className="ssh-command-panel"
              hidden={appearance.commands_collapsed}
            >
              <SavedCommands
                enabled={status === "connected"}
                send={(value) => send.current?.(value)}
                onCollapse={() =>
                  void persistAppearance({ commands_collapsed: true })
                }
                onResize={resizeCommands}
              />
            </div>
            {appearance.commands_collapsed && (
              <div className="ssh-command-rail">
                <button
                  className="icon-button"
                  aria-label="Hazır komutları göster"
                  title="Hazır komutları göster"
                  disabled={saving}
                  onClick={() =>
                    void persistAppearance({ commands_collapsed: false })
                  }
                >
                  <CaretLeft size={20} aria-hidden="true" />
                </button>
              </div>
            )}
          </>
        )}
      </div>
      <footer className="ssh-footer">
        <span role="status">{notice || "SSH · Şifreli bağlantı"}</span>
        <span>
          {session.idle_timeout_minutes ?? 15} dk hareketsizlikte kapanır
        </span>
      </footer>
    </dialog>
  );
}

type BatchWindowState = {
  key: string;
  devices: Row[];
  minimized: boolean;
  id?: string;
  draftId?: string;
  command?: string;
  timeout?: number;
};

function BulkCommand({
  windowState,
  standalone,
  onClose,
  onMinimize,
  onDetached,
}: {
  windowState: BatchWindowState;
  standalone: boolean;
  onClose: () => void;
  onMinimize: () => void;
  onDetached: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [full, setFull] = useState(standalone);
  const [command, setCommand] = useState(windowState.command || "");
  const [timeout, setTimeoutValue] = useState(windowState.timeout || 30);
  const [id, setId] = useState(windowState.id || "");
  const [data, setData] = useState<Row>({
    status: windowState.id ? "queued" : "draft",
    targets: windowState.devices.map((d) => ({
      device_id: d.id,
      name: d.name,
      management_ip: d.management_ip,
      status: "queued",
      output: "",
    })),
  });
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<string>(
    windowState.devices[0]?.id || "",
  );
  const [savedVisible, setSavedVisible] = useState(
    currentPreferences().features.includes("saved_commands"),
  );
  const [commandsWidth, setCommandsWidth] = useState(
    currentPreferences().terminal.commands_width,
  );
  const transferred = useRef(false);
  const draftDiscarded = useRef(false);
  const running = ["queued", "running"].includes(data.status);
  const activeBatch = useRef({ id, running });
  activeBatch.current = { id, running };
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    if (windowState.minimized) dialog.current?.close();
    else if (!dialog.current?.open) dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      previous?.focus();
    };
  }, [windowState.minimized]);
  useEffect(() => {
    const release = () => {
      if (transferred.current) return;
      const value = activeBatch.current;
      const paths = [];
      if (value.id && value.running)
        paths.push(`/api/v1/access/batches/${value.id}`);
      if (windowState.draftId && !draftDiscarded.current)
        paths.push(`/api/v1/access/batch-drafts/${windowState.draftId}`);
      for (const path of paths)
        void fetch(path, {
          method: "DELETE",
          credentials: "same-origin",
          keepalive: true,
          headers: { "X-Netrix-Request": "1" },
        });
    };
    window.addEventListener("pagehide", release);
    return () => {
      window.removeEventListener("pagehide", release);
      release();
    };
  }, []);
  useEffect(() => {
    if (!id) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await api("/access/batches/" + id);
        if (!stopped) {
          setData(value);
          setActive(
            (previous) => previous || value.targets[0]?.device_id || "",
          );
          setError("");
          if (["queued", "running"].includes(value.status))
            timer = setTimeout(
              poll,
              windowState.minimized || document.hidden ? 1500 : 700,
            );
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
  }, [id, windowState.minimized, refresh]);
  const start = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api("/access/batches", "POST", {
        device_ids: data.targets.map((d: Row) => d.device_id),
        command,
        timeout,
      });
      setData((v) => ({
        ...v,
        status: result.status,
        error: "",
        targets: v.targets.map((t: Row) => ({
          ...t,
          status: "queued",
          output: "",
          error: "",
        })),
      }));
      setId(result.id);
      if (standalone) history.replaceState(null, "", `/batch/${result.id}`);
      if (windowState.draftId && !draftDiscarded.current) {
        draftDiscarded.current = true;
        void api(`/access/batch-drafts/${windowState.draftId}`, "DELETE").catch(
          () => {},
        );
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const detach = async () => {
    const next = window.open("about:blank", "_blank");
    if (!next) {
      setError(
        "Tarayıcı yeni sekmeyi engelledi. Bu site için açılır pencerelere izin verin.",
      );
      return;
    }
    next.opener = null;
    setBusy(true);
    setError("");
    let draftId = "";
    try {
      let url = `/batch/${id}`;
      if (!id) {
        const draft = await api("/access/batch-drafts", "POST", {
          device_ids: data.targets.map((d: Row) => d.device_id),
          command,
          timeout,
        });
        draftId = draft.id;
        url = `/batch/draft/${draft.id}`;
      }
      if (next.closed)
        throw new Error("Yeni sekme kapatıldı; mevcut pencere korunuyor.");
      next.location.href = url;
      transferred.current = true;
      onDetached();
    } catch (e: any) {
      next.close();
      setError(e.message);
      if (draftId)
        void api(`/access/batch-drafts/${draftId}`, "DELETE").catch(() => {});
    } finally {
      setBusy(false);
    }
  };
  const target = data.targets.find((t: Row) => t.device_id === active);
  const phases: Record<string, string> = {
    connection: "SSH bağlantısı",
    greeting: "Karşılama ekranı",
    preparation: "Oturum hazırlığı",
    initial_command: "Başlangıç komutu",
    command: "Komut yanıtı",
    authorization: "Yetki kontrolü",
  };
  return (
    <dialog
      ref={dialog}
      className={`ssh-dialog ssh-batch-dialog${full ? " ssh-full" : ""}`}
      aria-label="Toplu komut gönder"
      onCancel={(event) => {
        event.preventDefault();
        onMinimize();
      }}
    >
      <header className="ssh-header">
        <div className="ssh-heading">
          <TerminalWindow size={22} aria-hidden="true" />
          <div>
            <h2>Toplu komut gönder</h2>
            <span className="mono">{data.targets.length} cihaz seçili</span>
          </div>
        </div>
        <span className={`ssh-state state-${data.status}`} role="status">
          {data.status === "draft"
            ? "Komut hazırlanıyor"
            : states[data.status] || data.status}
        </span>
        <div className="ssh-window-actions">
          <button
            className="icon-button"
            aria-label={
              savedVisible
                ? "Toplu komut hazır komutlarını gizle"
                : "Toplu komut hazır komutlarını göster"
            }
            title="Hazır komutlar"
            aria-expanded={savedVisible}
            onClick={() => setSavedVisible((v) => !v)}
          >
            <ListBullets size={19} aria-hidden="true" />
          </button>
          <button
            className="icon-button"
            aria-label="Toplu komutu simge durumuna küçült"
            title="Simge durumuna küçült"
            onClick={onMinimize}
          >
            <Minus size={19} aria-hidden="true" />
          </button>
          {!standalone && (
            <button
              className="icon-button"
              aria-label="Toplu komutu yeni sekmede aç"
              title="Yeni sekmede aç"
              disabled={busy}
              onClick={() => void detach()}
            >
              <ArrowSquareOut size={19} aria-hidden="true" />
            </button>
          )}
          <button
            className="icon-button"
            aria-label={
              full
                ? "Toplu komut penceresini küçült"
                : "Toplu komutu tam ekran yap"
            }
            title={full ? "Pencereyi küçült" : "Tam ekran"}
            onClick={() => setFull((v) => !v)}
          >
            {full ? (
              <ArrowsIn size={19} aria-hidden="true" />
            ) : (
              <ArrowsOut size={19} aria-hidden="true" />
            )}
          </button>
          <button
            className="icon-button"
            aria-label="Toplu komut penceresini kapat"
            title={running ? "İşlemi iptal et ve kapat" : "Pencereyi kapat"}
            onClick={onClose}
          >
            <X size={19} aria-hidden="true" />
          </button>
        </div>
      </header>
      <div
        className={`ssh-batch-body${savedVisible ? " with-commands" : ""}`}
        style={
          {
            "--ssh-commands-width": `${commandsWidth}px`,
          } as React.CSSProperties
        }
      >
        <div className="ssh-batch">
          <p className="batch-guidance">
            Aynı anda en fazla dört bağlantı · Her cihaz kendi grubunun SSH
            hesabını kullanır.
          </p>
          <form onSubmit={start}>
            <label>
              Gönderilecek komut
              <textarea
                aria-label="Gönderilecek komut"
                name="batch-command"
                autoComplete="off"
                spellCheck={false}
                required
                rows={3}
                maxLength={4000}
                value={command}
                disabled={!!id || busy}
                onChange={(e) => setCommand(e.target.value)}
                placeholder={
                  id
                    ? "Bu sekme mevcut işlemin sonuçlarını izliyor."
                    : "Örnek: show version"
                }
              />
            </label>
            <div className="batch-submit">
              <label>
                Cihaz başına süre (saniye)
                <input
                  name="batch-timeout"
                  type="number"
                  min={5}
                  max={120}
                  required
                  value={timeout}
                  disabled={!!id || busy}
                  onChange={(e) => setTimeoutValue(Number(e.target.value))}
                />
              </label>
              {!id ? (
                <button
                  className="primary"
                  disabled={
                    busy || !data.targets.length || data.targets.length > 100
                  }
                >
                  <Play size={18} aria-hidden="true" />
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
                  <Stop size={18} aria-hidden="true" />
                  İptal et
                </button>
              ) : (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setId("");
                    setData((v) => ({
                      ...v,
                      status: "draft",
                      error: "",
                      targets: v.targets.map((t: Row) => ({
                        ...t,
                        status: "queued",
                        output: "",
                        error: "",
                      })),
                    }));
                    setError("");
                  }}
                >
                  <Plus size={18} aria-hidden="true" />
                  Yeni komut hazırla
                </button>
              )}
            </div>
          </form>
          {(error || data.error) && (
            <div className="ssh-error batch-error" role="alert">
              {error || data.error}
              {id && (
                <button
                  className="text-button"
                  onClick={() => setRefresh((value) => value + 1)}
                >
                  Sonucu yenile
                </button>
              )}
            </div>
          )}
          <div className="batch-summary" role="status">
            <span>
              <i className="status-dot state-succeeded" />
              {
                data.targets.filter((t: Row) => t.status === "succeeded").length
              }{" "}
              başarılı
            </span>
            <span>
              {
                data.targets.filter((t: Row) =>
                  ["failed", "cancelled"].includes(t.status),
                ).length
              }{" "}
              başarısız / iptal
            </span>
            <span>
              {
                data.targets.filter((t: Row) =>
                  ["queued", "running"].includes(t.status),
                ).length
              }{" "}
              {id ? "bekleyen" : "hazır"}
            </span>
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
                    {id ? states[t.status] : "Hazır"}
                  </span>
                </button>
              ))}
            </nav>
            <section aria-label="Seçili cihazın komut sonucu">
              <div className="batch-result-heading">
                <h3>{target?.name || "Cihaz seçin"}</h3>
                {target?.phase && <span>{phases[target.phase] || "SSH"}</span>}
              </div>
              <pre tabIndex={0} aria-label="Cihaz komut çıktısı">
                {target?.output ||
                  (target?.status === "succeeded"
                    ? "Komut tamamlandı; cihaz metin çıktısı döndürmedi."
                    : id
                      ? "Cihazdan yanıt bekleniyor…"
                      : "Komut gönderildiğinde cihaz çıktısı burada görünür.")}
              </pre>
            </section>
          </div>
        </div>
        {savedVisible && (
          <aside className="batch-saved-commands">
            <p>Hazır komutu seçin, kontrol edip gönderin.</p>
            <SavedCommands
              selectOnly
              enabled={!id && !busy}
              send={setCommand}
              onCollapse={() => setSavedVisible(false)}
              onResize={(delta) =>
                setCommandsWidth((v) => Math.max(240, Math.min(560, v + delta)))
              }
            />
          </aside>
        )}
      </div>
      <footer className="ssh-footer">
        <span>Sonuçlar 10 dakika tutulur · Otomatik tekrar yapılmaz.</span>
        <span>Küçültme ve sekme aktarımı işlemi sürdürür.</span>
      </footer>
    </dialog>
  );
}

export function SSHWorkspace({
  standaloneId,
  standaloneBatchId,
  standaloneDraftId,
}: {
  standaloneId?: string;
  standaloneBatchId?: string;
  standaloneDraftId?: string;
}) {
  const standalone = !!(standaloneId || standaloneBatchId || standaloneDraftId);
  const [sessions, setSessions] = useState<Session[]>([]);
  const sessionRef = useRef(sessions);
  sessionRef.current = sessions;
  const [batch, setBatch] = useState<BatchWindowState | null>(null);
  const batchRef = useRef(batch);
  batchRef.current = batch;
  const minimizedCount =
    sessions.filter((s) => s.minimized).length + (batch?.minimized ? 1 : 0);
  const [error, setError] = useState("");
  const pending = useRef(false);
  useEffect(() => {
    if (standaloneBatchId || standaloneDraftId) {
      const draft = !!standaloneDraftId;
      const id = standaloneDraftId || standaloneBatchId;
      api((draft ? "/access/batch-drafts/" : "/access/batches/") + id)
        .then((value) =>
          setBatch({
            key: id!,
            minimized: false,
            devices: value.targets.map((t: Row) => ({ ...t, id: t.device_id })),
            ...(draft
              ? { draftId: id, command: value.command, timeout: value.timeout }
              : { id, timeout: value.timeout }),
          }),
        )
        .catch((e) => setError(e.message));
      return;
    }
    if (standaloneId) {
      api("/access/sessions/" + standaloneId)
        .then((value) => setSessions([{ ...value, minimized: false }]))
        .catch((e) => setError(e.message));
      return;
    }
    const open = async (event: Event) => {
      if (pending.current) return;
      if (sessionRef.current.length + (batchRef.current ? 1 : 0) >= 16) {
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
        setBatch((value) => (value ? { ...value, minimized: true } : null));
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
      if (sessionRef.current.length > 15) {
        setError(
          "Önce bir SSH oturumunu kapatın; en fazla 15 pencere küçültülebilir.",
        );
        return;
      }
      setSessions((v) => v.map((s) => ({ ...s, minimized: true })));
      setBatch((previous) =>
        previous
          ? { ...previous, minimized: false }
          : {
              key: crypto.randomUUID(),
              devices: (event as CustomEvent).detail,
              minimized: false,
            },
      );
    };
    window.addEventListener("netrix:ssh-open", open);
    window.addEventListener("netrix:ssh-batch", bulk);
    return () => {
      window.removeEventListener("netrix:ssh-open", open);
      window.removeEventListener("netrix:ssh-batch", bulk);
    };
  }, [standaloneId, standaloneBatchId, standaloneDraftId]);
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
    if (minimizedCount >= 15) {
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
      {standalone && (
        <main className="standalone-terminal">
          <h1>
            NETRIX ·{" "}
            {standaloneId ? "SSH çalışma alanı" : "Toplu komut çalışma alanı"}
          </h1>
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
      {!!minimizedCount && (
        <nav className="ssh-dock" aria-label="Küçültülmüş SSH oturumları">
          <span>{minimizedCount}/15</span>
          {batch?.minimized && (
            <div>
              <button
                aria-label="Toplu komut penceresini aç"
                onClick={() => {
                  setSessions((v) => v.map((s) => ({ ...s, minimized: true })));
                  setBatch((v) => (v ? { ...v, minimized: false } : null));
                }}
              >
                <ListBullets size={18} aria-hidden="true" />
                <span>Toplu komut · {batch.devices.length} cihaz</span>
              </button>
              <button
                aria-label="Küçültülmüş toplu komutu kapat"
                onClick={() => setBatch(null)}
              >
                <X size={15} aria-hidden="true" />
              </button>
            </div>
          )}
          {sessions
            .filter((s) => s.minimized)
            .map((session) => (
              <div key={session.id}>
                <button
                  title={session.management_ip}
                  aria-label={`${session.device_name} SSH oturumunu aç`}
                  onClick={() => {
                    setBatch((value) =>
                      value ? { ...value, minimized: true } : null,
                    );
                    setSessions((v) =>
                      v.map((s) => ({ ...s, minimized: s.id !== session.id })),
                    );
                  }}
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
      {batch && (
        <BulkCommand
          key={batch.key}
          windowState={batch}
          standalone={standalone}
          onClose={() => setBatch(null)}
          onDetached={() => setBatch(null)}
          onMinimize={() => {
            if (minimizedCount >= 15) {
              setError(
                "En fazla 15 pencere küçültülebilir. Önce bir pencereyi kapatın.",
              );
              return;
            }
            setBatch((value) => (value ? { ...value, minimized: true } : null));
          }}
        />
      )}
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
