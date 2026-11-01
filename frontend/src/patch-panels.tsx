import { cloneElement, useEffect, useRef, useState } from "react";
import { api, useLiveQuery } from "./data";
import { Dialog } from "./main";
import { allRows } from "./inventory";
import "./patch-panels.css";

type Row = Record<string, any>;
export const panelKind = (kind: string) =>
  kind === "fiber" ? "Fiber Patch Panel" : "CAT Patch Panel";
const cables: Record<string, string[]> = {
  cat: ["Cat5", "Cat6", "Cat7"],
  fiber: ["OM3", "OM4"],
};
const fiberModes: Record<string, string> = {
  multimode: "Multimode (MM)",
  singlemode: "Singlemode (SM)",
};
const cableLabel = (port: Row) =>
  [port.cable_model, fiberModes[port.fiber_mode]].filter(Boolean).join(" · ");
const defaults = {
  name: "",
  kind: "cat",
  start_unit: 1,
  units: 1,
  port_count: 24,
};
function Field({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: React.ReactElement<any>;
  wide?: boolean;
}) {
  return (
    <label className={`ipam-field${wide ? " patch-wide" : ""}`}>
      <span>{label}</span>
      {cloneElement(children, { "aria-label": label })}
    </label>
  );
}

export function PatchPanels({
  cabinet,
  panels,
  user,
  saved,
  open,
}: {
  cabinet: Row;
  panels: Row[];
  user: Row;
  saved: () => void;
  open: (panel: Row) => void;
}) {
  const [values, setValues] = useState<Row>(defaults);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [removing, setRemoving] = useState<Row | null>(null);
  const base = `/ipam/cabinets/${cabinet.id}/patch-panels`;
  const writable = user.role !== "viewer";
  const set = (key: string, value: any) => {
    setValues((v) => ({ ...v, [key]: value }));
    setNotice("");
  };
  return (
    <section className="patch-section" aria-labelledby="patch-title">
      <h3 id="patch-title">Patch paneller</h3>
      <p className="ipam-hint">
        CAT ve fiber panelleri U konumuna yerleştirin. Port numaraları, cihaz
        bağlantıları ve kablo bilgileri elle kaydedilir.
      </p>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {notice && <p role="status">{notice}</p>}
      <div className="patch-panel-list">
        {panels.map((panel) => (
          <div className="patch-panel-card" key={panel.id}>
            <div>
              <strong>{panel.name}</strong>
              <small>
                {panelKind(panel.kind)} · {panel.start_unit}–
                {panel.start_unit + panel.units - 1} U · {panel.port_count} port
              </small>
            </div>
            <div className="ipam-actions">
              <button
                type="button"
                className="secondary"
                onClick={() => open(panel)}
                aria-label={`${panel.name} portlarını aç`}
              >
                Portlar
              </button>
              {writable && (
                <>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => {
                      setValues(panel);
                      setError("");
                    }}
                    aria-label={`${panel.name} panelini düzenle`}
                  >
                    Düzenle
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => setRemoving(panel)}
                    aria-label={`${panel.name} panelini sil`}
                  >
                    Sil
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
        {!panels.length && (
          <p className="ipam-hint">Henüz patch panel eklenmedi.</p>
        )}
      </div>
      {writable && (
        <form
          className="patch-form"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            setNotice("");
            try {
              const panel = await api(
                base + (values.id ? `/${values.id}` : ""),
                values.id ? "PUT" : "POST",
                Object.fromEntries(
                  Object.keys(defaults).map((k) => [k, values[k]]),
                ),
              );
              setValues(defaults);
              setNotice("Patch panel kaydedildi.");
              saved();
              if (!values.id) open(panel);
            } catch (e: any) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Panel adı">
            <input
              required
              maxLength={120}
              value={values.name}
              onChange={(e) => set("name", e.target.value)}
            />
          </Field>
          <Field label="Panel türü">
            <select
              value={values.kind}
              onChange={(e) => {
                set("kind", e.target.value);
                if (!values.id)
                  set("port_count", e.target.value === "fiber" ? 12 : 24);
              }}
            >
              <option value="cat">CAT Patch Panel</option>
              <option value="fiber">Fiber Patch Panel</option>
            </select>
          </Field>
          <Field label="Panel başlangıç U">
            <input
              type="number"
              required
              min={1}
              max={cabinet.units}
              value={values.start_unit}
              onChange={(e) => set("start_unit", Number(e.target.value))}
            />
          </Field>
          <Field label="Panel yüksekliği (U)">
            <input
              type="number"
              required
              min={1}
              max={cabinet.units}
              value={values.units}
              onChange={(e) => set("units", Number(e.target.value))}
            />
          </Field>
          <Field label="Port sayısı">
            <input
              type="number"
              required
              min={1}
              max={288}
              value={values.port_count}
              onChange={(e) => set("port_count", Number(e.target.value))}
            />
          </Field>
          <div className="ipam-actions">
            <button className="primary" disabled={busy}>
              {busy
                ? "Kaydediliyor…"
                : values.id
                  ? "Paneli güncelle"
                  : "Patch panel ekle"}
            </button>
            {values.id && (
              <button
                type="button"
                className="secondary"
                onClick={() => setValues(defaults)}
              >
                Vazgeç
              </button>
            )}
          </div>
        </form>
      )}
      {removing && (
        <Dialog
          title="Patch paneli sil"
          onClose={() => !busy && setRemoving(null)}
        >
          <div className="patch-section">
            <p>
              <strong>{removing.name}</strong> ve bu panelin tüm port/kablo
              kayıtları silinecek. Bağlı envanter cihazları korunur.
            </p>
            <div className="ipam-actions">
              <button
                className="secondary"
                disabled={busy}
                onClick={() => setRemoving(null)}
              >
                Vazgeç
              </button>
              <button
                className="primary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    await api(`${base}/${removing.id}`, "DELETE");
                    setRemoving(null);
                    saved();
                    setNotice("Patch panel kaldırıldı.");
                  } catch (e: any) {
                    setError(e.message);
                    setRemoving(null);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Silmeyi onayla
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </section>
  );
}

export function PatchPorts({
  cabinet,
  panel,
  devices,
  user,
  close,
  saved,
}: {
  cabinet: Row;
  panel: Row;
  devices: Row[];
  user: Row;
  close: () => void;
  saved: () => void;
}) {
  const [refresh, setRefresh] = useState(0);
  const editor = useRef<HTMLHeadingElement>(null);
  const base = `/ipam/cabinets/${cabinet.id}/patch-panels/${panel.id}/ports`;
  const listing = useLiveQuery(base, refresh);
  const [selected, setSelected] = useState<Row | null>(null);
  useEffect(() => {
    editor.current?.focus();
  }, [selected?.id]);
  const [values, setValues] = useState<Row>({});
  const [deviceMode, setDeviceMode] = useState("inventory");
  const [portMode, setPortMode] = useState("inventory");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [portSearch, setPortSearch] = useState("");
  const interfaces = useLiveQuery<Row[]>(
    values.device_id ? `patch-interfaces:${values.device_id}` : null,
    0,
    () =>
      allRows(
        `/inventory/interfaces?candidates=true&device_id=${encodeURIComponent(values.device_id)}`,
      ),
  );
  const rows: Row[] = listing.data?.items || [];
  const choose = (port: Row) => {
    setSelected(port);
    setValues(port);
    setError("");
    setNotice("");
    setDeviceMode(port.device_id || !port.device_name ? "inventory" : "manual");
    setPortMode(port.interface_id || !port.port_name ? "inventory" : "manual");
  };
  const set = (key: string, value: any) =>
    setValues((v) => ({ ...v, [key]: value }));
  return (
    <Dialog
      title={`${panel.name} · ${panelKind(panel.kind)}`}
      onClose={close}
      wide
    >
      <div className="patch-section">
        <p className="ipam-hint">
          Kabinet {cabinet.name} · {panel.start_unit} U · {panel.port_count}{" "}
          port. Düzenlemek için port numarasına tıklayın.
        </p>
        {(error || listing.error || interfaces.error) && (
          <div className="error" role="alert">
            {error || listing.error || interfaces.error}
          </div>
        )}
        {notice && <p role="status">{notice}</p>}
        {listing.loading && <p role="status">Panel portları yükleniyor…</p>}
        <Field label="Panel portlarında ara">
          <input
            type="search"
            value={portSearch}
            onChange={(e) => setPortSearch(e.target.value)}
            placeholder="Port, cihaz veya kablo…"
          />
        </Field>
        <div
          className="patch-port-grid"
          role="group"
          aria-label="Patch panel portları"
        >
          {rows
            .filter((p) =>
              [p.number, p.device_name, p.port_name, cableLabel(p)]
                .join(" ")
                .toLocaleLowerCase("tr")
                .includes(portSearch.toLocaleLowerCase("tr")),
            )
            .map((port) => (
              <button
                type="button"
                key={port.id}
                className={`patch-port ${port.device_name ? "connected" : ""} ${selected?.id === port.id ? "selected" : ""}`}
                aria-pressed={selected?.id === port.id}
                aria-label={`Port ${port.number}${port.device_name ? ` · ${port.device_name} · ${port.port_name}` : " · Boş"}`}
                onClick={() => choose(port)}
              >
                <strong>{port.number}</strong>
                <span>{port.device_name || "Boş"}</span>
                <small>
                  {port.port_name || "—"} ·{" "}
                  {cableLabel(port) || "Kablo seçilmedi"}
                </small>
              </button>
            ))}
        </div>
        {selected && (
          <form
            className="patch-form"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              setNotice("");
              try {
                const updated = await api(`${base}/${selected.id}`, "PUT", {
                  number: values.number,
                  device_id:
                    deviceMode === "inventory"
                      ? values.device_id || null
                      : null,
                  interface_id:
                    deviceMode === "inventory" && portMode === "inventory"
                      ? values.interface_id || null
                      : null,
                  device_name:
                    deviceMode === "manual" ? values.device_name || "" : "",
                  port_name:
                    portMode === "manual" || deviceMode === "manual"
                      ? values.port_name || ""
                      : "",
                  cable_model: values.cable_model || "",
                  fiber_mode: values.fiber_mode || "",
                });
                setValues(updated);
                setSelected(updated);
                setRefresh((v) => v + 1);
                saved();
                setNotice(`Port ${updated.number} kaydedildi.`);
              } catch (e: any) {
                setError(e.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <h3 className="patch-wide" ref={editor} tabIndex={-1}>
              Port {selected.number} bağlantısı
            </h3>
            <Field label="Port numarası" wide={panel.kind === "fiber"}>
              <input
                required
                maxLength={40}
                value={values.number}
                onChange={(e) => set("number", e.target.value)}
                readOnly={user.role === "viewer"}
              />
            </Field>
            <Field label="Kablo modeli">
              <select
                disabled={user.role === "viewer"}
                value={values.cable_model || ""}
                onChange={(e) => set("cable_model", e.target.value)}
              >
                <option value="">Seçilmedi</option>
                {cables[panel.kind].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </Field>
            {panel.kind === "fiber" && (
              <Field label="Fiber türü">
                <select
                  disabled={user.role === "viewer"}
                  value={values.fiber_mode || ""}
                  onChange={(e) => set("fiber_mode", e.target.value)}
                >
                  <option value="">Seçilmedi</option>
                  {Object.entries(fiberModes).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="Cihaz girişi">
              <select
                disabled={user.role === "viewer"}
                value={deviceMode}
                onChange={(e) => {
                  setDeviceMode(e.target.value);
                  setValues((v) => ({
                    ...v,
                    device_id: "",
                    device_name: "",
                    interface_id: "",
                    port_name: "",
                  }));
                }}
              >
                <option value="inventory">Envanterden seç</option>
                <option value="manual">Manuel gir</option>
              </select>
            </Field>
            {deviceMode === "inventory" ? (
              <>
                <Field label="Envanter cihazlarında ara">
                  <input
                    type="search"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </Field>
                <Field label="Bağlı cihaz">
                  <select
                    disabled={user.role === "viewer"}
                    value={values.device_id || ""}
                    onChange={(e) =>
                      setValues((v) => ({
                        ...v,
                        device_id: e.target.value,
                        interface_id: "",
                        port_name: "",
                      }))
                    }
                  >
                    <option value="">Seçilmedi</option>
                    {values.device_id &&
                      !devices.some((d) => d.id === values.device_id) && (
                        <option value={values.device_id}>
                          {values.device_name || "Önceki cihaz"}
                        </option>
                      )}
                    {devices
                      .filter(
                        (d) =>
                          d.id === values.device_id ||
                          [d.name, d.management_ip]
                            .join(" ")
                            .toLocaleLowerCase("tr")
                            .includes(search.toLocaleLowerCase("tr")),
                      )
                      .map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name} · {d.management_ip}
                        </option>
                      ))}
                  </select>
                </Field>
              </>
            ) : (
              <Field label="Bağlı cihaz adı / IP">
                <input
                  maxLength={190}
                  readOnly={user.role === "viewer"}
                  value={values.device_name || ""}
                  onChange={(e) => set("device_name", e.target.value)}
                />
              </Field>
            )}
            {deviceMode === "inventory" && (
              <Field label="Cihaz portu girişi">
                <select
                  disabled={user.role === "viewer"}
                  value={portMode}
                  onChange={(e) => {
                    setPortMode(e.target.value);
                    set("interface_id", "");
                    set("port_name", "");
                  }}
                >
                  <option value="inventory">Envanterden seç</option>
                  <option value="manual">Manuel gir</option>
                </select>
              </Field>
            )}
            {deviceMode === "inventory" && portMode === "inventory" ? (
              <Field label="Bağlı cihaz portu">
                <select
                  disabled={
                    user.role === "viewer" ||
                    !values.device_id ||
                    interfaces.loading
                  }
                  value={values.interface_id || ""}
                  onChange={(e) => set("interface_id", e.target.value)}
                >
                  <option value="">
                    {interfaces.loading ? "Portlar yükleniyor…" : "Seçilmedi"}
                  </option>
                  {values.interface_id &&
                    !interfaces.loading &&
                    !(interfaces.data || []).some(
                      (p) => p.id === values.interface_id && !p.is_deleted,
                    ) && (
                      <option value={values.interface_id}>
                        {values.port_name || "Önceki port"}
                      </option>
                    )}
                  {(interfaces.data || [])
                    .filter((p) => !p.is_deleted)
                    .map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                </select>
              </Field>
            ) : (
              <Field label="Bağlı cihaz portu (manuel)">
                <input
                  maxLength={120}
                  readOnly={user.role === "viewer"}
                  value={values.port_name || ""}
                  onChange={(e) => set("port_name", e.target.value)}
                />
              </Field>
            )}
            {user.role !== "viewer" && (
              <div className="ipam-actions patch-wide">
                <button
                  className="primary"
                  disabled={busy || interfaces.loading}
                >
                  {busy ? "Kaydediliyor…" : "Port bağlantısını kaydet"}
                </button>
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    setValues((v) => ({
                      ...v,
                      device_id: "",
                      interface_id: "",
                      device_name: "",
                      port_name: "",
                      cable_model: "",
                      fiber_mode: "",
                    }))
                  }
                >
                  Bağlantıyı temizle
                </button>
              </div>
            )}
          </form>
        )}
      </div>
    </Dialog>
  );
}

export function DevicePatchInfo({
  deviceId,
  refresh,
}: {
  deviceId: string;
  refresh: number;
}) {
  const query = useLiveQuery(`/devices/${deviceId}/patch-ports`, refresh);
  return (
    <section
      className="patch-device-section"
      aria-labelledby="device-patch-title"
    >
      <h3 id="device-patch-title">Patch bilgileri</h3>
      {query.error && (
        <p className="error" role="alert">
          {query.error}
        </p>
      )}
      {query.loading ? (
        <p role="status">Patch bilgileri yükleniyor…</p>
      ) : query.data?.items.length ? (
        <div
          className="table-scroll"
          role="region"
          tabIndex={0}
          aria-label="Cihaz patch bağlantıları"
        >
          <table>
            <thead>
              <tr>
                {[
                  "Kabinet",
                  "Patch panel",
                  "U",
                  "Panel portu",
                  "Cihaz portu",
                  "Kablo modeli",
                  "Fiber türü",
                ].map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((r: Row) => (
                <tr key={r.id}>
                  <td>{r.cabinet_name}</td>
                  <td>
                    {r.panel_name}
                    <small className="ipam-sub">{panelKind(r.kind)}</small>
                  </td>
                  <td>{r.start_unit}</td>
                  <td>{r.number}</td>
                  <td>{r.port_name || "—"}</td>
                  <td>{r.cable_model || "—"}</td>
                  <td>{fiberModes[r.fiber_mode] || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="ipam-hint">
          Bu cihaz için patch bağlantısı kaydedilmedi.
        </p>
      )}
    </section>
  );
}
