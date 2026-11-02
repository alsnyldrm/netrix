import React, { useDeferredValue, useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Plus,
  UploadSimple,
  ShieldCheck,
  Trash,
  Play,
  Stop,
  ArrowClockwise,
  CheckCircle,
} from "@phosphor-icons/react";
import { api, clearReadCache, useLiveQuery } from "./data";
import { Dialog, date } from "./main";
import "./firmware.css";

type Row = Record<string, any>;
const TABS = [
  ["devices", "Cihazlar"],
  ["images", "Firmware deposu"],
  ["groups", "Gruplar"],
  ["plans", "Güncelleme planları"],
  ["history", "İşlem geçmişi"],
  ["service", "Aktarım ve kurtarma"],
];
const FAMILIES: Row = {
  aos_s: "ArubaOS-Switch · 5400/2920/2930",
  cx6100: "Aruba 6100 · AOS-CX",
  hp1950: "HP 1950 · Comware 7",
};
const STATUS: Row = {
  draft: "Taslak",
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
  uploading: "Yükleme bekliyor",
};
const PHASE: Row = {
  waiting: "Bekliyor",
  preflight: "Ön kontrol",
  backup: "Konfigürasyon yedeği",
  transferring: "Dosya aktarımı ve yazım",
  rebooting: "Yeniden başlatma",
  verifying: "Sürüm doğrulama",
  reconcile: "Sonucu yeniden doğrulama",
  recovered: "Manuel kurtarma doğrulandı",
};
const MODES: Row = {
  check: "Yalnız ön kontrol",
  stage: "Aktar ve açılışa hazırla",
  upgrade: "Aktar ve yeniden başlat",
  activate: "Hazır imajı etkinleştir",
};
const bytes = (n: number) =>
  n >= 1024 ** 3
    ? (n / 1024 ** 3).toFixed(2) + " GB"
    : (n / 1024 ** 2).toFixed(1) + " MB";
function State({ value }: { value: string }) {
  return (
    <span className={"fw-state fw-state-" + value}>
      {STATUS[value] || value}
    </span>
  );
}
function Empty({ text }: { text: string }) {
  return (
    <div className="fw-empty">
      <ShieldCheck size={32} aria-hidden="true" />
      <p>{text}</p>
    </div>
  );
}
function Pager({
  offset,
  total,
  onChange,
  size = 50,
}: {
  offset: number;
  total: number;
  onChange: (v: number) => void;
  size?: number;
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

function DevicePicker({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const [q, setQ] = useState(""),
    [offset, setOffset] = useState(0);
  const query = useDeferredValue(q);
  const { data, error } = useLiveQuery<Row>(
    `/firmware/devices?q=${encodeURIComponent(query)}&offset=${offset}`,
    0,
    undefined,
    200,
  );
  return (
    <div className="fw-picker">
      <label>
        Cihaz ara
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOffset(0);
          }}
          placeholder="Ad, IP veya model"
        />
      </label>
      <p>{selected.length} cihaz seçildi</p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="fw-checklist">
        {data?.items.map((d: Row) => (
          <label key={d.id}>
            <input
              type="checkbox"
              checked={selected.includes(d.id)}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? [...selected, d.id]
                    : selected.filter((id) => id !== d.id),
                )
              }
            />
            <span>
              <b>{d.name}</b>
              <small>
                {d.management_ip} · {d.model || "Model kaydı yok"}
              </small>
            </span>
          </label>
        ))}
      </div>
      {data && (
        <Pager offset={offset} total={data.total} onChange={setOffset} />
      )}
    </div>
  );
}

