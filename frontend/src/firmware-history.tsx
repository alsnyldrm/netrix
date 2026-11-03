import { useDeferredValue, useState } from "react";
import { CaretRight, TerminalWindow } from "@phosphor-icons/react";
import { useLiveQuery } from "./data";
import { Dialog } from "./main";

type Row = Record<string, any>;
const STATES: Row = {
  queued: "Sırada",
  running: "Çalışıyor",
  paused: "Müdahale bekliyor",
  ready: "Etkinleştirmeye hazır",
  succeeded: "Doğrulandı",
  cancelled: "Durduruldu",
  checked: "Ön kontrol tamam",
  staged: "İmaj hazır",
  failed: "Başarısız",
  attention: "Sonuç belirsiz",
};
const MODES: Row = {
  check: "Yalnız ön kontrol",
  stage: "Aktar ve açılışa hazırla",
  upgrade: "Aktar ve yeniden başlat",
  activate: "Hazır imajı etkinleştir",
  verify: "Sonucu doğrula",
};
const PHASES: Row = {
  waiting: "Bekliyor",
  preflight: "Ön kontrol",
  backup: "Konfigürasyon yedeği",
  transferring: "Dosya aktarımı ve yazım",
  image_verifying: "Cihazın imajı doğrulanıyor",
  rebooting: "Yeniden başlatma",
  verifying: "Sürüm doğrulama",
  reconcile: "Sonucu yeniden doğrulama",
  recovered: "Manuel kurtarma",
  version_skipped: "Cihaz güncel; işlem atlandı",
};
const EVENT_STATES: Row = {
  info: "Bilgi",
  started: "Tamamlanma kaydı bekleniyor",
  succeeded: "Tamamlandı",
  failed: "Tamamlanamadı",
  sent: "Gönderildi; açılış ayrıca doğrulanır",
};
const timestamp = (v?: string) =>
  v
    ? new Intl.DateTimeFormat("tr-TR", {
        dateStyle: "medium",
        timeStyle: "medium",
        timeZone: "Europe/Istanbul",
      }).format(new Date(v))
    : "—";
