import { useState } from "react";
import { api, Dialog } from "./main";

type Row = Record<string, any>;
export function LinkLabelEditor({
  row,
  onClose,
  onSaved,
}: {
  row: Row;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(row.remote_name || "");
  const [port, setPort] = useState(row.remote_port || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const save = async (restore = false) => {
    setBusy(true);
    setError("");
    try {
      await api(`/links/${row.id}/labels`, "PUT", {
        remote_name: restore
          ? null
          : name.trim() !== row.remote_name
            ? name.trim()
            : (row.manual_remote_name ?? null),
        remote_port: restore
          ? null
          : port.trim() !== row.remote_port
            ? port.trim()
            : (row.manual_remote_port ?? null),
      });
      onSaved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title="Komşuluk kaydını düzenle"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="link-label-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <p className="link-label-context">
          {row.device_name} · Yerel port: {row.interface_name || "Bilinmiyor"}
        </p>
        <p className="muted">
          Kaydettiğiniz alanlar sonraki keşiflerde korunur. Cihazdan gelen
          değerler ayrıca saklanır.
        </p>
        <label>
          Komşu
          <input
            name="remote_name"
            required
            maxLength={190}
            value={name}
            disabled={busy}
            onChange={(e) => setName(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label>
          <span id="remote-port-label">Uzak port</span>
          <input
            name="remote_port"
            maxLength={120}
            value={port}
            disabled={busy}
            onChange={(e) => setPort(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            aria-labelledby="remote-port-label"
            aria-describedby="remote-port-hint"
          />
          <small id="remote-port-hint" className="muted">
            Bilinmiyorsa boş bırakabilirsiniz.
          </small>
        </label>
        <details>
          <summary>Cihazdan gelen değerler</summary>
          <dl className="link-observed-values">
            <dt>Komşu</dt>
            <dd>
              {row.observed_remote_name || row.remote_name || "Bilinmiyor"}
            </dd>
            <dt>Uzak port</dt>
            <dd>
              {row.observed_remote_port ?? row.remote_port ?? "Bilinmiyor"}
            </dd>
          </dl>
        </details>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="dialog-footer">
          {row.has_manual_changes && (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => void save(true)}
            >
              Keşif değerlerini kullan
            </button>
          )}
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onClose}
          >
            Vazgeç
          </button>
          <button className="primary" disabled={busy || !name.trim()}>
            {busy ? "Kaydediliyor…" : "Kaydet"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
