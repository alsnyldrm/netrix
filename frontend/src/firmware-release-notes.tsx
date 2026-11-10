import React, { useId, useState } from "react";
import { api, useLiveQuery } from "./data";

export function ReleaseNotesField({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="fw-full fw-release-notes-field">
      <label htmlFor={id}>Release notları (isteğe bağlı)</label>
      <textarea
        id={id}
        name="release_notes"
        aria-label="Release notları"
        aria-describedby={`${id}-hint`}
        placeholder="Bu sürümdeki yenilikler, giderilen hatalar ve bilinen sorunlar…"
        rows={6}
        maxLength={50000}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      <small id={`${id}-hint`}>
        Üreticinin sürüm notlarını veya kendi açıklamalarınızı ekleyin. En fazla
        50.000 karakter.
      </small>
    </div>
  );
}

export default function FirmwareReleaseNotes({
  imageId,
  admin,
  refresh,
  onSaved,
}: {
  imageId: string;
  admin: boolean;
  refresh: number;
  onSaved: () => void;
}) {
  const result = useLiveQuery<{ release_notes: string }>(
    `/firmware/images/${imageId}`,
    refresh,
  );
  const [editing, setEditing] = useState(false),
    [value, setValue] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [saved, setSaved] = useState(false);
  return (
    <section className="fw-release-notes" aria-label="Release notları">
      <h3>Release notları</h3>
      {result.loading && <p role="status">Release notları okunuyor…</p>}
      {(error || result.error) && (
        <p className="error" role="alert">
          {error || result.error}
        </p>
      )}
      {saved && <p role="status">Release notları kaydedildi.</p>}
      {result.data && !editing && (
        <>
          <p className="fw-notes">
            {result.data.release_notes || "Release notu eklenmemiş."}
          </p>
          {admin && (
            <button
              className="secondary"
              onClick={() => {
                setValue(result.data!.release_notes);
                setSaved(false);
                setError("");
                setEditing(true);
              }}
            >
              Release notlarını düzenle
            </button>
          )}
        </>
      )}
      {editing && (
        <form
          className="fw-release-notes-editor"
          onSubmit={async (event) => {
            event.preventDefault();
            if (busy) return;
            setBusy(true);
            setError("");
            try {
              await api(`/firmware/images/${imageId}/release-notes`, "PATCH", {
                release_notes: value,
              });
              setEditing(false);
              setSaved(true);
              onSaved();
            } catch (e: any) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <ReleaseNotesField
            value={value}
            disabled={busy}
            onChange={setValue}
          />
          <div className="fw-row-actions">
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              Vazgeç
            </button>
            <button className="primary" disabled={busy}>
              {busy ? "Kaydediliyor…" : "Release notlarını kaydet"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