const bytes = (n: number) => (n ? `${(n / 1024 ** 2).toFixed(1)} MB` : "0 MB");
function State({ value }: { value: string }) {
  return (
    <span className={`fw-state fw-state-${value}`}>
      {STATES[value] || value}
    </span>
  );
}
function Counts({ counts }: { counts: Row }) {
  return (
    <div className="fw-history-counts">
      {Object.entries(counts).map(([state, count]) => (
        <span key={state}>
          <b>{String(count)}</b> {STATES[state] || state}
        </span>
      ))}
    </div>
  );
}
function Pager({
  offset,
  total,
  size,
  onChange,
}: {
  offset: number;
  total: number;
  size: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="fw-pager">
      <span>
        {total} kayıt · {total ? offset + 1 : 0}–
        {Math.min(offset + size, total)}
      </span>
      <div>
        <button
          className="secondary"
          disabled={!offset}
          onClick={() => onChange(Math.max(0, offset - size))}
        >
          Önceki
        </button>
        <button
          className="secondary"
          disabled={offset + size >= total}
          onClick={() => onChange(offset + size)}
        >
          Sonraki
        </button>
      </div>
    </div>
  );
}
function QueryState({ result }: { result: Row }) {
  return (
    <>
      {result.error && (
        <p className="error" role="alert">
          {result.error}
        </p>
      )}
      {result.loading && !result.data && (
        <p role="status" className="fw-history-loading">
          Kayıtlar okunuyor…
        </p>
      )}
    </>
  );
}
function Event({ event }: { event: Row }) {
  const elapsed = event.finished_at
    ? Math.max(
        0,
        (new Date(event.finished_at).getTime() -
          new Date(event.created_at).getTime()) /
          1000,
      )
    : null;
  return (
    <li
      className={`fw-history-event fw-history-event-${event.status || "info"}`}
    >
      <div className="fw-history-event-heading">
        <div>
          <b>{event.title}</b>
          <small>
            {PHASES[event.phase] || "Kayıtlı işlem bilgisi"}
            {elapsed !== null ? ` · ${elapsed.toFixed(1)} sn` : ""}
          </small>
        </div>
        <time dateTime={event.created_at}>{timestamp(event.created_at)}</time>
      </div>
      {event.status && (
        <span className="fw-history-event-state">
          {EVENT_STATES[event.status]}
        </span>
      )}
      {event.command && (
        <div className="fw-history-command">
          <span>
            <TerminalWindow size={16} aria-hidden="true" /> Cihaza gönderilen
            komut
          </span>
          <pre>{event.command}</pre>
        </div>
      )}
      {event.kind === "command" ? (
        <details className="fw-history-output">
          <summary>
            Cihaz yanıtı{event.response ? "" : " · yanıt kaydı yok"}
          </summary>
          <pre>
            {event.response ||
              "Bu komut için cihaz yanıtı kaydedilmemiş veya henüz tamamlanmamış."}
          </pre>
        </details>
      ) : (
        event.response && <p className="fw-history-note">{event.response}</p>
      )}
      {event.truncated && (
        <p className="fw-history-warning">
          Uzun çıktı kısaltıldı; tamamı saklanmadı.
        </p>
      )}
    </li>
  );
}
function Transcript({ id, refresh }: { id: string; refresh: number }) {
  const [offset, setOffset] = useState(0);
  const result = useLiveQuery<Row>(
    `/firmware/history/targets/${id}?offset=${offset}`,
    refresh,
  );
  const data = result.data,
    t = data?.target;
  return (
    <div className="fw-history-transcript">
      <QueryState result={result} />
      {data && (
        <>
          <dl className="fw-history-metadata">
            <div>
              <dt>Önceki → doğrulanan sürüm</dt>
              <dd>
                {t.previous_version || "Okunmamış"} →{" "}
                {t.verified_version || "Henüz doğrulanmadı"}
              </dd>
            </div>
            <div>
              <dt>Dosya / hedef sürüm</dt>
              <dd>
                {data.image.original_name} · {data.image.version}
              </dd>
            </div>
            <div>
              <dt>Aktarım / yazılım alanı</dt>
              <dd>
                {t.evidence.protocol?.toUpperCase() || "Yöntem kaydedilmemiş"} ·{" "}
                {t.previous_bank || "—"} →{" "}
                {t.bank === "auto" ? "Seçilmemiş" : t.bank}
              </dd>
            </div>
            <div>
              <dt>Dosya boyutu / aktarılan</dt>
              <dd>
                {bytes(data.image.size_bytes)} / {bytes(t.transfer_bytes)}
                {t.evidence.transfer_reused ? " · Mevcut imaj kullanıldı" : ""}
              </dd>
            </div>
            {t.evidence.image_verification_percent != null && (
              <div className="fw-history-metadata-wide">
                <dt>Cihazın imaj doğrulaması</dt>
                <dd>
                  {t.evidence.staged && t.evidence.staged_sha256
                    ? "SHA-256 eşleşti; imaj hazır."
                    : `SHA-256 doğrulaması: %${t.evidence.image_verification_percent}`}
                </dd>
              </div>
            )}
            <div className="fw-history-metadata-wide">
              <dt>SHA-256</dt>
              <dd className="mono">{data.image.sha256 || "Kaydedilmemiş"}</dd>
            </div>
            <div className="fw-history-metadata-wide">
              <dt>Konfigürasyon yedeği</dt>
              <dd>
                {t.snapshot_id
                  ? `Şifreli yedek korunuyor · ${t.snapshot_id}`
                  : "Bu işlemde yedek kaydı bulunmuyor"}
              </dd>
            </div>
          </dl>
          {t.error && <p className="fw-history-failure">{t.error}</p>}
          {data.legacy && (
            <p className="fw-history-warning">
              Bu eski işlemde ayrıntılı komut ve cihaz yanıtı kaydı tutulmamış.
              Aşağıdaki akış yalnız saklanmış zaman ve sonuç bilgilerini
              gösterir.
            </p>
          )}
          {!data.items.length && (
            <p className="fw-history-guide">
              Bu cihaz için henüz işlem adımı kaydedilmedi; komut gönderimi
              bekleniyor.
            </p>
          )}
          <ol
            className="fw-history-timeline"
            aria-label="Cihaz işlem adımları"
            style={{ counterReset: `firmware-event ${offset}` }}
          >
            {data.items.map((event: Row) => (
              <Event key={event.id} event={event} />
            ))}
          </ol>
          {data.total > 40 && (
            <Pager
              offset={offset}
              total={data.total}
              size={40}
              onChange={setOffset}
            />
          )}
        </>
      )}
    </div>
  );
}
function Device({ target, refresh }: { target: Row; refresh: number }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="fw-history-device"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <CaretRight className="fw-history-caret" size={18} aria-hidden="true" />
        <span className="fw-history-name">
          <b>{target.evidence.device_name}</b>
          <small>
            {target.evidence.management_ip} ·{" "}
            {PHASES[target.phase] || target.phase}
          </small>
        </span>
        {target.evidence.skipped_current ? (
          <span className="fw-state fw-state-succeeded">Güncel; atlandı</span>
        ) : (
          <State value={target.status} />
        )}
      </summary>
      {open && <Transcript id={target.id} refresh={refresh} />}
    </details>
  );
}
function Group({
  group,
  planId,
  refresh,
}: {
  group: Row;
  planId: string;
  refresh: number;
}) {
  const [open, setOpen] = useState(false),
    [offset, setOffset] = useState(0);
  const result = useLiveQuery<Row>(
    open
      ? `/firmware/history/${planId}/targets?stage=${group.stage}&offset=${offset}`
      : null,
    refresh,
  );
  return (
    <details
      className="fw-history-group"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        <CaretRight className="fw-history-caret" size={18} aria-hidden="true" />
        <span className="fw-history-name">
          <b>
            {group.stage + 1}. {group.group_name}
          </b>
          <small>
            Hedef: {group.version} · {group.count} cihaz
          </small>
        </span>
        <Counts counts={group.counts} />
      </summary>
      {open && (
        <div className="fw-history-devices">
          <QueryState result={result} />
          {result.data?.items.map((target: Row) => (
            <Device key={target.id} target={target} refresh={refresh} />
          ))}
          {result.data && !result.data.items.length && (
            <p>Cihaz kaydı bulunamadı.</p>
          )}
          {result.data && result.data.total > 30 && (
            <Pager
              offset={offset}
              total={result.data.total}
              size={30}
              onChange={setOffset}
            />
          )}
        </div>
      )}
    </details>
  );
}
function Operation({
  id,
  refresh,
  onClose,
}: {
  id: string;
  refresh: number;
  onClose: () => void;
}) {
  const result = useLiveQuery<Row>(`/firmware/history/${id}`, refresh),
    plan = result.data;
  return (
    <Dialog title={plan?.name || "İşlem ayrıntısı"} wide onClose={onClose}>
      <div className="fw-history-detail">
        <QueryState result={result} />
        {plan && (
          <>
            <div className="fw-history-operation-meta">
              <State value={plan.status} />
              <span>{MODES[plan.mode]}</span>
              <span>Oluşturulma: {timestamp(plan.created_at)}</span>
              <span>Bitiş: {timestamp(plan.finished_at)}</span>
            </div>
            <p className="fw-history-guide">
              Grubu, ardından cihazı açarak işlem adımlarını ve cihaz
              yanıtlarını inceleyin. Saatler Türkiye saatidir.
            </p>
            <div className="fw-history-groups">
              {plan.groups.map((group: Row) => (
                <Group
                  key={group.stage}
                  group={group}
                  planId={id}
                  refresh={refresh}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </Dialog>
  );
}
export default function FirmwareHistory({ refresh }: { refresh: number }) {
  const [q, setQ] = useState(""),
    [status, setStatus] = useState(""),
    [mode, setMode] = useState(""),
    [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<string | null>(null);
  const query = useDeferredValue(q);
  const result = useLiveQuery<Row>(
    `/firmware/history?q=${encodeURIComponent(query)}&status=${status}&mode=${mode}&offset=${offset}`,
    refresh,
    undefined,
    150,
  );
  return (
    <section
      className="fw-workspace fw-history fw-panel"
      aria-label="İşlem geçmişi"
    >
      <div className="fw-toolbar">
        <div>
          <h2>İşlem geçmişi</h2>
          <p>
            İşlem → grup → cihaz → komut ve yanıt. Her cihazın adımlarını zaman
            sırasıyla inceleyin.
          </p>
        </div>
      </div>
      <div className="fw-history-filters">
        <label>
          İşlem adı
          <input
            value={q}
            placeholder="İşlem adına göre ara…"
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <label>
          İşlem durumu
          <select
            aria-label="İşlem durumu"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Tüm durumlar</option>
            {[
              "queued",
              "running",
              "paused",
              "ready",
              "succeeded",
              "cancelled",
            ].map((s) => (
              <option key={s} value={s}>
                {STATES[s]}
              </option>
            ))}
          </select>
        </label>
        <label>
          İşlem türü
          <select
            aria-label="İşlem türü"
            value={mode}
            onChange={(e) => {
              setMode(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">Tüm işlemler</option>
            {Object.entries(MODES).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <QueryState result={result} />
      <div className="fw-history-operations">
        {result.data?.items.map((plan: Row) => (
          <article className="fw-history-operation" key={plan.id}>
            <div className="fw-history-operation-heading">
              <button
                className="fw-history-open"
                onClick={() => setSelected(plan.id)}
              >
                <span>{plan.name}</span>
                <CaretRight size={18} aria-hidden="true" />
              </button>
              <State value={plan.status} />
            </div>
            <div className="fw-history-operation-meta">
              <span>{MODES[plan.mode]}</span>
              <span>
                {plan.steps.length} grup ·{" "}
                {Object.values(plan.counts).reduce<number>(
                  (a, b) => a + Number(b),
                  0,
                )}{" "}
                cihaz
              </span>
              <time dateTime={plan.created_at}>
                {timestamp(plan.created_at)}
              </time>
            </div>
            <Counts counts={plan.counts} />
          </article>
        ))}
      </div>
      {result.data && !result.data.total && (
        <p className="fw-empty">
          Bu filtrelerle eşleşen işlem kaydı bulunmuyor.
        </p>
      )}
      {result.data && (
        <Pager
          offset={offset}
          total={result.data.total}
          size={20}
          onChange={setOffset}
        />
      )}
      {selected && (
        <Operation
          id={selected}
          refresh={refresh}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  );
}
