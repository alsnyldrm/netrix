import { useState } from "react";
import {
  CalendarBlank,
  Check,
  Clock,
  MagnifyingGlass,
  PencilSimple,
  Plus,
  Trash,
} from "@phosphor-icons/react";
import { api, useLiveQuery } from "./data";
import { Dialog } from "./main";
import "./ipam-settings.css";

type Row = Record<string, any>;
function ErrorNote({ error }: { error: string }) {
  return error ? (
    <div className="error" role="alert">
      {error}
    </div>
  ) : null;
}
const date = (v: string) =>
  new Date(v).toLocaleString("tr-TR", {
    timeZone: "Europe/Istanbul",
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
const frequencies: Record<string, string> = {
  daily: "Günlük",
  weekly: "Haftalık",
  monthly: "Aylık",
};
const units: Record<string, string> = {
  daily: "gün",
  weekly: "hafta",
  monthly: "ay",
};
const zone = "Europe/Istanbul";
const localTime = (iso: string) => {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(iso));
  const p = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
};
const utcTime = (local: string) => {
  const guess = Date.parse(local + "Z");
  const offset =
    Date.parse(localTime(new Date(guess).toISOString()) + "Z") - guess;
  return new Date(guess - offset).toISOString();
};
const vlanLabel = (v: Row) =>
  `VLAN-${v.vid} / ${v.name} | ${v.cidr || "IP bloğu yok"} · ${v.vrf || "—"}`;

function GroupForm({
  row,
  catalog,
  close,
  saved,
}: {
  row?: Row;
  catalog: Row;
  close: () => void;
  saved: () => void;
}) {
  const [values, setValues] = useState<Row>(() => ({
    name: row?.name || "",
    description: row?.description || "",
    enabled: row?.enabled ?? true,
    frequency: row?.frequency || "daily",
    repeat_every: row?.repeat_every || 1,
    start: localTime(
      row?.start_at || new Date(Date.now() + 3600000).toISOString(),
    ),
    run_limit: row?.run_limit || "",
    vlan_ids: row?.vlan_ids || [],
  }));
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const change = (k: string, v: any) => {
    setValues((s) => ({ ...s, [k]: v }));
    setError("");
  };
  const filtered = catalog.vlans.filter((v: Row) =>
    query
      .toLocaleLowerCase("tr")
      .split(/\s+/)
      .every((w) => vlanLabel(v).toLocaleLowerCase("tr").includes(w)),
  );
  const available = (v: Row) =>
    (!!v.cidr || values.vlan_ids.includes(v.id)) &&
    (!v.group_id || v.group_id === row?.id);
  const toggle = (id: string) =>
    change(
      "vlan_ids",
      values.vlan_ids.includes(id)
        ? values.vlan_ids.filter((v: string) => v !== id)
        : [...values.vlan_ids, id],
    );
  return (
    <Dialog
      title={row ? "Tarama grubunu düzenle" : "Yeni tarama grubu"}
      onClose={close}
      wide
    >
      <form
        className="scan-group-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          if (!values.vlan_ids.length) {
            setError("Gruba en az bir VLAN seçin.");
            return;
          }
          setBusy(true);
          try {
            const data: Row = {
              ...values,
              timezone: zone,
              start_at:
                row && values.start === localTime(row.start_at)
                  ? row.start_at
                  : utcTime(values.start),
              repeat_every: Number(values.repeat_every),
              run_limit: values.run_limit ? Number(values.run_limit) : null,
            };
            delete data.start;
            await api(
              "/ipam/scan-groups" + (row ? "/" + row.id : ""),
              row ? "PUT" : "POST",
              data,
            );
            saved();
            close();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <ErrorNote error={error} />
        <div className="scan-form-grid">
          <label>
            <span>
              Grup adı <span className="required">*</span>
            </span>
            <input
              required
              aria-label="Grup adı"
              maxLength={120}
              value={values.name}
              onChange={(e) => change("name", e.target.value)}
            />
          </label>
          <label>
            <span>Açıklama</span>
            <input
              maxLength={400}
              aria-label="Açıklama"
              value={values.description}
              onChange={(e) => change("description", e.target.value)}
            />
          </label>
          <label>
            <span>Tekrarlama</span>
            <select
              aria-label="Tekrarlama"
              value={values.frequency}
              onChange={(e) => change("frequency", e.target.value)}
            >
              {Object.entries(frequencies).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Tekrar aralığı</span>
            <input
              type="number"
              aria-label="Tekrar aralığı"
              min={1}
              max={365}
              required
              value={values.repeat_every}
              onChange={(e) => change("repeat_every", e.target.value)}
            />
            <small>
              Her {values.repeat_every || "—"}{" "}
              {
                (
                  {
                    daily: "günde",
                    weekly: "haftada",
                    monthly: "ayda",
                  } as Record<string, string>
                )[values.frequency]
              }{" "}
              bir çalışır.
            </small>
          </label>
          <label>
            <span>
              Başlangıç tarihi ve saati <span className="required">*</span>
            </span>
            <input
              type="datetime-local"
              aria-label="Başlangıç tarihi ve saati"
              required
              min="2000-01-01T00:00"
              max="2100-12-31T23:59"
              value={values.start}
              onChange={(e) => change("start", e.target.value)}
            />
            <small>Türkiye saati · {zone}</small>
          </label>
          <label>
            <span>Toplam çalışma sayısı</span>
            <input
              type="number"
              min={1}
              max={100000}
              aria-label="Toplam çalışma sayısı"
              placeholder="Sürekli"
              value={values.run_limit}
              onChange={(e) => change("run_limit", e.target.value)}
            />
            <small>Boş bırakırsanız durdurulana kadar tekrarlanır.</small>
          </label>
        </div>
        <p className="scan-note">
          {values.frequency === "monthly"
            ? "Başlangıç tarihinin günü kullanılır. O gün bulunmayan aylarda ayın son günü çalışır."
            : values.frequency === "weekly"
              ? "Başlangıç tarihinin haftanın günü ve saati kullanılır."
              : "Başlangıç saati her çalışma gününde korunur."}{" "}
          Zamanlama alanlarını değiştirmek çalışma sayacını sıfırlar.
        </p>
        <fieldset className="scan-vlans">
          <legend>
            Gruba eklenecek VLAN’lar{" "}
            <span className="scan-count">{values.vlan_ids.length} seçili</span>
          </legend>
          <div className="scan-vlan-tools">
            <label className="scan-search">
              <MagnifyingGlass size={18} aria-hidden="true" />
              <input
                type="search"
                aria-label="VLAN ara"
                placeholder="VLAN, ad, CIDR veya VRF ara…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="secondary"
              onClick={() =>
                change("vlan_ids", [
                  ...new Set([
                    ...values.vlan_ids,
                    ...filtered.filter(available).map((v: Row) => v.id),
                  ]),
                ])
              }
            >
              Aramadakileri seç
            </button>
            <button
              type="button"
              className="secondary"
              disabled={!values.vlan_ids.length}
              onClick={() => change("vlan_ids", [])}
            >
              Temizle
            </button>
          </div>
          <div className="scan-vlan-list" role="group" aria-label="VLAN seçimi">
            {filtered.map((v: Row) => (
              <label
                key={v.id}
                className={
                  !available(v) ? "scan-vlan unavailable" : "scan-vlan"
                }
              >
                <input
                  type="checkbox"
                  checked={values.vlan_ids.includes(v.id)}
                  disabled={!available(v)}
                  onChange={() => toggle(v.id)}
                />
                <span>
                  <b>{vlanLabel(v)}</b>
                  {v.group_id && v.group_id !== row?.id && (
                    <small>
                      Başka grupta:{" "}
                      {
                        catalog.items.find((g: Row) => g.id === v.group_id)
                          ?.name
                      }
                    </small>
                  )}
                </span>
              </label>
            ))}
            {!filtered.length && (
              <p className="scan-empty">Eşleşen VLAN yok.</p>
            )}
          </div>
        </fieldset>
        <label className="scan-enabled">
          <input
            type="checkbox"
            checked={values.enabled}
            onChange={(e) => change("enabled", e.target.checked)}
          />
          <span>Zamanlama etkin</span>
        </label>
        <p className="scan-note">
          Gruptaki VLAN’ların tam taraması bu takvimden yönetilir. Ping
          zamanlamaları ayrı çalışır. Geçmiş bir başlangıç seçilirse ilk kontrol
          turunda bir kez çalışır.
        </p>
        <div className="dialog-footer">
          <button type="button" className="secondary" onClick={close}>
            Vazgeç
          </button>
          <button className="primary" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Grubu kaydet"}
            <Check size={17} aria-hidden="true" />
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function RunHistory({
  group,
  close,
  refresh,
}: {
  group: Row;
  close: () => void;
  refresh: number;
}) {
  const query = useLiveQuery<Row>(
    `/ipam/scan-groups/${group.id}/runs`,
    refresh,
  );
  const status = (s: string) =>
    ({
      queued: "Kuyrukta",
      running: "Çalışıyor",
      succeeded: "Tamamlandı",
      failed: "Başarısız",
      cancelled: "İptal edildi",
      removed: "Kayıt kaldırılmış",
    })[s] || s;
  return (
    <Dialog title={`${group.name} · Tarama geçmişi`} onClose={close} wide>
      <div className="scan-history">
        <ErrorNote error={query.error || ""} />
        {!query.data && !query.error && (
          <p role="status">Tarama geçmişi yükleniyor…</p>
        )}
        {query.data?.items.length === 0 && (
          <p className="scan-empty">
            Bu grup için henüz zamanlanmış tarama başlamadı.
          </p>
        )}
        {query.data?.items.map((run: Row) => (
          <section key={run.id}>
            <h3>{date(run.created_at)}</h3>
            <p className="scan-note">
              Planlanan: {date(run.scheduled_for)} · Zamanlama sürümü{" "}
              {run.generation}
            </p>
            {run.jobs.map((j: Row) => (
              <div key={j.vlan_id} className="scan-job">
                <span>{j.vlan_label || "VLAN taraması"}</span>
                <a href="#jobs" title={j.job_id}>
                  {status(j.status)}
                </a>
              </div>
            ))}
            {run.errors.map((e: Row, i: number) => (
              <p key={i} className="error" role="alert">
                {e.message}
              </p>
            ))}
          </section>
        ))}
      </div>
    </Dialog>
  );
}

export default function IPAMSettings({
  user,
  refresh,
}: {
  user: Row;
  refresh: number;
}) {
  const [revision, setRevision] = useState(0);
  const query = useLiveQuery<Row>("/ipam/scan-groups", refresh + revision);
  const [search, setSearch] = useState("");
  const [form, setForm] = useState<Row | null>(null);
  const [history, setHistory] = useState<Row | null>(null);
  const [removing, setRemoving] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const canWrite = ["admin", "operator"].includes(user.role);
  const data = query.data;
  const items = (data?.items || []).filter((g: Row) =>
    `${g.name} ${g.description}`
      .toLocaleLowerCase("tr")
      .includes(search.toLocaleLowerCase("tr")),
  );
  return (
    <div className="scan-settings">
      <div className="scan-section-title">
        <div>
          <span className="scan-kicker">
            <CalendarBlank size={18} aria-hidden="true" />
            Tarama
          </span>
          <h2>VLAN tam tarama zamanlaması</h2>
          <p>
            VLAN’ları gruplayın; başlangıcı, tekrar aralığını ve kaç kez
            çalışacağını belirleyin.
          </p>
        </div>
        {canWrite && (
          <button
            className="primary"
            disabled={!data}
            onClick={() => setForm({})}
          >
            <Plus size={18} aria-hidden="true" />
            Yeni grup
          </button>
        )}
      </div>
      <ErrorNote error={error || query.error || ""} />
      <section className="panel scan-groups" aria-label="Tarama grupları">
        <div className="scan-group-tools">
          <h3>
            Tarama grupları{" "}
            <span className="scan-count">{data?.items.length || 0}</span>
          </h3>
          <label className="scan-search">
            <MagnifyingGlass size={18} aria-hidden="true" />
            <input
              aria-label="Tarama grubu ara"
              type="search"
              placeholder="Grup veya açıklama ara…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>
        {!data && !query.error && (
          <p className="scan-empty" role="status">
            Tarama grupları yükleniyor…
          </p>
        )}
        {data && items.length === 0 && (
          <div className="scan-empty">
            <CalendarBlank size={28} aria-hidden="true" />
            <p>
              {search
                ? "Aramayla eşleşen grup yok."
                : "Henüz tarama grubu yok. VLAN’ları seçerek ilk grubunuzu oluşturun."}
            </p>
          </div>
        )}
        {items.map((g: Row) => (
          <article className="scan-group" key={g.id}>
            <div className="scan-group-heading">
              <div>
                <h3>{g.name}</h3>
                {g.description && <p>{g.description}</p>}
              </div>
              <span
                className={`scan-state ${!g.enabled ? "paused" : !g.next_run_at ? "done" : "scheduled"}`}
              >
                {!g.enabled
                  ? "Duraklatıldı"
                  : !g.next_run_at
                    ? "Tamamlandı"
                    : "Zamanlandı"}
              </span>
            </div>
            <dl className="scan-facts">
              <div>
                <dt>Tekrarlama</dt>
                <dd>
                  {frequencies[g.frequency]} · Her {g.repeat_every}{" "}
                  {units[g.frequency]}
                </dd>
              </div>
              <div>
                <dt>Başlangıç</dt>
                <dd>{date(g.start_at)}</dd>
              </div>
              <div>
                <dt>Sonraki çalışma</dt>
                <dd>
                  {g.enabled && g.next_run_at ? date(g.next_run_at) : "—"}
                </dd>
              </div>
              <div>
                <dt>Çalışma sayısı</dt>
                <dd>
                  {g.run_count} / {g.run_limit || "Sürekli"}
                </dd>
              </div>
            </dl>
            <details className="scan-members">
              <summary>{g.vlan_ids.length} VLAN</summary>
              <ul>
                {g.vlan_ids.map((id: string) => {
                  const v = data?.vlans.find((v: Row) => v.id === id);
                  return (
                    <li key={id}>{v ? vlanLabel(v) : "VLAN kaldırılmış"}</li>
                  );
                })}
              </ul>
            </details>
            <div className="scan-group-actions">
              <button className="secondary" onClick={() => setHistory(g)}>
                <Clock size={17} aria-hidden="true" />
                Tarama geçmişi
              </button>
              {canWrite && (
                <button className="secondary" onClick={() => setForm(g)}>
                  <PencilSimple size={17} aria-hidden="true" />
                  Düzenle
                </button>
              )}
              {user.role === "admin" && (
                <button
                  className="icon-button danger"
                  aria-label={`${g.name} grubunu sil`}
                  onClick={() => setRemoving(g)}
                >
                  <Trash size={18} aria-hidden="true" />
                </button>
              )}
            </div>
          </article>
        ))}
      </section>
      <p className="scan-note">
        Saatler Türkiye saatine ({zone}) göredir. Tam tarama, seçili VLAN’ların
        IP keşfi ve entegrasyon eşleştirmelerini kapsar. Çalışan bir VLAN
        taraması tekrar kuyruğa alınmaz.
      </p>
      {form && data && (
        <GroupForm
          row={form.id ? form : undefined}
          catalog={data}
          close={() => setForm(null)}
          saved={() => {
            setRevision((r) => r + 1);
          }}
        />
      )}
      {history && (
        <RunHistory
          group={history}
          close={() => setHistory(null)}
          refresh={refresh + revision}
        />
      )}
      {removing && (
        <Dialog title="Tarama grubunu sil" onClose={() => setRemoving(null)}>
          <div className="scan-history">
            <p>
              <b>{removing.name}</b> grubu ve bu gruba ait zamanlama geçmişi
              silinecek. VLAN ve IP kayıtları ile başlamış taramalar korunur.
              VLAN’ların kendi tarama ayarları yeniden geçerli olur.
            </p>
            <ErrorNote error={error} />
            <div className="dialog-footer">
              <button
                className="secondary"
                disabled={busy}
                onClick={() => setRemoving(null)}
              >
                Vazgeç
              </button>
              <button
                className="secondary scan-delete"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    await api(`/ipam/scan-groups/${removing.id}`, "DELETE");
                    setRemoving(null);
                    setRevision((r) => r + 1);
                  } catch (e: any) {
                    setError(e.message);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Trash size={17} aria-hidden="true" />
                {busy ? "Siliniyor…" : "Grubu sil"}
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </div>
  );
}
