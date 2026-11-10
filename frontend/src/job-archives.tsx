import { useEffect, useState } from "react";
import { Archive, Clock, DownloadSimple, Trash } from "@phosphor-icons/react";
import { api, useLiveQuery } from "./data";
import { Dialog } from "./main";
import { formatDate } from "./preferences";
import "./job-archives.css";

type ArchiveRow = {
  id: string;
  filename: string;
  job_count: number;
  size_bytes: number;
  source: string;
  created_at: string;
};

export function ArchiveJobsButton({ onSaved }: { onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function archive() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api("/job-archives", "POST");
      setMessage(
        result.archived_jobs
          ? `${result.archived_jobs} görev ZIP arşivine taşındı.`
          : "Arşivlenecek sonuçlanmış görev yok.",
      );
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="job-archive-action">
      <button
        className="secondary"
        disabled={busy}
        onClick={() => void archive()}
      >
        <Archive size={18} aria-hidden="true" />
        {busy ? "Arşivleniyor…" : "Tümünü arşive gönder"}
      </button>
      {message && <span role="status">{message}</span>}
      {error && (
        <span className="error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function JobArchives({
  refresh,
  canWrite,
}: {
  refresh: number;
  canWrite: boolean;
}) {
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const { data, error, loading } = useLiveQuery<{
    items: ArchiveRow[];
    total: number;
  }>(`/job-archives?limit=50&offset=${offset}`, refresh + version);
  const rows = data?.items || [];
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    setSelected(new Set());
  }, [offset]);
  useEffect(() => {
    if (data)
      setSelected(
        (current) =>
          new Set(
            [...current].filter((id) =>
              data.items.some((row) => row.id === id),
            ),
          ),
      );
  }, [data]);
  useEffect(() => {
    if (offset && data && !data.items.length)
      setOffset(Math.max(0, offset - 50));
  }, [data, offset]);
  async function remove() {
    setBusy(true);
    setActionError("");
    try {
      const result = await api("/job-archives/delete", "POST", {
        ids: deleting,
      });
      setDeleting(null);
      setSelected(new Set());
      setVersion((v) => v + 1);
      setMessage(`${result.deleted} arşiv silindi.`);
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const allSelected =
    rows.length > 0 && rows.every((row) => selected.has(row.id));
  return (
    <>
      <div className="info-note job-archive-note">
        <Clock size={20} aria-hidden="true" />
        <p>
          Her gece 00:00’da (İstanbul) sonuçlanmış görevler ZIP olarak
          arşivlenir. Çalışan ve kuyruktaki görevler tamamlanana kadar görev
          merkezinde kalır.
        </p>
      </div>
      {(error || actionError) && (
        <p className="error" role="alert">
          {error || actionError}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <section
        className="panel table-panel job-archives-panel"
        aria-label="Görev arşivleri"
      >
        <div className="toolbar">
          <div className="table-title">
            <Archive size={19} aria-hidden="true" />
            <b>ZIP arşivleri</b>
            <span className="count-pill">{data?.total || 0}</span>
          </div>
          {canWrite && (
            <button
              className="secondary"
              disabled={!selected.size || busy}
              onClick={() => {
                setActionError("");
                setDeleting([...selected]);
              }}
            >
              <Trash size={18} aria-hidden="true" />
              Seçilenleri sil{selected.size ? ` (${selected.size})` : ""}
            </button>
          )}
        </div>
        {loading ? (
          <p className="empty">Arşivler yükleniyor…</p>
        ) : rows.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Görev ZIP kayıtları"
          >
            <table>
              <thead>
                <tr>
                  {canWrite && (
                    <th className="archive-select">
                      <input
                        type="checkbox"
                        aria-label="Bu sayfadaki tüm arşivleri seç"
                        checked={allSelected}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? new Set(rows.map((r) => r.id))
                              : new Set(),
                          )
                        }
                      />
                    </th>
                  )}
                  <th>Arşiv</th>
                  <th>Oluşturulma</th>
                  <th>Görev sayısı</th>
                  <th>Boyut</th>
                  <th>Kaynak</th>
                  <th className="archive-actions">İşlemler</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    {canWrite && (
                      <td className="archive-select">
                        <input
                          type="checkbox"
                          aria-label={`${row.filename} arşivini seç`}
                          checked={selected.has(row.id)}
                          onChange={(e) =>
                            setSelected((current) => {
                              const next = new Set(current);
                              if (e.target.checked) next.add(row.id);
                              else next.delete(row.id);
                              return next;
                            })
                          }
                        />
                      </td>
                    )}
                    <td>
                      <a
                        className="archive-download"
                        href={`/api/v1/job-archives/${row.id}/download`}
                        download={row.filename}
                      >
                        <Archive size={18} aria-hidden="true" />
                        <span>{row.filename}</span>
                      </a>
                    </td>
                    <td className="archive-nowrap">
                      {formatDate(row.created_at)}
                    </td>
                    <td>{row.job_count}</td>
                    <td className="archive-nowrap">
                      {(row.size_bytes / 1024).toLocaleString("tr-TR", {
                        maximumFractionDigits: 1,
                      })}{" "}
                      KB
                    </td>
                    <td>
                      {row.source === "scheduled" ? "Otomatik" : "Manuel"}
                    </td>
                    <td>
                      <div className="row-actions">
                        <a
                          className="icon-button"
                          aria-label={`${row.filename} indir`}
                          href={`/api/v1/job-archives/${row.id}/download`}
                          download={row.filename}
                        >
                          <DownloadSimple size={18} aria-hidden="true" />
                        </a>
                        {canWrite && (
                          <button
                            className="icon-button danger"
                            disabled={busy}
                            aria-label={`${row.filename} sil`}
                            onClick={() => {
                              setActionError("");
                              setDeleting([row.id]);
                            }}
                          >
                            <Trash size={18} aria-hidden="true" />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty">
            <Archive size={32} aria-hidden="true" />
            <h3>Henüz görev arşivi yok</h3>
            <p>
              Görev merkezindeki “Tümünü arşive gönder” düğmesini kullanın veya
              gece 00:00’daki otomatik arşivlemeyi bekleyin.
            </p>
          </div>
        )}
        {!!data?.total && (
          <div className="job-archive-footer">
            <span>
              {data.total} arşiv · Sayfa {Math.floor(offset / 50) + 1}
            </span>
            <div className="row-actions">
              <button
                className="secondary"
                disabled={!offset || loading}
                onClick={() => setOffset(offset - 50)}
              >
                Önceki
              </button>
              <button
                className="secondary"
                disabled={offset + 50 >= data.total || loading}
                onClick={() => setOffset(offset + 50)}
              >
                Sonraki
              </button>
            </div>
          </div>
        )}
      </section>
      {deleting && (
        <Dialog
          title="Görev arşivlerini sil"
          onClose={() => {
            if (!busy) setDeleting(null);
          }}
        >
          <div className="job-archive-confirm">
            <p>
              {deleting.length} ZIP arşivi kalıcı olarak silinecek. Bu işlem
              geri alınamaz.
            </p>
            {actionError && (
              <p className="error" role="alert">
                {actionError}
              </p>
            )}
            <div className="job-archive-confirm-actions">
              <button
                className="secondary"
                disabled={busy}
                onClick={() => setDeleting(null)}
              >
                Vazgeç
              </button>
              <button
                className="primary danger"
                disabled={busy}
                onClick={() => void remove()}
              >
                {busy ? "Siliniyor…" : "Arşivleri sil"}
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </>
  );
}
