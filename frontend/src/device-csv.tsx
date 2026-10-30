import { useState } from "react";
import { DownloadSimple, UploadSimple } from "@phosphor-icons/react";
import { api, Dialog, tag } from "./main";

type Report = {
  total: number;
  valid: number;
  imported: number;
  errors: { row: number; field: string; message: string }[];
  preview: { row: number; name: string; management_ip: string; kind: string }[];
};

export async function downloadDeviceCSV(ids?: string[]) {
  const response = await fetch(
    `/api/v1/inventory/devices/csv/${ids ? "export" : "template"}`,
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
      typeof error.detail === "string" ? error.detail : "CSV indirilemedi",
    );
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = ids ? "netrix-cihazlar.csv" : "netrix-cihaz-sablonu.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export function DeviceCSVImport({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
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
        throw new Error("CSV dosyası en fazla 1 MiB olabilir.");
      let text: string;
      try {
        text = new TextDecoder("utf-8", { fatal: true }).decode(
          await file.arrayBuffer(),
        );
      } catch {
        throw new Error("Dosya UTF-8 CSV biçiminde olmalı.");
      }
      const result = await api("/inventory/devices/csv/import", "POST", {
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
  return (
    <Dialog
      title="Cihazları CSV ile içeri aktar"
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
          setBusy(true);
          setError("");
          try {
            const result = await api("/inventory/devices/csv/import", "POST", {
              content,
              apply: true,
            });
            setReport(result);
            if (result.imported) {
              setDone(true);
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
                await downloadDeviceCSV();
              } catch (e: any) {
                setError(e.message);
              }
            }}
          >
            <DownloadSimple size={18} aria-hidden="true" />
            CSV şablonu indir
          </button>
        </div>
        <label className="csv-file">
          <span id="csv-file-label">CSV dosyası</span>
          <input
            aria-labelledby="csv-file-label"
            type="file"
            accept=".csv,text/csv"
            disabled={busy}
            aria-describedby="csv-file-hint"
            onChange={(e) => inspect(e.target.files?.[0])}
          />
          <small id="csv-file-hint">
            UTF-8 · Virgül, noktalı virgül veya sekme · En fazla 500 cihaz / 1
            MiB
          </small>
        </label>
        <p className="csv-help">
          Cihaz adı, Yönetim IP adresi ve VRF zorunludur. VRF, lokasyon, yedek
          grubu ve erişim profilleri için kayıtlı adları veya kimlikleri
          kullanın. Parola ve anahtar sütunları boş veya yıldızlı olmalıdır;
          erişim bilgileri Erişim kasasındaki profillerden alınır.
        </p>
        <p className="csv-help">
          Yeni cihazlar eklenir. Aynı VRF ve IP adresindeki mevcut cihazlar
          değiştirilmez. Hatalı satır varsa dosyanın tamamını düzeltip yeniden
          seçin.
        </p>
        {busy && <p role="status">CSV işleniyor…</p>}
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
                aria-label="CSV satır hataları"
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
                  aria-label="CSV önizlemesi"
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
            <button
              className="primary"
              disabled={busy || !report || !!report.errors.length || !content}
            >
              <UploadSimple size={18} aria-hidden="true" />
              {report && !report.errors.length
                ? `${report.valid} cihazı içeri aktar`
                : "İçeri aktar"}
            </button>
          )}
        </div>
      </form>
    </Dialog>
  );
}
