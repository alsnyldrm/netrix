import { useEffect, useState } from "react";
import { api, Badge, date, Dialog } from "./main";
import "./job-details.css";

type Row = Record<string, any>;
function duration(seconds: number | null) {
  if (seconds === null) return "Kaydedilmemiş";
  if (seconds < 1) return "1 saniyeden az";
  if (seconds < 60) return `${Math.ceil(seconds)} saniye`;
  return `${Math.floor(seconds / 60)} dakika ${Math.floor(seconds % 60)} saniye`;
}

export function JobDetails({
  job,
  onClose,
}: {
  job: Row;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<Row | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const result = await api(`/jobs/${job.id}/details`);
        if (!active) return;
        setDetail(result);
        setError("");
        if (["queued", "running"].includes(result.status))
          timer = setTimeout(load, 2000);
      } catch (e: any) {
        if (active) {
          setError(e.message);
          timer = setTimeout(load, 4000);
        }
      }
    };
    load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [job.id]);
  return (
    <Dialog title="Görev açıklaması" onClose={onClose}>
      <div className="job-details">
        <div className="job-details-heading">
          <div>
            <h3>{detail?.title || job.title}</h3>
            <p>{detail?.target_label || job.target_label}</p>
          </div>
          <Badge value={detail?.status || job.status} />
        </div>
        {error && (
          <p role="alert" className="error-note">
            {error}
          </p>
        )}
        {!detail && !error && <p role="status">Görev açıklaması yükleniyor…</p>}
        {detail && (
          <>
            <div className="job-explanation">
              {detail.paragraphs.map((text: string, index: number) => (
                <p key={index}>{text}</p>
              ))}
            </div>
            <dl className="job-timing">
              <div>
                <dt>Kuyruğa alınma</dt>
                <dd>{date(detail.created_at)}</dd>
              </div>
              <div>
                <dt>Çalışmaya başlama</dt>
                <dd>
                  {detail.started_at
                    ? date(detail.started_at)
                    : detail.status === "queued"
                      ? "Henüz başlamadı"
                      : "Kaydedilmemiş"}
                </dd>
              </div>
              <div>
                <dt>İlk kuyruk beklemesi</dt>
                <dd>{duration(detail.queue_seconds)}</dd>
              </div>
              <div>
                <dt>Toplam geçen süre</dt>
                <dd>{duration(detail.elapsed_seconds)}</dd>
              </div>
              <div>
                <dt>Deneme sayısı</dt>
                <dd>{detail.attempts}</dd>
              </div>
              <div>
                <dt>Başlatan</dt>
                <dd>{detail.requested_by}</dd>
              </div>
              {detail.finished_at && (
                <div>
                  <dt>Tamamlanma</dt>
                  <dd>{date(detail.finished_at)}</dd>
                </div>
              )}
            </dl>
          </>
        )}
      </div>
      <div className="dialog-footer">
        <button className="secondary" onClick={onClose}>
          Kapat
        </button>
      </div>
    </Dialog>
  );
}
