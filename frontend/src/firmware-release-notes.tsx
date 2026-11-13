import React, { useId, useState } from "react";
import { DownloadSimple } from "@phosphor-icons/react";
import { api, clearReadCache, useLiveQuery } from "./data";

export function releaseFileError(file: File | null) {
  if (!file) return "";
  if (!/\.(pdf|docx|txt)$/i.test(file.name))
    return "PDF, DOCX veya TXT belgesi seçin.";
  if (!file.size) return "Release belgesi boş olamaz.";
  if (file.size > 20 * 1024 * 1024)
    return "Release belgesi en fazla 20 MB olabilir.";
  return "";
}

function documentPath(id: string) {
  return `/api/v1/firmware/images/${id}/release-notes/content`;
}

export async function uploadReleaseDocument(id: string, file: File) {
  const error = releaseFileError(file);
  if (error) throw new Error(error);
  let response: Response;
  try {
    response = await fetch(documentPath(id), {
      method: "PUT",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Netrix-Request": "1",
        "X-Netrix-Filename": encodeURIComponent(file.name),
      },
      body: file,
      signal: AbortSignal.timeout(125000),
    });
  } catch {
    throw new Error("Belge aktarımı tamamlanamadı. Yeniden deneyin.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Release belgesi yüklenemedi. Yeniden deneyin.",
    );
  }
  clearReadCache();
}

export function ReleaseDocumentField({
  disabled,
  onChange,
}: {
  disabled: boolean;
  onChange: (file: File | null) => void;
}) {
  const id = useId();
  const [error, setError] = useState("");
  return (
    <div className="fw-full fw-release-notes-field">
      <label htmlFor={id}>Release belgesi (isteğe bağlı)</label>
      <input
        id={id}
        name="release_document"
        type="file"
        accept=".pdf,.docx,.txt"
        aria-label="Release belgesi"
        aria-describedby={`${id}-hint${error ? ` ${id}-error` : ""}`}
        aria-invalid={!!error}
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0] || null;
          const message = releaseFileError(file);
          event.target.setCustomValidity(message);
          setError(message);
          onChange(file);
        }}
      />
      <small id={`${id}-hint`}>PDF, DOCX veya TXT · En fazla 20 MB.</small>
      {error && (
        <p id={`${id}-error`} className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

type ReleaseFile = { filename: string; size_bytes: number };

function ReleaseDocument({
  imageId,
  file,
  admin,
  onSaved,
}: {
  imageId: string;
  file: ReleaseFile | null;
  admin: boolean;
  onSaved: () => void;
}) {
  const [selected, setSelected] = useState<File | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [saved, setSaved] = useState(false);
  return (
    <section className="fw-release-document" aria-label="Belge eki">
      <h4>Belge eki</h4>
      {file ? (
        <a
          className="secondary fw-release-download"
          href={documentPath(imageId)}
          download
        >
          <DownloadSimple size={18} aria-hidden="true" />
          <span>
            {file.filename}
            <small>
              İndir · {Math.max(1, Math.ceil(file.size_bytes / 1024))} KB
            </small>
          </span>
        </a>
      ) : (
        <p className="muted">Belge yüklenmemiş.</p>
      )}
      {admin && (
        <form
          className="fw-release-notes-editor"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!selected || busy) return;
            const form = event.currentTarget;
            setBusy(true);
            setError("");
            setSaved(false);
            try {
              await uploadReleaseDocument(imageId, selected);
              form.reset();
              setSelected(null);
              setSaved(true);
              onSaved();
            } catch (e: any) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <ReleaseDocumentField
            disabled={busy}
            onChange={(next) => {
              setSelected(next);
              setError("");
              setSaved(false);
            }}
          />
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {saved && <p role="status">Release belgesi yüklendi.</p>}
          <div className="fw-row-actions">
            <button
              className="primary"
              disabled={!selected || !!releaseFileError(selected) || busy}
            >
              {busy
                ? "Yükleniyor…"
                : file
                  ? "Belgeyi değiştir"
                  : "Belgeyi yükle"}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}

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
  const result = useLiveQuery<{
    release_notes: string;
    release_file: ReleaseFile | null;
  }>(`/firmware/images/${imageId}`, refresh);
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
      {result.data && (
        <ReleaseDocument
          imageId={imageId}
          file={result.data.release_file}
          admin={admin}
          onSaved={onSaved}
        />
      )}
    </section>
  );
}
