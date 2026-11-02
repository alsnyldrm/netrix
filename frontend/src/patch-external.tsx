import { useState } from "react";
import { useLiveQuery } from "./data";

type Row = Record<string, any>;
export function ExternalEditor({
  values,
  setValues,
  refs,
  readOnly,
}: {
  values: Row;
  setValues: (update: (row: Row) => Row) => void;
  refs: Record<string, Row[]>;
  readOnly: boolean;
}) {
  const [mode, setMode] = useState(
    values.room_name && !values.panel_id ? "planned" : "existing",
  );
  const [roomId, setRoomId] = useState(values.room_id || "");
  const [cabinetId, setCabinetId] = useState(values.cabinet_id || "");
  const [panelId, setPanelId] = useState(values.panel_id || "");
  const panelQuery = useLiveQuery(
    cabinetId ? `/ipam/cabinets/${cabinetId}/patch-panels` : null,
  );
  const portQuery = useLiveQuery(
    cabinetId && panelId
      ? `/ipam/cabinets/${cabinetId}/patch-panels/${panelId}/ports`
      : null,
  );
  const sites = (refs.sites || []).filter((s) => !s.parent_id);
  const rooms = (refs.sites || []).filter(
    (s) => s.parent_id === values.site_id,
  );
  const cabinets = (refs.cabinets || []).filter(
    (c) => c.sub_site_id === roomId,
  );
  const reset = (next: Row) =>
    setValues((v) => ({
      ...v,
      port_id: undefined,
      panel_id: undefined,
      ...next,
    }));
  const field = (label: string, key: string, number = false) => (
    <label className="ipam-field">
      <span>{label}</span>
      <input
        aria-label={label}
        type={number ? "number" : "text"}
        min={number ? 1 : undefined}
        max={number ? 60 : undefined}
        maxLength={
          number
            ? undefined
            : key === "floor_number" || key === "port_number"
              ? 40
              : 120
        }
        required={!number}
        readOnly={readOnly}
        value={values[key] ?? ""}
        onChange={(e) =>
          reset({
            [key]: number
              ? e.target.value
                ? Number(e.target.value)
                : null
              : e.target.value,
          })
        }
      />
    </label>
  );
  return (
    <div className="patch-target-fields">
      <label className="ipam-field">
        <span>Karşı uç girişi</span>
        <select
          aria-label="Karşı uç girişi"
          disabled={readOnly}
          value={mode}
          onChange={(e) => {
            setMode(e.target.value);
            setRoomId("");
            setCabinetId("");
            setPanelId("");
            reset({
              room_id: undefined,
              cabinet_id: undefined,
              floor_number: "",
              department_name: "",
              room_name: "",
              cabinet_name: "",
              panel_name: "",
              panel_unit: null,
              port_number: "",
            });
          }}
        >
          <option value="existing">Kayıtlı panelden seç</option>
          <option value="planned">Konum bilgisiyle gir</option>
        </select>
      </label>
      <label className="ipam-field">
        <span>Karşı lokasyon</span>
        <select
          required
          aria-label="Karşı lokasyon"
          disabled={readOnly}
          value={values.site_id || ""}
          onChange={(e) => {
            setRoomId("");
            setCabinetId("");
            setPanelId("");
            reset({
              site_id: e.target.value,
              room_id: undefined,
              cabinet_id: undefined,
              floor_number: "",
              department_name: "",
              room_name: "",
              cabinet_name: "",
              panel_name: "",
              panel_unit: null,
              port_number: "",
            });
          }}
        >
          <option value="">Seçiniz</option>
          {sites.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      {mode === "existing" ? (
        <>
          <label className="ipam-field">
            <span>Karşı oda</span>
            <select
              required
              aria-label="Karşı oda"
              disabled={readOnly || !values.site_id}
              value={roomId}
              onChange={(e) => {
                const room = rooms.find((r) => r.id === e.target.value);
                setRoomId(e.target.value);
                setCabinetId("");
                setPanelId("");
                reset({
                  room_id: e.target.value,
                  floor_number: room?.floor_number || "",
                  department_name: room?.department_name || "",
                  room_name: room?.name || "",
                  cabinet_id: undefined,
                  cabinet_name: "",
                  panel_name: "",
                  panel_unit: null,
                  port_number: "",
                });
              }}
            >
              <option value="">Seçiniz</option>
              {roomId && !rooms.some((r) => r.id === roomId) && (
                <option value={roomId}>
                  {values.floor_number || "—"}/{values.department_name || "—"}/
                  {values.room_name}
                </option>
              )}
              {rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.floor_number || "—"}/{r.department_name || "—"}/{r.name}
                </option>
              ))}
            </select>
          </label>
          <label className="ipam-field">
            <span>Karşı kabinet</span>
            <select
              required
              aria-label="Karşı kabinet"
              disabled={readOnly || !roomId}
              value={cabinetId}
              onChange={(e) => {
                setCabinetId(e.target.value);
                setPanelId("");
                reset({
                  cabinet_id: e.target.value,
                  cabinet_name:
                    cabinets.find((c) => c.id === e.target.value)?.name || "",
                  panel_name: "",
                  panel_unit: null,
                  port_number: "",
                });
              }}
            >
              <option value="">Seçiniz</option>
              {cabinetId && !cabinets.some((c) => c.id === cabinetId) && (
                <option value={cabinetId}>{values.cabinet_name}</option>
              )}
              {cabinets.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="ipam-field">
            <span>Karşı patch panel</span>
            <select
              required
              aria-label="Karşı patch panel"
              disabled={readOnly || !cabinetId || panelQuery.loading}
              value={panelId}
              onChange={(e) => {
                const panel = panelQuery.data?.items.find(
                  (p: Row) => p.id === e.target.value,
                );
                setPanelId(e.target.value);
                reset({
                  panel_id: e.target.value,
                  panel_name: panel?.name || "",
                  panel_unit: panel?.start_unit || null,
                  port_number: "",
                });
              }}
            >
              <option value="">
                {panelQuery.loading ? "Paneller yükleniyor…" : "Seçiniz"}
              </option>
              {(panelQuery.data?.items || []).map((p: Row) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {p.start_unit}U
                </option>
              ))}
            </select>
          </label>
          <label className="ipam-field">
            <span>Karşı panel portu</span>
            <select
              required
              aria-label="Karşı panel portu"
              disabled={readOnly || !panelId || portQuery.loading}
              value={values.port_id || ""}
              onChange={(e) => {
                const port = portQuery.data?.items.find(
                  (p: Row) => p.id === e.target.value,
                );
                setValues((v) => ({
                  ...v,
                  port_id: e.target.value,
                  port_number: port?.number || "",
                  device_id: port?.device_id || null,
                  interface_id: port?.interface_id || null,
                  device_name: port?.device_name || "",
                  port_name: port?.port_name || "",
                }));
              }}
            >
              <option value="">
                {portQuery.loading ? "Portlar yükleniyor…" : "Seçiniz"}
              </option>
              {(portQuery.data?.items || []).map((p: Row) => (
                <option key={p.id} value={p.id}>
                  {p.number}
                  {p.device_name
                    ? ` · ${p.device_name} / ${p.port_name || "—"}`
                    : ""}
                </option>
              ))}
            </select>
          </label>
        </>
      ) : (
        <>
          <p className="ipam-hint patch-wide">
            Oda, kabinet veya panel henüz yoksa tam konumu girin.
            Oluşturulduğunda bağlantı otomatik eşleşir.
          </p>
          {field("Karşı kat", "floor_number")}
          {field("Karşı bölüm", "department_name")}
          {field("Karşı oda adı", "room_name")}
          {field("Karşı kabinet no", "cabinet_name")}
          {field("Karşı panel adı", "panel_name")}
          {field("Karşı panel U (isteğe bağlı)", "panel_unit", true)}
          {field("Karşı port numarası", "port_number")}
        </>
      )}
      {(panelQuery.error || portQuery.error) && (
        <p className="error patch-wide" role="alert">
          {panelQuery.error || portQuery.error}
        </p>
      )}
    </div>
  );
}
