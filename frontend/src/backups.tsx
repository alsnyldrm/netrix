import { useLiveQuery } from "./data";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft } from "@phosphor-icons/react";
import { api, Dialog, date } from "./main";
import { allRows, InventoryTable } from "./inventory";
import "./configurations.css";
type Row = Record<string, any>;

export function ConfigEditors({ result }: { result: Row }) {
  return (
    <div className="config-comparison">
      <p role="status">
        {result.changed
          ? "Konfigürasyon farkları işaretlendi."
          : "Konfigürasyon ayarları aynı."}{" "}
        Hassas değerler maskelenir.
      </p>
      <div
        className="config-editors"
        style={{
          gridTemplateColumns: `repeat(${result.documents.length}, minmax(0, 1fr))`,
        }}
      >
        {result.documents.map((d: Row) => (
          <section className="config-editor" key={d.id}>
            <header>
              <strong>{d.device_name}</strong>
              <span>
                {date(d.created_at)}{" "}
                {d.is_base && <b className="base-config-label">Base config</b>}
              </span>
            </header>
            <pre
              tabIndex={0}
              aria-label={`${d.device_name} konfigürasyonu`}
              role="region"
            >
              {d.lines.map((line: Row) => (
                <span
                  key={line.number}
                  className={`config-line${line.changed ? " changed" : ""}`}
                >
                  <span className="config-line-number" aria-hidden="true">
                    {line.number}
                  </span>
                  <span>
                    {line.changed && (
                      <span className="sr-only">Değişen satır: </span>
                    )}
                    {line.text || " "}
                  </span>
                </span>
              ))}
            </pre>
          </section>
        ))}
      </div>
      {result.documents.slice(1).map(
        (d: Row) =>
          d.diff && (
            <details key={d.id}>
              <summary>
                {result.documents[0].device_name} / {d.device_name} · Eklenen ve
                kaldırılan satırlar
              </summary>
              <pre className="config-diff">{d.diff}</pre>
            </details>
          ),
      )}
    </div>
  );
}

