import { cloneElement, useEffect, useRef, useState } from "react";
import { api, useLiveQuery } from "./data";
import { Dialog } from "./main";
import { allRows } from "./inventory";
import "./patch-panels.css";
import { ExternalEditor } from "./patch-external";

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
  const cancelEdit = () => {
    if (busy) return;
    setValues(defaults);
    setError("");
  };
  const form = (
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
            disabled={busy}
            onClick={cancelEdit}
          >
            Vazgeç
          </button>
        )}
      </div>
    </form>
  );
  return (
    <section className="patch-section" aria-labelledby="patch-title">
      <h3 id="patch-title">Patch paneller</h3>
      <p className="ipam-hint">
        CAT ve fiber panelleri U konumuna yerleştirin. Port numaraları, cihaz
        bağlantıları ve kablo bilgileri elle kaydedilir.
      </p>
      {error && !values.id && (
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
      {writable &&
        (values.id ? (
          <Dialog drawer title="Patch paneli düzenle" onClose={cancelEdit}>
            <div className="patch-section">
              {error && (
                <div className="error" role="alert">
                  {error}
                </div>
              )}
              {form}
            </div>
          </Dialog>
        ) : (
          form
        ))}
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

function EndpointFields({
  values,
  setValues,
  devices,
  readOnly,
  prefix = "",
}: {
  values: Row;
  setValues: (update: (row: Row) => Row) => void;
  devices: Row[];
  readOnly: boolean;
  prefix?: string;
}) {
  const user = { role: readOnly ? "viewer" : "operator" };
  const label = (text: string) => (prefix ? `${prefix} · ${text}` : text);
  const [deviceMode, setDeviceMode] = useState(
    values.device_id || !values.device_name ? "inventory" : "manual",
  );
  const [portMode, setPortMode] = useState(
    values.interface_id || !values.port_name ? "inventory" : "manual",
  );
  const [search, setSearch] = useState("");
  const set = (key: string, value: any) =>
    setValues((v) => ({ ...v, [key]: value }));
  const interfaces = useLiveQuery<Row[]>(
    values.device_id ? `patch-interfaces:${values.device_id}` : null,
    0,
    () =>
      allRows(
        `/inventory/interfaces?candidates=true&device_id=${encodeURIComponent(values.device_id)}`,
      ),
  );
  return (
    <div className="patch-endpoint-fields">
      {interfaces.error && (
        <p className="error patch-wide" role="alert">
          {interfaces.error}
        </p>
      )}
      <Field label={label("Cihaz girişi")}>
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
          <Field label={label("Envanter cihazlarında ara")}>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </Field>
          <Field label={label("Bağlı cihaz")}>
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
        <Field label={label("Bağlı cihaz adı / IP")}>
          <input
            maxLength={190}
            readOnly={user.role === "viewer"}
            value={values.device_name || ""}
            onChange={(e) => set("device_name", e.target.value)}
          />
        </Field>
      )}
      {deviceMode === "inventory" && (
        <Field label={label("Cihaz portu girişi")}>
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
        <Field label={label("Bağlı cihaz portu")}>
          <select
            disabled={
              user.role === "viewer" || !values.device_id || interfaces.loading
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
        <Field label={label("Bağlı cihaz portu (manuel)")}>
          <input
            maxLength={120}
            readOnly={user.role === "viewer"}
            value={values.port_name || ""}
            onChange={(e) => set("port_name", e.target.value)}
          />
        </Field>
      )}
    </div>
  );
}

const endpointValues = (row: Row) => ({
  device_id: row.device_id || null,
  interface_id: row.interface_id || null,
  device_name: row.device_name || "",
  port_name: row.port_name || "",
});
const externalValues = (row: Row | null) =>
  row
    ? Object.fromEntries(
        [
          "port_id",
          "site_id",
          "floor_number",
          "department_name",
          "room_name",
          "cabinet_name",
          "panel_name",
          "panel_unit",
          "port_number",
          "device_id",
          "interface_id",
          "device_name",
          "port_name",
        ]
          .filter((key) => row[key] !== undefined && row[key] !== "")
          .map((key) => [key, row[key]]),
      )
    : null;
const externalState = (state: string) =>
  ({
    connected: "Bağlı",
    pending: "Karşı uç bekleniyor",
    ambiguous: "Birden fazla eşleşme",
    conflict: "Karşı bağlantıyı kontrol edin",
  })[state] || "Kaydedilmedi";

export function PatchPorts({
  cabinet,
  panel,
  devices,
  refs,
  refresh: parentRefresh = 0,
  user,
  close,
  saved,
}: {
  cabinet: Row;
  panel: Row;
  devices: Row[];
  refs: Record<string, Row[]>;
  refresh?: number;
  user: Row;
  close: () => void;
  saved: () => void;
}) {
  const [refresh, setRefresh] = useState(0);
  const editor = useRef<HTMLHeadingElement>(null);
  const base = `/ipam/cabinets/${cabinet.id}/patch-panels/${panel.id}/ports`;
  const listing = useLiveQuery(base, refresh + parentRefresh);
  const [selected, setSelected] = useState<Row | null>(null);
  useEffect(() => {
    editor.current?.focus();
  }, [selected?.id]);
  const [values, setStoredValues] = useState<Row>({});
  const dirty = useRef(false);
  const setValues = (update: Row | ((previous: Row) => Row)) => {
    dirty.current = true;
    setStoredValues(update);
  };
  const [internalOpen, setInternalOpen] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [portSearch, setPortSearch] = useState("");
  const rows: Row[] = listing.data?.items || [];
  useEffect(() => {
    if (!dirty.current && selected) {
      const fresh = listing.data?.items.find(
        (port: Row) => port.id === selected.id,
      );
      if (fresh) {
        setSelected(fresh);
        setStoredValues(fresh);
        setInternalOpen(!!(fresh.device_id || fresh.device_name));
      }
    }
  }, [listing.data, selected?.id]);
  const choose = (port: Row) => {
    setSelected(port);
    dirty.current = false;
    setStoredValues(port);
    setError("");
    setNotice("");
    setInternalOpen(!!(port.device_id || port.device_name));
  };
  const set = (key: string, value: any) =>
    setValues((v) => ({ ...v, [key]: value }));
  return (
    <Dialog
      title={`${panel.name} · ${panelKind(panel.kind)}`}
      onClose={close}
      wide
      drawer
    >
      <div className="patch-section">
        <p className="ipam-hint">
          Kabinet {cabinet.name} · {panel.start_unit} U · {panel.port_count}{" "}
          port. Düzenlemek için port numarasına tıklayın.
        </p>
        {(error || listing.error) && (
          <div className="error" role="alert">
            {error || listing.error}
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
              [
                p.number,
                p.device_name,
                p.port_name,
                cableLabel(p),
                p.external?.device_name,
                p.external?.port_name,
                p.external?.room_name,
              ]
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
                  {port.port_name ? `${port.port_name} · ` : ""}
                  {cableLabel(port) || "Kablo seçilmedi"}
                </small>
                {port.external && (
                  <small>
                    Dış:{" "}
                    {port.external.device_name ||
                      externalState(port.external_status)}
                    {port.external.port_name
                      ? ` / ${port.external.port_name}`
                      : ""}
                  </small>
                )}
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
                  ...endpointValues(values),
                  external: externalValues(values.external),
                  cable_model: values.cable_model || "",
                  fiber_mode: values.fiber_mode || "",
                });
                dirty.current = false;
                setStoredValues(updated);
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
            {(selected.device_name || selected.external?.device_name) && (
              <dl className="patch-port-details patch-wide">
                {selected.device_name && (
                  <div>
                    <dt>İç bağlantı cihazı</dt>
                    <dd>{selected.device_name}</dd>
                  </div>
                )}
                {selected.external?.device_name && (
                  <div>
                    <dt>Dış bağlantı cihazı</dt>
                    <dd>{selected.external.device_name}</dd>
                  </div>
                )}
              </dl>
            )}
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
            <fieldset
              className="patch-side patch-wide"
              aria-label="İç bağlantı"
            >
              <legend>
                İç bağlantı <span>Ön port</span>
              </legend>
              {internalOpen ? (
                <>
                  <EndpointFields
                    key={selected.id}
                    values={values}
                    setValues={setValues}
                    devices={devices}
                    readOnly={user.role === "viewer"}
                  />
                  {user.role !== "viewer" && (
                    <button
                      className="secondary"
                      type="button"
                      onClick={() => {
                        setValues((v) => ({ ...v, ...endpointValues({}) }));
                        setInternalOpen(false);
                      }}
                    >
                      İç bağlantıyı temizle
                    </button>
                  )}
                </>
              ) : user.role !== "viewer" ? (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setInternalOpen(true)}
                >
                  İç bağlantı ekle
                </button>
              ) : (
                <p className="ipam-hint">İç bağlantı tanımlanmamış.</p>
              )}
            </fieldset>
            <fieldset
              className="patch-side patch-wide"
              aria-label="Dış bağlantı"
            >
              <legend>
                Dış bağlantı <span>Arka port</span>
              </legend>
              {values.external ? (
                <>
                  <p
                    className="patch-link-status"
                    data-status={values.external_status}
                  >
                    {externalState(values.external_status)}
                  </p>
                  <ExternalEditor
                    key={`${selected.id}:${values.external_status || "new"}`}
                    values={values.external}
                    refs={refs}
                    readOnly={user.role === "viewer"}
                    setValues={(update) =>
                      setValues((v) => ({
                        ...v,
                        external: update(v.external || {}),
                      }))
                    }
                  />
                  <h4>Karşı portun iç bağlantısı</h4>
                  <EndpointFields
                    key={`${selected.id}:${values.external.port_id || "pending"}`}
                    values={values.external}
                    setValues={(update) =>
                      setValues((v) => ({
                        ...v,
                        external: update(v.external || {}),
                      }))
                    }
                    devices={devices}
                    readOnly={user.role === "viewer"}
                    prefix="Karşı uç"
                  />
                  {user.role !== "viewer" && (
                    <button
                      type="button"
                      className="secondary danger"
                      onClick={() =>
                        setValues((v) => ({
                          ...v,
                          external: null,
                          external_status: "",
                        }))
                      }
                    >
                      Dış bağlantıyı kaldır
                    </button>
                  )}
                </>
              ) : user.role !== "viewer" ? (
                <button
                  className="secondary"
                  type="button"
                  onClick={() =>
                    setValues((v) => ({
                      ...v,
                      external: { site_id: cabinet.site_id || "" },
                      external_status: "",
                    }))
                  }
                >
                  Dış bağlantı ekle
                </button>
              ) : (
                <p className="ipam-hint">Dış bağlantı tanımlanmamış.</p>
              )}
              <p className="ipam-hint">
                Karşı panelin iç ve geri dönüş bağlantısı kaydettiğinizde
                otomatik güncellenir.
              </p>
            </fieldset>
            {user.role !== "viewer" && (
              <div className="ipam-actions patch-wide">
                <button className="primary" disabled={busy}>
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
                      external: null,
                      external_status: "",
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
                  "Dış bağlantı",
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
                  <td>
                    {r.external ? (
                      <>
                        {r.external.device_name ||
                          externalState(r.external_status)}
                        {r.external.port_name
                          ? ` / ${r.external.port_name}`
                          : ""}
                        <small className="ipam-sub">
                          {[
                            r.external.site_name,
                            r.external.floor_number,
                            r.external.department_name,
                            r.external.room_name,
                            r.external.cabinet_name,
                            r.external.panel_name,
                            r.external.port_number,
                          ]
                            .filter(Boolean)
                            .join(" / ")}
                        </small>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
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