function GroupForm({
  row,
  onClose,
  onSaved,
}: {
  row?: Row;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(row?.name || ""),
    [description, setDescription] = useState(row?.description || ""),
    [members, setMembers] = useState<string[]>(row?.device_ids || []);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <Dialog
      title={row ? "Firmware grubunu düzenle" : "Firmware grubu oluştur"}
      wide
      onClose={onClose}
    >
      <form
        className="fw-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api(
              "/firmware/groups" + (row ? "/" + row.id : ""),
              row ? "PUT" : "POST",
              { name, description, device_ids: members },
            );
            onSaved();
            onClose();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="fw-fields">
          <label>
            Grup adı
            <input
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            Açıklama
            <input
              maxLength={400}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
        </div>
        <p className="muted">
          Grup adını ve üyelerini siz belirlersiniz. Yedekleme gruplarından
          bağımsızdır.
        </p>
        <DevicePicker selected={members} onChange={setMembers} />
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="fw-form-actions">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onClose}
          >
            Vazgeç
          </button>
          <button className="primary" disabled={busy}>
            {busy ? "Kaydediliyor…" : "Grubu kaydet"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ImageForm({
  row,
  onClose,
  onSaved,
}: {
  row?: Row;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Row>({
    name: row?.name || "",
    family: row?.family || "aos_s",
    version: row?.version || "",
    models: row?.models?.join(", ") || "",
    expected_sha256: row?.expected_sha256 || "",
    notes: row?.notes || "",
  });
  const [file, setFile] = useState<File | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [progress, setProgress] = useState(0);
  const [created, setCreated] = useState<Row | undefined>(row);
  const field = (key: string) => ({
    name: key,
    autoComplete: "off",
    spellCheck: false,
    value: values[key],
    onChange: (
      e: React.ChangeEvent<
        HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
      >,
    ) => setValues({ ...values, [key]: e.target.value }),
  });
  return (
    <Dialog
      title="Firmware dosyası yükle"
      wide
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="fw-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!file) return;
          setBusy(true);
          setError("");
          try {
            const image =
              created ||
              (await api("/firmware/images", "POST", {
                ...values,
                models: values.models
                  .split(",")
                  .map((v: string) => v.trim())
                  .filter(Boolean),
                original_name: file.name,
              }));
            setCreated(image);
            await new Promise<void>((resolve, reject) => {
              const request = new XMLHttpRequest();
              request.open(
                "PUT",
                `/api/v1/firmware/images/${image.id}/content`,
              );
              request.setRequestHeader("X-Netrix-Request", "1");
              request.setRequestHeader(
                "Content-Type",
                "application/octet-stream",
              );
              request.timeout = 3600000;
              request.upload.onprogress = (e) => {
                if (e.lengthComputable)
                  setProgress(Math.round((e.loaded / e.total) * 100));
              };
              request.onerror = () =>
                reject(
                  new Error(
                    "Dosya aktarımı kesildi; aynı dosyayla yeniden deneyin.",
                  ),
                );
              request.ontimeout = () =>
                reject(new Error("Dosya aktarımı zaman aşımına uğradı."));
              request.onload = () => {
                if (request.status >= 200 && request.status < 300) resolve();
                else {
                  let message = "Dosya yüklenemedi";
                  try {
                    message =
                      JSON.parse(request.responseText).detail || message;
                  } catch {}
                  reject(new Error(message));
                }
              };
              request.send(file);
            });
            clearReadCache();
            onSaved();
            onClose();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="fw-fields">
          <label>
            Dosya adı için açıklama
            <input
              required
              maxLength={120}
              disabled={!!created || busy}
              {...field("name")}
            />
          </label>
          <label>
            Cihaz ailesi
            <select disabled={!!created || busy} {...field("family")}>
              {Object.entries(FAMILIES).map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Hedef sürüm
            <input
              required
              disabled={!!created || busy}
              placeholder="Örn. WC.16.11.0026"
              {...field("version")}
            />
          </label>
          <label>
            Uyumlu ürün kodları / tam modeller
            <input
              required
              disabled={!!created || busy}
              placeholder="Virgülle ayırın: JL256A, JL254A"
              {...field("models")}
            />
          </label>
          <label className="fw-full">
            Üreticinin yayımladığı SHA-256
            <input
              className="mono"
              required
              pattern="[a-fA-F0-9]{64}"
              minLength={64}
              maxLength={64}
              disabled={!!created || busy}
              {...field("expected_sha256")}
            />
          </label>
          <label className="fw-full">
            Sürüm geçişi, BootROM ve kurtarma notları
            <textarea
              maxLength={8000}
              disabled={!!created || busy}
              {...field("notes")}
            />
          </label>
          <label className="fw-full">
            Firmware dosyası
            <input
              type="file"
              required
              disabled={busy}
              accept={values.family === "hp1950" ? ".ipe" : ".swi"}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>
        </div>
        <p className="muted">
          Dosya aktarılırken sunucuda SHA-256 hesaplanır. Üretici değeriyle
          eşleşmeden kullanıma açılmaz.
        </p>
        {busy && (
          <div role="status">
            <progress max={100} value={progress} aria-label="Dosya yükleme" />
            <p>
              {progress === 100
                ? "Sunucu dosyayı doğruluyor…"
                : `Dosya aktarılıyor · %${progress}`}
            </p>
          </div>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="fw-form-actions">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onClose}
          >
            Vazgeç
          </button>
          <button className="primary" disabled={busy || !file}>
            <UploadSimple aria-hidden="true" size={18} />
            {busy ? "Yükleniyor…" : "Dosyayı yükle"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function PlanForm({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (id: string) => void;
}) {
  const groups = useLiveQuery<Row>("/firmware/groups"),
    images = useLiveQuery<Row>("/firmware/images?limit=100");
  const [name, setName] = useState(""),
    [mode, setMode] = useState("check"),
    [concurrency, setConcurrency] = useState(1),
    [time, setTime] = useState("");
  const [steps, setSteps] = useState([{ group_id: "", image_id: "" }]),
    [path, setPath] = useState(false),
    [outage, setOutage] = useState(false),
    [enableSFTP, setEnableSFTP] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const move = (index: number, direction: number) => {
    const next = [...steps];
    [next[index], next[index + direction]] = [
      next[index + direction],
      next[index],
    ];
    setSteps(next);
  };
  return (
    <Dialog title="Güncelleme planı oluştur" wide onClose={onClose}>
      <form
        className="fw-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            const p = await api("/firmware/plans", "POST", {
              name,
              mode,
              concurrency,
              steps,
              available_at: time ? new Date(time).toISOString() : null,
              allow_enable_sftp: enableSFTP,
              acknowledge_upgrade_path: path,
              acknowledge_outage: outage,
            });
            onSaved(p.id);
            onClose();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="fw-fields">
          <label>
            Plan adı
            <input
              required
              maxLength={120}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <label>
            İşlem
            <select
              aria-label="İşlem"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
            >
              {["check", "stage", "upgrade"].map((key) => (
                <option key={key} value={key}>
                  {MODES[key]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Grup içi eşzamanlı cihaz
            <select
              aria-label="Grup içi eşzamanlı cihaz"
              value={concurrency}
              onChange={(e) => setConcurrency(Number(e.target.value))}
            >
              {[1, 2, 3, 4].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
          <label>
            Başlangıç zamanı · yerel saat
            <input
              type="datetime-local"
              value={time}
              onChange={(e) => setTime(e.target.value)}
            />
            <small>Boşsa, siz Başlat dediğinizde çalışır.</small>
          </label>
        </div>
        <p>
          Grupların çalışma sırasını aşağıdan belirleyin. Önceki aşama
          tamamlanmadan sonraki başlamaz; hatada plan bekler.
        </p>
        <div className="fw-steps">
          {steps.map((step, i) => (
            <fieldset className="fw-step" key={i}>
              <legend>Aşama {i + 1}</legend>
              <div className="fw-fields">
                <label>
                  Firmware grubu
                  <select
                    aria-label="Firmware grubu"
                    required
                    value={step.group_id}
                    onChange={(e) =>
                      setSteps(
                        steps.map((s, n) =>
                          n === i ? { ...s, group_id: e.target.value } : s,
                        ),
                      )
                    }
                  >
                    <option value="">Grup seçin</option>
                    {groups.data?.items.map((g: Row) => (
                      <option key={g.id} value={g.id}>
                        {g.name} · {g.device_count} cihaz
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Firmware imajı
                  <select
                    aria-label="Firmware imajı"
                    required
                    value={step.image_id}
                    onChange={(e) =>
                      setSteps(
                        steps.map((s, n) =>
                          n === i ? { ...s, image_id: e.target.value } : s,
                        ),
                      )
                    }
                  >
                    <option value="">Doğrulanmış imaj seçin</option>
                    {images.data?.items
                      .filter((r: Row) => r.status === "ready")
                      .map((r: Row) => (
                        <option key={r.id} value={r.id}>
                          {r.name} · {r.version}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              <div className="fw-row-actions">
                <button
                  type="button"
                  className="secondary"
                  disabled={!i}
                  aria-label={`Aşama ${i + 1} yukarı`}
                  onClick={() => move(i, -1)}
                >
                  <ArrowUp size={16} aria-hidden="true" />
                  Yukarı
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={i === steps.length - 1}
                  aria-label={`Aşama ${i + 1} aşağı`}
                  onClick={() => move(i, 1)}
                >
                  <ArrowDown size={16} aria-hidden="true" />
                  Aşağı
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={steps.length === 1}
                  aria-label={`Aşama ${i + 1} kaldır`}
                  onClick={() => setSteps(steps.filter((_, n) => i !== n))}
                >
                  <Trash size={16} aria-hidden="true" />
                  Kaldır
                </button>
              </div>
            </fieldset>
          ))}
        </div>
        <button
          type="button"
          className="secondary"
          disabled={steps.length >= 50}
          onClick={() => setSteps([...steps, { group_id: "", image_id: "" }])}
        >
          <Plus size={18} aria-hidden="true" />
          Aşama ekle
        </button>
        {mode !== "check" && (
          <label className="fw-check">
            <input
              type="checkbox"
              required
              checked={path}
              onChange={(e) => setPath(e.target.checked)}
            />
            <span>
              Üreticinin model, sürüm geçişi ve BootROM gereksinimlerini
              doğruladım.
            </span>
          </label>
        )}
        {mode !== "check" && (
          <label className="fw-check">
            <input
              type="checkbox"
              checked={enableSFTP}
              onChange={(e) => setEnableSFTP(e.target.checked)}
            />
            <span>
              5400/2920/2930 cihazlarda gerekirse SFTP erişimini aç. Bu
              değişikliğin TFTP’yi kapatmasını onaylıyorum.
            </span>
          </label>
        )}
        {mode === "upgrade" && (
          <label className="fw-check">
            <input
              type="checkbox"
              required
              checked={outage}
              onChange={(e) => setOutage(e.target.checked)}
            />
            <span>Yeniden başlatmayı ve hizmet kesintisini onaylıyorum.</span>
          </label>
        )}
        {mode === "stage" && (
          <p className="fw-note">
            HP 1950’de hazırlama işlemi sonraki açılış imajını da değiştirir.
            Cihaz bu planda yeniden başlatılmaz.
          </p>
        )}
        {(error || groups.error || images.error) && (
          <p role="alert" className="error">
            {error || groups.error || images.error}
          </p>
        )}
        <div className="fw-form-actions">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onClose}
          >
            Vazgeç
          </button>
          <button className="primary" disabled={busy}>
            {busy ? "Oluşturuluyor…" : "Taslak oluştur"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function PlanDetail({
  id,
  refresh,
  admin,
  busy,
  actionError,
  mutate,
  onClose,
}: {
  id: string;
  refresh: number;
  admin: boolean;
  busy: boolean;
  actionError: string;
  mutate: (path: string, body?: Row) => Promise<void>;
  onClose: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const result = useLiveQuery<Row>(
    `/firmware/plans/${id}?offset=${offset}`,
    refresh,
  );
  const [confirmation, setConfirmation] = useState("");
  const [recovery, setRecovery] = useState<Row | null>(null);
  const [recoveryName, setRecoveryName] = useState("");
  const p = result.data;
  const action = async (operation: string) => {
    await mutate(`/plans/${id}/${operation}`);
    setConfirmation("");
  };
  return (
    <Dialog title={p?.name || "Firmware planı"} wide onClose={onClose}>
      <div className="fw-form">
        {(result.error || actionError) && (
          <p className="error" role="alert">
            {result.error || actionError}
          </p>
        )}
        {!p ? (
          <p role="status">Plan okunuyor…</p>
        ) : (
          <>
            <div className="fw-detail-header">
              <State value={p.status} />
              <span>
                {MODES[p.mode]} · {date(p.available_at)}
              </span>
            </div>
            <ol className="fw-plan-order">
              {p.steps.map((s: Row, i: number) => (
                <li key={i}>
                  <b>{s.group_name}</b>
                  <span>
                    {s.version} · {s.count} cihaz
                  </span>
                </li>
              ))}
            </ol>
            <div
              className="fw-table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Firmware tablosu"
            >
              <table>
                <thead>
                  <tr>
                    <th>Cihaz</th>
                    <th>Durum / aşama</th>
                    <th>İmaj / sürüm</th>
                    <th>Kanıt ve sonuç</th>
                  </tr>
                </thead>
                <tbody>
                  {p.targets.map((t: Row) => (
                    <tr key={t.id}>
                      <td>
                        <b>{t.evidence.device_name}</b>
                        <small>
                          {t.evidence.management_ip} · Aşama {t.stage + 1}
                        </small>
                      </td>
                      <td>
                        <State value={t.status} />
                        <small>{PHASE[t.phase] || t.phase}</small>
                      </td>
                      <td>
                        <span>
                          {t.previous_version || "Ön kontrol bekliyor"}
                        </span>
                        <small>Hedef: {t.evidence.expected_version}</small>
                        <small>
                          {t.bank === "auto"
                            ? "İmaj alanı ön kontrolde seçilir"
                            : `${t.previous_bank} → ${t.bank}`}
                        </small>
                      </td>
                      <td>
                        {t.error ? (
                          <p className="fw-error-text">{t.error}</p>
                        ) : t.verified_version ? (
                          <span>Çalışan: {t.verified_version}</span>
                        ) : t.transfer_bytes ? (
                          <span>{bytes(t.transfer_bytes)} aktarıldı</span>
                        ) : (
                          "—"
                        )}
                        {t.snapshot_id && (
                          <small>Konfigürasyon yedeği korumada</small>
                        )}
                        {admin && t.status === "attention" && (
                          <div className="fw-row-actions">
                            <button
                              className="text-button"
                              disabled={busy}
                              onClick={() => mutate(`/targets/${t.id}/verify`)}
                            >
                              Sürümü yeniden doğrula
                            </button>
                            <button
                              className="text-button"
                              disabled={busy}
                              onClick={() => {
                                setRecovery(t);
                                setRecoveryName("");
                              }}
                            >
                              Manuel kurtarmayı tamamla
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager
              offset={offset}
              total={p.target_total}
              onChange={setOffset}
            />
            {admin && (
              <div className="fw-row-actions">
                {p.status === "draft" && (
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() => setConfirmation("start")}
                  >
                    <Play size={18} aria-hidden="true" />
                    Başlat
                  </button>
                )}
                {p.status === "ready" && (
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() => setConfirmation("activate")}
                  >
                    <Play size={18} aria-hidden="true" />
                    Yeniden başlat ve etkinleştir
                  </button>
                )}
                {p.status === "paused" && !p.cancel_requested && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => action("retry")}
                  >
                    <ArrowClockwise size={18} aria-hidden="true" />
                    Güvenli hedefleri yeniden dene
                  </button>
                )}
                {!["succeeded", "cancelled"].includes(p.status) && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => setConfirmation("cancel")}
                  >
                    <Stop size={18} aria-hidden="true" />
                    Sonraki işlemleri durdur
                  </button>
                )}
              </div>
            )}
            {recovery && (
              <div
                className="fw-note"
                role="group"
                aria-label="Manuel kurtarma onayı"
              >
                <p>
                  Cihazın imaj yazımını tamamladığını ve çalışır durumda
                  olduğunu konsol/SSH ile doğruladıysanız kilidi serbest
                  bırakın. Bu işlem firmware kurulumunu başarılı saymaz.
                </p>
                <label>
                  Cihazın tam adı
                  <input
                    value={recoveryName}
                    onChange={(e) => setRecoveryName(e.target.value)}
                    autoComplete="off"
                  />
                </label>
                <div className="fw-row-actions">
                  <button
                    className="primary"
                    disabled={
                      busy || recoveryName !== recovery.evidence.device_name
                    }
                    onClick={async () => {
                      await mutate(`/targets/${recovery.id}/release`, {
                        device_name: recoveryName,
                        confirmed_recovery: true,
                      });
                      setRecovery(null);
                    }}
                  >
                    Kurtarmayı doğrula
                  </button>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => setRecovery(null)}
                  >
                    Vazgeç
                  </button>
                </div>
              </div>
            )}
            {confirmation && (
              <div className="fw-note" role="group" aria-label="İşlem onayı">
                <p>
                  {confirmation === "activate"
                    ? "Hazır imajlar için yeniden başlatma ve hizmet kesintisini onaylıyor musunuz?"
                    : confirmation === "cancel"
                      ? "Yeni işlemler duracak. Başlamış flash yazımı veya yeniden başlatma kesilmeyecek."
                      : p.mode === "check"
                        ? "Seçili cihazlarda salt okunur ön kontrol başlatılacak."
                        : "Bu plan seçili cihazlara firmware aktaracak. Plan türüne göre yeniden başlatma ve hizmet kesintisi oluşabilir."}
                </p>
                <div className="fw-row-actions">
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() => action(confirmation)}
                  >
                    İşlemi onayla
                  </button>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => setConfirmation("")}
                  >
                    Vazgeç
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Dialog>
  );
}

export default function FirmwareWorkspace({
  tab,
  navigate,
  user,
  refresh: externalRefresh,
}: {
  tab: string;
  navigate: (key: string) => void;
  user: Row;
  refresh: number;
}) {
  const [revision, setRevision] = useState(0),
    [q, setQ] = useState(""),
    [offset, setOffset] = useState(0),
    [error, setError] = useState("");
  const [modal, setModal] = useState<{ kind: string; row?: Row } | null>(null),
    [detail, setDetail] = useState<string | null>(null),
    [busy, setBusy] = useState(false);
  const refresh = revision + externalRefresh,
    admin = user.role === "admin",
    write = admin || user.role === "operator";
  const search = useDeferredValue(q);
  const overview = useLiveQuery<Row>("/firmware/overview", refresh);
  const endpoint =
    tab === "service"
      ? null
      : tab === "groups"
        ? "/firmware/groups"
        : tab === "plans" || tab === "history"
          ? `/firmware/plans?limit=30&offset=${offset}&history=${tab === "history"}`
          : `/firmware/${tab}?q=${encodeURIComponent(search)}&offset=${offset}`;
  const result = useLiveQuery<Row>(endpoint, refresh, undefined, q ? 200 : 0);
  useEffect(() => {
    setOffset(0);
    setQ("");
  }, [tab]);
  useEffect(() => {
    if (!detail && !["plans", "history"].includes(tab)) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") setRevision((n) => n + 1);
    }, 5000);
    return () => clearInterval(timer);
  }, [tab, detail]);
  const saved = () => setRevision((n) => n + 1);
  const mutate = async (path: string, body?: Row) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api("/firmware" + path, "POST", body);
      saved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const rows = result.data?.items || [];
  return (
    <div className="fw-workspace" aria-busy={busy}>
      <nav className="fw-tabs" aria-label="Firmware bölümleri">
        {TABS.map(([key, title]) => (
          <a
            key={key}
            href={"#firmware-" + key}
            aria-current={tab === key ? "page" : undefined}
            onClick={(e) => {
              if (!e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0) {
                e.preventDefault();
                navigate("firmware-" + key);
              }
            }}
          >
            {title}
          </a>
        ))}
      </nav>
      <div className="fw-summary">
        <div>
          <span>Doğrulanmış dosya</span>
          <b>{overview.data?.images ?? "—"}</b>
        </div>
        <div>
          <span>Firmware grubu</span>
          <b>{overview.data?.groups ?? "—"}</b>
        </div>
        <div>
          <span>Çalışan plan</span>
          <b>{overview.data ? overview.data.plans.running || 0 : "—"}</b>
        </div>
        <div>
          <span>Müdahale bekleyen</span>
          <b>{overview.data ? overview.data.plans.paused || 0 : "—"}</b>
        </div>
      </div>
      {(error || result.error || overview.error) && (
        <div role="alert" className="error">
          {error || result.error || overview.error}
        </div>
      )}
      <section
        className="fw-panel"
        aria-label={TABS.find(([key]) => key === tab)?.[1]}
      >
        <div className="fw-toolbar">
          <div>
            <h2>{TABS.find(([key]) => key === tab)?.[1]}</h2>
            <p>
              {tab === "devices"
                ? "Ortak envanterden, desteklenen cihazlar."
                : tab === "groups"
                  ? "Grupları rol ve ihtiyacınıza göre siz tanımlayın."
                  : tab === "images"
                    ? "Uyumlu modelleri ve bütünlüğü doğrulanmış imajlar."
                    : tab === "plans"
                      ? "Ön kontrol, hazırlama ve etkinleştirmeyi sıraya koyun."
                      : tab === "history"
                        ? "Tamamlanmış ve durdurulmuş işlemlerin kalıcı kaydı."
                        : "Cihaz bağlantıları ve kurtarma davranışı."}
            </p>
          </div>
          <div className="fw-toolbar-actions">
            {["images", "devices"].includes(tab) && (
              <input
                aria-label="Firmware kayıtlarında ara"
                placeholder="Ara…"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setOffset(0);
                }}
              />
            )}
            {admin && tab === "images" && (
              <button
                className="primary"
                onClick={() => setModal({ kind: "image" })}
              >
                <UploadSimple size={18} aria-hidden="true" />
                Dosya yükle
              </button>
            )}
            {write && tab === "groups" && (
              <button
                className="primary"
                onClick={() => setModal({ kind: "group" })}
              >
                <Plus size={18} aria-hidden="true" />
                Grup oluştur
              </button>
            )}
            {admin && tab === "plans" && (
              <button
                className="primary"
                onClick={() => setModal({ kind: "plan" })}
              >
                <Plus size={18} aria-hidden="true" />
                Plan oluştur
              </button>
            )}
          </div>
        </div>
        {result.loading && (
          <p className="fw-loading" role="status">
            Kayıtlar okunuyor…
          </p>
        )}
        {tab === "service" ? (
          <div className="fw-service">
            <div className="fw-note">
              <ShieldCheck size={24} aria-hidden="true" />
              <div>
                <b>
                  {overview.data?.service.configured
                    ? "Dosya sunucusu yapılandırıldı"
                    : "Dosya sunucusu adresi bekleniyor"}
                </b>
                <p>
                  {overview.data?.service.host ||
                    "Sunucu adresi yapılandırılmamış"}{" "}
                  · SFTP {overview.data?.service.sftp_port || 2222} · TFTP 69
                </p>
                <p>
                  Dosya erişimi yalnız çalışan işlemin hedef IP’sine, süreli ve
                  salt okunur verilir.
                </p>
              </div>
            </div>
            <div
              className="fw-table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Firmware tablosu"
            >
              <table>
                <thead>
                  <tr>
                    <th>Cihaz ailesi</th>
                    <th>Komut bağlantısı</th>
                    <th>Dosya yolu</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>5400 / 2920 / 2930</td>
                    <td>SSH</td>
                    <td>SFTP ile cihazın boş imaj bankasına gönderilir.</td>
                  </tr>
                  <tr>
                    <td>6100</td>
                    <td>SSH</td>
                    <td>Cihaz süreli SFTP hesabıyla dosyayı çeker.</td>
                  </tr>
                  <tr>
                    <td>HP 1950</td>
                    <td>SSH</td>
                    <td>
                      Cihaz TFTP ile .ipe paketini çeker; sonraki açılış
                      hazırlanır.
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <h3>Kurtarma ve doğrulama</h3>
            <p>
              Her yazma öncesinde şifreli konfigürasyon yedeği alınır. Önceki
              sürüm ve imaj alanı işlem ayrıntısında tutulur. Eski sürüme dönüş,
              sürümle uyumlu konfigürasyon ve üretici yönergesiyle
              planlanmalıdır.
            </p>
            <p>
              Bağlantı yazma veya yeniden başlatma sırasında kesilirse komut
              otomatik tekrarlanmaz. Plan bekler; işlem ayrıntısından salt
              okunur sürüm doğrulaması başlatabilirsiniz. Ulaşılamayan cihaz
              için konsol erişimi gerekebilir.
            </p>
            <p>
              Stack/VSF aynı yönetim hedefi üzerinden ele alınır. Üyeleri farklı
              gruplarda ayrı cihazlar gibi çalıştırmayın. Kesintisiz güncelleme
              taahhüdü yoktur.
            </p>
          </div>
        ) : !result.loading && !rows.length ? (
          <Empty
            text={
              tab === "groups"
                ? "Henüz firmware grubu yok. İlk grubunuzu oluşturun."
                : tab === "images"
                  ? "Henüz firmware dosyası yüklenmedi."
                  : tab === "devices"
                    ? "Desteklenen cihaz kaydı bulunamadı."
                    : "Henüz firmware planı bulunmuyor."
            }
          />
        ) : (
          <div
            className="fw-table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Firmware tablosu"
          >
            <table>
              <thead>
                <tr>
                  {(tab === "devices"
                    ? ["Cihaz", "Model / aile", "Çalışan sürüm", "Aktarım"]
                    : tab === "images"
                      ? ["Firmware", "Uyumluluk", "Bütünlük", "İşlemler"]
                      : tab === "groups"
                        ? ["Grup", "Açıklama", "Üyeler", "İşlemler"]
                        : ["Plan", "İşlem / sıra", "Durum", "Zaman"]
                  ).map((label) => (
                    <th key={label}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r: Row) => (
                  <tr key={r.id}>
                    {tab === "devices" ? (
                      <>
                        <td>
                          <b>{r.name}</b>
                          <small>{r.management_ip}</small>
                        </td>
                        <td>
                          {r.model || "—"}
                          <small>{FAMILIES[r.family]}</small>
                        </td>
                        <td className="mono">
                          {r.software_version || "Henüz okunmadı"}
                        </td>
                        <td>SSH + {r.protocol.toUpperCase()}</td>
                      </>
                    ) : tab === "images" ? (
                      <>
                        <td>
                          <button
                            className="text-button fw-plan-link"
                            onClick={() =>
                              setModal({ kind: "image-detail", row: r })
                            }
                          >
                            {r.name}
                          </button>
                          <small>
                            {r.version} · {bytes(r.size_bytes)}
                          </small>
                        </td>
                        <td>
                          {FAMILIES[r.family]}
                          <small>{r.models.join(", ")}</small>
                        </td>
                        <td>
                          <State value={r.status} />
                          <small
                            className="mono"
                            title={r.sha256 || r.expected_sha256}
                          >
                            {(r.sha256 || r.expected_sha256).slice(0, 20)}…
                          </small>
                        </td>
                        <td>
                          <div className="fw-row-actions">
                            {admin && r.status === "uploading" && (
                              <button
                                className="text-button"
                                onClick={() =>
                                  setModal({ kind: "image", row: r })
                                }
                              >
                                Yüklemeyi tamamla
                              </button>
                            )}
                            {admin && r.status === "ready" && (
                              <a
                                className="text-button"
                                href={`/api/v1/firmware/images/${r.id}/content`}
                              >
                                İndir
                              </a>
                            )}
                            {admin && (
                              <button
                                className="text-button"
                                onClick={() =>
                                  setModal({ kind: "delete-image", row: r })
                                }
                              >
                                Sil
                              </button>
                            )}
                          </div>
                        </td>
                      </>
                    ) : tab === "groups" ? (
                      <>
                        <td>
                          <b>{r.name}</b>
                        </td>
                        <td>{r.description || "—"}</td>
                        <td>{r.device_count} cihaz</td>
                        <td>
                          <div className="fw-row-actions">
                            {write && (
                              <button
                                className="text-button"
                                onClick={async () => {
                                  try {
                                    const group = await api(
                                      "/firmware/groups/" + r.id,
                                    );
                                    setModal({ kind: "group", row: group });
                                  } catch (e: any) {
                                    setError(e.message);
                                  }
                                }}
                              >
                                Düzenle
                              </button>
                            )}
                            {admin && (
                              <button
                                className="text-button"
                                onClick={() =>
                                  setModal({ kind: "delete-group", row: r })
                                }
                              >
                                Sil
                              </button>
                            )}
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td>
                          <button
                            className="text-button fw-plan-link"
                            onClick={() => setDetail(r.id)}
                          >
                            {r.name}
                          </button>
                          <small>
                            {Object.values(r.counts as Row).reduce(
                              (a: number, n: any) => a + Number(n),
                              0,
                            )}{" "}
                            cihaz
                          </small>
                        </td>
                        <td>
                          {MODES[r.mode]}
                          <small>
                            {r.steps.map((s: Row) => s.group_name).join(" → ")}
                          </small>
                        </td>
                        <td>
                          <State value={r.status} />
                        </td>
                        <td>{date(r.available_at)}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {result.data && tab !== "groups" && (
          <Pager
            offset={offset}
            total={result.data.total}
            onChange={setOffset}
            size={["plans", "history"].includes(tab) ? 30 : 50}
          />
        )}
      </section>
      {modal?.kind === "image-detail" && (
        <Dialog
          title={modal.row?.name || "Firmware ayrıntısı"}
          onClose={() => setModal(null)}
        >
          <div className="fw-form">
            <dl>
              <dt>Cihaz ailesi</dt>
              <dd>{FAMILIES[modal.row!.family]}</dd>
              <dt>Sürüm / modeller</dt>
              <dd>
                {modal.row!.version} · {modal.row!.models.join(", ")}
              </dd>
              <dt>SHA-256</dt>
              <dd className="mono fw-hash">
                {modal.row!.sha256 || modal.row!.expected_sha256}
              </dd>
            </dl>
            <h3>Sürüm geçişi ve kurtarma notları</h3>
            <p className="fw-notes">{modal.row!.notes || "Not eklenmemiş."}</p>
            <button className="secondary" onClick={() => setModal(null)}>
              Kapat
            </button>
          </div>
        </Dialog>
      )}
      {modal?.kind === "group" && (
        <GroupForm
          row={modal.row}
          onClose={() => setModal(null)}
          onSaved={saved}
        />
      )}
      {modal?.kind === "image" && (
        <ImageForm
          row={modal.row}
          onClose={() => setModal(null)}
          onSaved={saved}
        />
      )}
      {modal?.kind === "plan" && (
        <PlanForm
          onClose={() => setModal(null)}
          onSaved={(id) => {
            saved();
            setDetail(id);
          }}
        />
      )}
      {modal?.kind.startsWith("delete-") && (
        <Dialog title="Kaydı sil" onClose={() => setModal(null)}>
          <div className="fw-form">
            <p>
              <b>{modal.row?.name}</b> kaydını silmek istiyor musunuz?
            </p>
            <p className="muted">
              Plan geçmişinde kullanılan imajlar korunur. Grup silinmesi
              cihazları veya eski planları silmez.
            </p>
            <div className="fw-form-actions">
              <button className="secondary" onClick={() => setModal(null)}>
                Vazgeç
              </button>
              <button
                className="primary danger"
                onClick={async () => {
                  try {
                    await api(
                      `/firmware/${modal.kind === "delete-image" ? "images" : "groups"}/${modal.row?.id}`,
                      "DELETE",
                    );
                    saved();
                    setModal(null);
                  } catch (e: any) {
                    setError(e.message);
                    setModal(null);
                  }
                }}
              >
                Sil
              </button>
            </div>
          </div>
        </Dialog>
      )}
      {detail && (
        <PlanDetail
          id={detail}
          refresh={refresh}
          admin={admin}
          busy={busy}
          actionError={error}
          mutate={mutate}
          onClose={() => setDetail(null)}
        />
      )}
    </div>
  );
}