export function ConfigComparison({
  sameDevice = false,
  initialDevice,
}: {
  sameDevice?: boolean;
  initialDevice?: Row;
}) {
  const deviceQuery = useLiveQuery<Row[]>("comparison:devices", 0, () =>
    allRows("/inventory/backup-devices"),
  );
  const devices = deviceQuery.data || [];
  const [selected, setSelected] = useState<string[]>(
    initialDevice ? [initialDevice.id] : [],
  );
  const [picking, setPicking] = useState(false);
  const [search, setSearch] = useState("");
  const snapshotQuery = useLiveQuery<Record<string, Row[]>>(
    selected.length ? "comparison:snapshots:" + selected.join(",") : null,
    0,
    async () =>
      Object.fromEntries(
        await Promise.all(
          selected.map(async (id) => [
            id,
            await allRows(`/snapshots?device_id=${id}`),
          ]),
        ),
      ),
  );
  const snapshots = snapshotQuery.data || {};
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!snapshotQuery.data) return;
    const records = snapshotQuery.data;
    setChoices((previous) => {
      const initial: Record<string, string> = {};
      if (sameDevice && selected.length) {
        const rows = records[selected[0]] || [];
        initial.left = rows.some((r: Row) => r.id === previous.left)
          ? previous.left
          : rows.find((r: Row) => r.is_base)?.id || rows.at(-1)?.id || "";
        initial.right = rows.some((r: Row) => r.id === previous.right)
          ? previous.right
          : rows[0]?.id || "";
      } else
        for (const [id, rows] of Object.entries(records))
          initial[id] = rows.some((r: Row) => r.id === previous[id])
            ? previous[id]
            : rows[0]?.id || "";
      return initial;
    });
  }, [snapshotQuery.data, sameDevice]);
  useEffect(() => {
    setResult(null);
    setError("");
  }, [selected.join(","), sameDevice]);
  const keys = sameDevice ? ["left", "right"] : selected;
  const ready =
    (sameDevice ? selected.length === 1 : selected.length >= 2) &&
    keys.every((k) => choices[k]) &&
    new Set(keys.map((k) => choices[k])).size === keys.length;
  const choose = (key: string, value: string) => {
    setChoices((v) => ({ ...v, [key]: value }));
    setResult(null);
  };
  return (
    <div className="config-workspace">
      {(error || deviceQuery.error || snapshotQuery.error) && (
        <p role="alert" className="error">
          {error || deviceQuery.error || snapshotQuery.error}
        </p>
      )}
      <div className="config-toolbar">
        <button className="secondary" onClick={() => setPicking(true)}>
          Önce cihaz seç
        </button>
        <span>
          {sameDevice
            ? "Bir cihaz ve iki kayıtlı konfigürasyon seçin."
            : "2–4 farklı cihaz seçin."}
        </span>
      </div>
      {selected.length > 0 && (
        <div className="config-selectors">
          {keys.map((key, index) => {
            const deviceId = sameDevice ? selected[0] : key;
            const device =
              devices.find((d) => d.id === deviceId) || initialDevice;
            return (
              <label key={key}>
                <strong>
                  {sameDevice ? (index === 0 ? "Sol" : "Sağ") + " · " : ""}
                  {device?.name || "Cihaz"}
                </strong>
                <select
                  aria-label={`${sameDevice ? (index === 0 ? "Sol" : "Sağ") : device?.name} config dosyası`}
                  value={choices[key] || ""}
                  onChange={(e) => choose(key, e.target.value)}
                >
                  <option value="">Config dosyası seçin</option>
                  {(snapshots[deviceId] || []).map((s) => (
                    <option key={s.id} value={s.id}>
                      {date(s.created_at)}
                      {s.is_base ? " · Base config" : ""}
                    </option>
                  ))}
                </select>
              </label>
            );
          })}
        </div>
      )}
      <button
        className="primary"
        disabled={!ready || busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            setResult(
              await api("/configuration/compare", "POST", {
                snapshot_ids: keys.map((k) => choices[k]),
                distinct_devices: !sameDevice,
              }),
            );
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Karşılaştırılıyor…" : "Karşılaştır"}
      </button>
      {result && <ConfigEditors result={result} />}
      {picking && (
        <Dialog
          title={sameDevice ? "Cihaz seç" : "Karşılaştırılacak cihazları seç"}
          onClose={() => setPicking(false)}
        >
          <label>
            Cihaz ara
            <input value={search} onChange={(e) => setSearch(e.target.value)} />
          </label>
          <div className="config-device-picker">
            {devices
              .filter((d) =>
                `${d.name} ${d.management_ip}`
                  .toLocaleLowerCase("tr")
                  .includes(search.toLocaleLowerCase("tr")),
              )
              .map((d) => (
                <label key={d.id}>
                  <input
                    type={sameDevice ? "radio" : "checkbox"}
                    name="comparison-device"
                    checked={selected.includes(d.id)}
                    disabled={
                      !sameDevice &&
                      selected.length >= 4 &&
                      !selected.includes(d.id)
                    }
                    onChange={(e) =>
                      setSelected(
                        sameDevice
                          ? [d.id]
                          : e.target.checked
                            ? [...selected, d.id]
                            : selected.filter((id) => id !== d.id),
                      )
                    }
                  />
                  <span>
                    <strong>{d.name}</strong>
                    <small>{d.management_ip}</small>
                  </span>
                </label>
              ))}
          </div>
          {!devices.length && (
            <p>Kayıtlı konfigürasyonu olan cihaz bulunamadı.</p>
          )}
          <div className="dialog-footer">
            <span role="status">{selected.length} cihaz seçildi</span>
            <button
              className="primary"
              disabled={
                sameDevice ? selected.length !== 1 : selected.length < 2
              }
              onClick={() => setPicking(false)}
            >
              Seçimi uygula
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

export function BackupWorkspace({
  page,
  refresh,
  user,
  onSaved,
  onDeviceChange,
}: {
  page: string;
  refresh: number;
  user: Row;
  onSaved: () => void;
  onDeviceChange: (device: Row | null) => void;
}) {
  const [device, setDevice] = useState<Row | null>(null);
  const [view, setView] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    onDeviceChange(device);
    return () => onDeviceChange(null);
  }, [device, onDeviceChange]);
  useEffect(() => {
    heading.current?.focus();
  }, [device?.id]);
  const action = async (row: Row, kind: string) => {
    setError("");
    if (["delete", "base", "approve"].includes(kind)) {
      setView({ row, kind });
      return;
    }
    setBusy(true);
    try {
      if (kind === "diff") {
        const diff = await api(`/snapshots/${row.id}/diff`);
        if (!diff.previous_id || diff.previous_id === row.id)
          setView({
            row,
            kind: "content",
            content: "Bu dosya base config; karşılaştırılacak fark yok.",
          });
        else
          setView({
            row,
            kind,
            result: await api("/configuration/compare", "POST", {
              snapshot_ids: [diff.previous_id, row.id],
            }),
          });
      } else {
        const data = await api(`/snapshots/${row.id}/content`);
        if (kind === "download") {
          const url = URL.createObjectURL(
            new Blob([data.content], { type: "text/plain;charset=utf-8" }),
          );
          const a = document.createElement("a");
          a.href = url;
          a.download = `netrix-${row.id}-masked.txt`;
          a.click();
          URL.revokeObjectURL(url);
        } else setView({ row, kind, content: data.content });
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  if (page === "backup-compare") return <ConfigComparison />;
  return (
    <>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {busy && !view && <p role="status">Konfigürasyon okunuyor…</p>}
      {page === "backup-changes" && (
        <p className="info-note">
          Base config ile son konfigürasyon karşılaştırılır. Dosya sürüm
          üstbilgileri dikkate alınmaz. Onay, base config seçimini değiştirmez.
        </p>
      )}
      {page === "configuration" && device && (
        <div className="inventory-breadcrumb backup-device-heading">
          <button className="secondary" onClick={() => setDevice(null)}>
            <ArrowLeft size={18} aria-hidden="true" />
            Cihazlara dön
          </button>
          <div>
            <h2 tabIndex={-1} ref={heading}>
              {device.name}
            </h2>
            <p>{device.management_ip}</p>
          </div>
        </div>
      )}
      {page === "configuration" && !device ? (
        <InventoryTable
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
          wide={view.kind === "diff"}
          title={
            (
              {
                base: "Base config seç",
                approve: "Konfigürasyon değişikliğini onayla",
                delete: "Konfigürasyonu sil",
                diff: "Base config / Son config",
              } as Row
            )[view.kind] || "Cihaz konfigürasyonu"
          }
          onClose={() => setView(null)}
        >
          <div className="backup-result">
            <p>
              <b>{view.row.device_name}</b> · {date(view.row.created_at)}
            </p>
            {["base", "approve", "delete"].includes(view.kind) ? (
              <>
                <p>
                  {view.kind === "base"
                    ? "Bu dosya cihazın base config’i olacak. Değişiklikler bu dosyaya göre yeniden hesaplanacak."
                    : view.kind === "approve"
                      ? "Bu konfigürasyondaki farklar onaylanacak ve Değişenler listesinden kaldırılacak."
                      : "Bu konfigürasyon dosyası kalıcı olarak silinecek."}
                </p>
                <div className="dialog-footer">
                  <button className="secondary" onClick={() => setView(null)}>
                    Vazgeç
                  </button>
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await api(
                          `/snapshots/${view.row.id}${view.kind === "delete" ? "" : "/" + view.kind}`,
                          view.kind === "delete" ? "DELETE" : "POST",
                        );
                        onSaved();
                        setView(null);
                      } catch (e: any) {
                        setError(e.message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    {view.kind === "base"
                      ? "Base config yap"
                      : view.kind === "approve"
                        ? "Onayla"
                        : "Sil"}
                  </button>
                </div>
              </>
            ) : view.result ? (
              <ConfigEditors result={view.result} />
            ) : (
              <pre>{view.content}</pre>
            )}
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
          </div>
        </Dialog>
      )}
    </>
  );
}
