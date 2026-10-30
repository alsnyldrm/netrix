import { useEffect, useId, useRef, useState } from "react";
import {
  CaretDown,
  DownloadSimple,
  PlugsConnected,
  UploadSimple,
} from "@phosphor-icons/react";
import { api, Dialog, tag } from "./main";

export type TransferFormat = "csv" | "xlsx";
type TestRow = {
  device_id: string;
  name: string;
  management_ip: string;
  protocol: string;
  job_id: string | null;
  status: string;
  message: string;
};
type Report = {
  tests?: TestRow[];
  total: number;
  valid: number;
  imported: number;
  errors: { row: number; field: string; message: string }[];
  preview: { row: number; name: string; management_ip: string; kind: string }[];
};

export async function downloadDevices(format: TransferFormat, ids?: string[]) {
  const response = await fetch(
    `/api/v1/inventory/devices/${format}/${ids ? "export" : "template"}`,
    {
      method: ids ? "POST" : "GET",
      headers: { "Content-Type": "application/json", "X-Netrix-Request": "1" },
      ...(ids ? { body: JSON.stringify({ ids }) } : {}),
    },
  );
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("netrix:session-expired"));
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string" ? error.detail : "Dosya indirilemedi",
    );
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = `${ids ? "netrix-cihazlar" : "netrix-cihaz-sablonu"}.${format}`;
  link.click();
  URL.revokeObjectURL(url);
}

