import { useEffect, useRef, useState } from "react";
import { ArrowLeft } from "@phosphor-icons/react";
import { api, Dialog, date } from "./main";
import { InventoryTable } from "./inventory";
type Row = Record<string, any>;
export function BackupWorkspace({
  page,
  refresh,
  user,
  onSaved,
}: {
  page: string;
  refresh: number;
  user: Row;
  onSaved: () => void;
}) {
  const [view, setView] = useState<Row | null>(null);
  const [job, setJob] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [device, setDevice] = useState<Row | null>(null);
  const deviceFirst = page === "configuration" || page === "backup-compare";
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [device?.id]);
  useEffect(() => {
    if (!job?.id) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const d = await api(`/backup-comparisons/${job.id}`);
        if (!active) return;
        setJob(d);
        setError("");
        if (["queued", "running"].includes(d.status))
          timer = setTimeout(poll, 1500);
      } catch (e: any) {
        if (active) {
          setError(e.message);
          timer = setTimeout(poll, 3000);
        }
      }
    };
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [job?.id]);
  const action = async (row: Row, kind: string) => {
    setError("");
    setJob(null);
    if (kind === "delete") {
      setView({ row, kind });
      return;
    }
    setBusy(true);
    try {
      if (kind === "compare") {
        setView({ row, kind });
        setJob(await api(`/snapshots/${row.id}/compare-live`, "POST"));
      } else {
        const d = await api(
          `/snapshots/${row.id}/${kind === "diff" ? "diff" : "content"}`,
        );
        const content =
          kind === "diff" && !d.previous_id
            ? "Önceki yedek bulunmuyor; karşılaştırma yapılamadı."
            : (d.content ?? d.diff);
        if (kind === "download") {
          const url = URL.createObjectURL(
            new Blob([content], { type: "text/plain;charset=utf-8" }),
          );
          const a = document.createElement("a");
          a.href = url;
          a.download = `netrix-${row.id}-masked.txt`;
          a.click();
          URL.revokeObjectURL(url);
        } else setView({ row, kind, content });
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const close = () => {
    setView(null);
    setJob(null);
  };
  const pending = job && ["queued", "running"].includes(job.status);
  return (
    <>
      {(page === "configuration" || page === "backup-compare") && (
        <div className="info-note">
          <p>
            Yedekler ve aktif config yalnızca SSH üzerinden okunur. FortiGate
            için SCP ile sys_config dosyası alınır; cihazda admin-scp açık ve
            SSH hesabı yedekleme yetkisine sahip olmalıdır. Eski, eksik kayıtlar
            yerine yeni bir yedek alın.
          </p>
        </div>
      )}
      {page === "backup-settings" && (
        <div className="info-note">
          <p>
            Grup atamak veya cihazın ayarlarını değiştirmek için cihazları seçip{" "}
            <b>Ayarları uygula</b> düğmesine basın. Gruba bağlı cihazlar,
            Gruplandırma ayarları ekranındaki zamanlama ve saklama sınırını
            kullanır. Saklama sınırı azaltılırsa eski yedekler silinir.
          </p>
        </div>
      )}
      {error && !view && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {busy && !view && <p role="status">Yedek okunuyor…</p>}
      {deviceFirst && device && (
        <div className="inventory-breadcrumb backup-device-heading">
          <button
            className="secondary"
            onClick={() => {
              setDevice(null);
              setError("");
            }}
          >
            <ArrowLeft size={18} aria-hidden="true" /> Cihazlara dön
          </button>
          <div>
            <h2 tabIndex={-1} ref={heading}>
              {device.name}
            </h2>
            <p>
              {device.management_ip} · {device.backup_group || "Grupsuz"}
            </p>
          </div>
        </div>
      )}
      {deviceFirst && !device ? (
        <InventoryTable
          key="backup-devices"
          resource="backup-devices"
          purpose="backup-devices"
          refresh={refresh}
          user={user}
          onSaved={onSaved}
          onDevice={setDevice}
        />
      ) : (
        <InventoryTable
          key={device?.id || page}
          deviceId={device?.id}
          resource={page === "backup-settings" ? "devices" : "snapshots"}
          purpose={
            page === "backup-changes"
              ? "changes"
              : page === "backup-compare"
                ? "compare"
                : page === "backup-settings"
                  ? "backup-settings"
                  : "snapshots"
          }
          refresh={refresh}
          user={user}
          onSaved={onSaved}
          onContent={action}
        />
      )}
      {view && (
        <Dialog
          title={
            view.kind === "delete"
              ? "Yedeği sil"
              : view.kind === "compare"
                ? "Aktif config karşılaştırması"
                : view.kind === "diff"
                  ? "Yedek değişiklikleri"
                  : "Cihaz yedeği"
          }
          onClose={close}
        >
          <div className="backup-result">
            <p>
              <b>{view.row.device_name}</b> · {date(view.row.created_at)}
            </p>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            {view.kind === "delete" ? (
              <>
                <p>Bu yedek kalıcı olarak silinecek.</p>
                <div className="dialog-footer">
                  <button className="secondary" onClick={close}>
                    Vazgeç
                  </button>
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await api(`/snapshots/${view.row.id}`, "DELETE");
                        onSaved();
                        close();
                      } catch (e: any) {
                        setError(e.message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Yedeği sil
                  </button>
                </div>
              </>
            ) : view.kind === "compare" ? (
              <>
                <p role="status">
                  {busy
                    ? "Sıraya alınıyor…"
                    : pending
                      ? "Cihazın aktif konfigürasyonu okunuyor…"
                      : job?.status === "succeeded"
                        ? job.result.changed
                          ? "Değişiklik bulundu."
                          : "Konfigürasyon aynı."
                        : job?.error || "Karşılaştırma tamamlanmadı."}
                </p>
                {job?.status === "succeeded" && (
                  <>
                    <p className="muted">
                      Okuma zamanı: {date(job.result.checked_at)}. Hassas
                      değerler maskelenir.
                    </p>
                    <pre>
                      {job.result.diff ||
                        (job.result.changed
                          ? "Değişiklik maskelenmiş alanlarda olabilir."
                          : "Fark yok.")}
                    </pre>
                  </>
                )}
                {pending && (
                  <button
                    className="secondary"
                    disabled={job.cancel_requested}
                    onClick={async () => {
                      try {
                        await api(`/jobs/${job.id}/cancel`, "POST");
                        setJob({ ...job, cancel_requested: true });
                      } catch (e: any) {
                        setError(e.message);
                      }
                    }}
                  >
                    Karşılaştırmayı iptal et
                  </button>
                )}
              </>
            ) : (
              <>
                <p className="muted">Hassas değerler maskelenir.</p>
                <pre>{view.content || "Görünür fark yok."}</pre>
              </>
            )}
          </div>
        </Dialog>
      )}
    </>
  );
}
