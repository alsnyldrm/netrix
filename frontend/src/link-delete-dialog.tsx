import { useState } from "react";
import { api, Dialog } from "./main";

export function LinkDeleteDialog({
  row,
  onClose,
  onDeleted,
}: {
  row: Record<string, any>;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Dialog
      title="Komşuluk kaydını sil"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="link-delete-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api(`/links/${row.id}`, "DELETE");
            onDeleted();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <p>
          Bu komşuluk kaydı silinecek ve sonraki taramalarda yeniden eklenmesi
          engellenecek.
        </p>
        <dl className="link-delete-details">
          <dt>Kaynak cihaz</dt>
          <dd>{row.device_name}</dd>
          <dt>Yerel port</dt>
          <dd>{row.interface_name || "Bilinmiyor"}</dd>
          <dt>Komşu</dt>
          <dd>{row.remote_name}</dd>
          <dt>Uzak port</dt>
          <dd>{row.remote_port || "Bilinmiyor"}</dd>
        </dl>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-footer">
          <button
            className="secondary"
            type="button"
            disabled={busy}
            onClick={onClose}
          >
            Vazgeç
          </button>
          <button className="secondary delete-confirm" disabled={busy}>
            {busy ? "Siliniyor…" : "Sil ve engelle"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