export function DeviceTransferImport({
  format,
  onClose,
  onSaved,
}: {
  format: TransferFormat;
  onClose: () => void;
  onSaved: () => void;
}) {
  const label = format.toUpperCase();
  const [showTests, setShowTests] = useState(false);
  const [content, setContent] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const inspect = async (file?: File) => {
    setReport(null);
    setContent("");
    setError("");
    setDone(false);
    if (!file) return;
    setBusy(true);
    try {
      if (file.size > 1024 * 1024)
        throw new Error(`${label} dosyası en fazla 1 MiB olabilir.`);
      let text: string;
      try {
        if (!file.name.toLowerCase().endsWith(`.${format}`))
          throw new Error("format");
        const bytes = new Uint8Array(await file.arrayBuffer());
        if (format === "xlsx") {
          let binary = "";
          for (let i = 0; i < bytes.length; i += 8192)
            binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
          text = btoa(binary);
        } else text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      } catch {
        throw new Error(
          format === "csv"
            ? "Dosya UTF-8 CSV biçiminde olmalı."
            : "XLSX dosyası seçin.",
        );
      }
      const result = await api(`/inventory/devices/${format}/import`, "POST", {
        content: text,
      });
      setContent(text);
      setReport(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  if (showTests && report?.tests)
    return (
      <ImportTestResults
        rows={report.tests}
        imported={report.imported}
        onClose={onClose}
      />
    );
  return (
    <Dialog
      title={`Cihazları ${label} ile içeri aktar`}
      wide
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="csv-import"
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy || done || !report || report.errors.length || !content)
            return;
          const testAfter =
            (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value") ===
            "test";
          setBusy(true);
          setError("");
          try {
            const result = await api(
              `/inventory/devices/${format}/import`,
              "POST",
              {
                content,
                apply: true,
                test_after: testAfter,
              },
            );
            setReport(result);
            if (result.imported) {
              setDone(true);
              setShowTests(testAfter);
              setContent("");
              onSaved();
            }
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="csv-intro">
          <p>
            Şablonu doldurup dosyanızı seçin. Önizlemeyi kontrol ettikten sonra
            cihazları birlikte ekleyin.
          </p>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={async () => {
              try {
                await downloadDevices(format);
              } catch (e: any) {
                setError(e.message);
              }
            }}
          >
            <DownloadSimple size={18} aria-hidden="true" />
            {label} şablonu indir
          </button>
        </div>
        <label className="csv-file">
          <span id="csv-file-label">{label} dosyası</span>
          <input
            aria-labelledby="csv-file-label"
            type="file"
            accept={
              format === "csv"
                ? ".csv,text/csv"
                : ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            }
            disabled={busy}
            aria-describedby="csv-file-hint"
            onChange={(e) => inspect(e.target.files?.[0])}
          />
          <small id="csv-file-hint">
            {format === "csv"
              ? "UTF-8 · Virgül, noktalı virgül veya sekme"
              : "Excel çalışma kitabı · Cihazlar sayfası"}{" "}
            · En fazla 500 cihaz / 1 MiB
          </small>
        </label>
        <p className="csv-help">
          <strong>
            Zorunlu alanlar (*): Cihaz adı, Yönetim IP adresi ve VRF.
          </strong>{" "}
          Diğer alanlar isteğe bağlıdır; boş bırakabilirsiniz. VRF, lokasyon,
          yedek grubu ve erişim profilleri için kayıtlı adları veya kimlikleri
          kullanın. Parola ve anahtar sütunları boş veya yıldızlı olmalıdır;
          erişim bilgileri Erişim kasasındaki profillerden alınır.
        </p>
        <p className="csv-help">
          Yeni cihazlar eklenir. Aynı VRF ve IP adresindeki mevcut cihazlar
          değiştirilmez. Hatalı satır varsa dosyanın tamamını düzeltip yeniden
          seçin.
        </p>
        <p className="csv-help">
          İçeri Aktar ve Test Et, kayıt sonrası atanmış SNMP ve SSH/API
          profillerini test eder. Etkin cihaz ve yetkili ağ kapsamı gerekir.
          Sonuçlar ayrı pencerede gösterilir.
        </p>
        {busy && <p role="status">{label} işleniyor…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {report && (
          <>
            <p className="csv-summary" role="status">
              {done
                ? `${report.imported} cihaz içeri aktarıldı.`
                : `${report.total} satır · ${report.valid} geçerli · ${new Set(report.errors.map((e) => e.row)).size} hatalı satır`}
            </p>
            {report.errors.length > 0 ? (
              <div
                className="csv-preview"
                tabIndex={0}
                role="region"
                aria-label={`${label} satır hataları`}
              >
                <table>
                  <thead>
                    <tr>
                      <th>Satır</th>
                      <th>Alan</th>
                      <th>Hata</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.errors.map((item, i) => (
                      <tr key={i}>
                        <td>{item.row}</td>
                        <td>{item.field}</td>
                        <td>{item.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              !done && (
                <div
                  className="csv-preview"
                  tabIndex={0}
                  role="region"
                  aria-label={`${label} önizlemesi`}
                >
                  <table>
                    <thead>
                      <tr>
                        <th>Satır</th>
                        <th>Cihaz adı</th>
                        <th>Yönetim IP adresi</th>
                        <th>Cihaz türü</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.preview.map((item) => (
                        <tr key={item.row}>
                          <td>{item.row}</td>
                          <td>{item.name}</td>
                          <td>{item.management_ip}</td>
                          <td>{tag(item.kind)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )}
          </>
        )}
        <div className="dialog-footer csv-footer">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onClose}
          >
            {done ? "Kapat" : "Vazgeç"}
          </button>
          {!done && (
            <>
              <button
                className="secondary"
                type="submit"
                value="import"
                disabled={busy || !report || !!report.errors.length || !content}
              >
                <UploadSimple size={18} aria-hidden="true" /> İçeri Aktar
              </button>
              <button
                className="primary"
                type="submit"
                value="test"
                disabled={busy || !report || !!report.errors.length || !content}
              >
                <PlugsConnected size={18} aria-hidden="true" /> İçeri Aktar ve
                Test Et
              </button>
            </>
          )}
        </div>
      </form>
    </Dialog>
  );
}

export function TransferMenu({
  mode,
  disabled,
  onSelect,
}: {
  mode: "import" | "export";
  disabled?: boolean;
  onSelect: (format: TransferFormat) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  const title = mode === "import" ? "İçeri Aktar" : "Dışarı Aktar";
  useEffect(() => {
    if (!open) return;
    root.current
      ?.querySelector<HTMLButtonElement>('[role="menuitem"]')
      ?.focus();
    const dismiss = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, [open]);
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  return (
    <div
      className="transfer-menu"
      ref={root}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      <button
        ref={trigger}
        className="secondary"
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        {mode === "import" ? (
          <UploadSimple size={18} aria-hidden="true" />
        ) : (
          <DownloadSimple size={18} aria-hidden="true" />
        )}
        {title}
        <CaretDown size={16} aria-hidden="true" />
      </button>
      {open && (
        <div
          className="transfer-options"
          role="menu"
          aria-label={`${title} biçimi`}
          id={id}
          onKeyDown={(e) => {
            const items = Array.from(
              e.currentTarget.querySelectorAll<HTMLButtonElement>(
                '[role="menuitem"]',
              ),
            );
            const index = items.indexOf(
              document.activeElement as HTMLButtonElement,
            );
            if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
              e.preventDefault();
              items[
                e.key === "Home"
                  ? 0
                  : e.key === "End"
                    ? items.length - 1
                    : (index +
                        (e.key === "ArrowDown" ? 1 : -1) +
                        items.length) %
                      items.length
              ]?.focus();
            } else if (e.key === "Escape") {
              e.preventDefault();
              e.stopPropagation();
              setOpen(false);
              trigger.current?.focus();
            }
          }}
        >
          {(["csv", "xlsx"] as TransferFormat[]).map((format) => (
            <button
              key={format}
              type="button"
              role="menuitem"
              tabIndex={-1}
              onClick={() => {
                setOpen(false);
                trigger.current?.focus();
                onSelect(format);
              }}
            >
              {format.toUpperCase()}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ImportTestResults({
  rows,
  imported,
  onClose,
}: {
  rows: TestRow[];
  imported: number;
  onClose: () => void;
}) {
  const [results, setResults] = useState(rows);
  const [error, setError] = useState("");
  const ids = rows
    .filter((row) => row.job_id)
    .map((row) => row.job_id)
    .join(",");
  useEffect(() => {
    if (!ids) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const updates: Pick<TestRow, "job_id" | "status" | "message">[] =
          await api("/inventory/devices/import-tests/status", "POST", {
            ids: ids.split(","),
          });
        if (!active) return;
        const byId = new Map(updates.map((row) => [row.job_id, row]));
        setResults((current) =>
          current.map((row) => ({
            ...row,
            ...(row.job_id ? byId.get(row.job_id) : {}),
          })),
        );
        setError("");
        if (updates.some((row) => ["queued", "running"].includes(row.status)))
          timer = setTimeout(poll, 2000);
      } catch (e: any) {
        if (active) {
          setError(e.message);
          timer = setTimeout(poll, 5000);
        }
      }
    };
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [ids]);
  const grouped = new Map<string, TestRow[]>();
  results.forEach((row) =>
    grouped.set(row.device_id, [...(grouped.get(row.device_id) || []), row]),
  );
  const counts = { succeeded: 0, failed: 0, pending: 0, skipped: 0 };
  grouped.forEach((device) => {
    if (device.some((row) => ["queued", "running"].includes(row.status)))
      counts.pending++;
    else if (device.some((row) => ["failed", "partial"].includes(row.status)))
      counts.failed++;
    else if (device.every((row) => row.status === "succeeded"))
      counts.succeeded++;
    else counts.skipped++;
  });
  const labels: Record<string, string> = {
    succeeded: "Başarılı",
    failed: "Başarısız",
    partial: "Başarısız",
    queued: "Sırada",
    running: "Test ediliyor",
    skipped: "Test edilemedi",
    cancelled: "İptal edildi",
  };
  return (
    <Dialog
      title="İçe aktarma · Bağlantı testi sonuçları"
      wide
      onClose={onClose}
    >
      <div className="import-test-body">
        <p>
          {imported} cihaz içeri aktarıldı. Her cihazın atanmış erişim
          profilleri ayrı ayrı test edilir.
        </p>
        <p className="csv-summary" role="status">
          {counts.succeeded} başarılı · {counts.failed} başarısız ·{" "}
          {counts.pending} bekleyen · {counts.skipped} test edilemedi
        </p>
        {error && (
          <p role="alert" className="error">
            Sonuçlar güncellenemedi: {error}. Yeniden deneniyor.
          </p>
        )}
        <div
          className="csv-preview import-test-table"
          tabIndex={0}
          role="region"
          aria-label="Cihaz bağlantı testi sonuçları"
        >
          <table>
            <thead>
              <tr>
                <th>Cihaz</th>
                <th>Protokol</th>
                <th>Durum</th>
                <th>Açıklama</th>
              </tr>
            </thead>
            <tbody>
              {results.map((row, i) => (
                <tr key={row.job_id || `${row.device_id}-${i}`}>
                  <td>
                    <b>{row.name}</b>
                    <br />
                    <span className="mono muted">{row.management_ip}</span>
                  </td>
                  <td>{row.protocol}</td>
                  <td>
                    <span
                      className="import-test-status"
                      data-state={row.status}
                    >
                      {labels[row.status] || row.status}
                    </span>
                  </td>
                  <td>{row.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="csv-help">
          Başarısız testler eklenen cihazları silmez. Pencereyi kapatsanız da
          testler sürer; sonuçları Görev merkezinden izleyebilirsiniz.
        </p>
        <div className="dialog-footer">
          <button type="button" className="secondary" onClick={onClose}>
            Kapat
          </button>
        </div>
      </div>
    </Dialog>
  );
}
