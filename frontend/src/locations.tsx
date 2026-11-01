import { PatchPanels, PatchPorts, panelKind } from "./patch-panels";
import React, { useEffect, useState } from "react";
import {
  Plus,
  ArrowLeft,
  ArrowRight,
  PencilSimple,
  Trash,
  Buildings,
  HardDrives,
  Funnel,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import { api, Dialog } from "./main";
import { useLiveQuery } from "./data";
import { Filters } from "./inventory";
import "./locations.css";
type Row = Record<string, any>;
type Props = {
  refs: Record<string, Row[]>;
  refresh: number;
  user: Row;
  onSaved: () => void;
};
const Label = ({
  name,
  children,
}: {
  name: string;
  children: React.ReactNode;
}) => (
  <label className="ipam-field">
    <span>{name}</span>
    {children}
  </label>
);

export function Locations({ refs, user, onSaved }: Props) {
  const [institution, setInstitution] = useState<string | null>(null);
  const [parent, setParent] = useState<string | null>(null);
  const [form, setForm] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  useEffect(() => setPicked([]), [parent, institution]);
  const canWrite = user.role !== "viewer";
  const institutions = refs.institutions || [],
    sites = refs.sites || [];
  const current = sites.find((s) => s.id === parent);
  const children = sites.filter((s) =>
    parent
      ? s.parent_id === parent
      : !s.parent_id &&
        (institution === null || s.institution_id === institution),
  );
  const remove = async (resource: string, row: Row) => {
    if (
      !window.confirm(
        row.parent_id
          ? `${row.name} odası ve kabinetleri silinsin mi? Envanter cihazları ve IP adresleri korunur; yerleşim ve patch kayıtları kaldırılır.`
          : `${row.name} silinsin mi? Bağlı kayıtlar varsa silinemez.`,
      )
    )
      return;
    try {
      if (resource === "sites" && row.parent_id)
        await api("/ipam/rooms/bulk-delete", "POST", { ids: [row.id] });
      else await api(`/${resource}/${row.id}`, "DELETE");
      onSaved();
    } catch (e: any) {
      setError(e.message);
    }
  };
  return (
    <div className="ipam-workspace">
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="location-toolbar">
        <div className="ipam-actions">
          {(institution !== null || parent) && (
            <button
              className="secondary"
              onClick={() => (parent ? setParent(null) : setInstitution(null))}
            >
              <ArrowLeft size={17} />
              Geri
            </button>
          )}
          <strong>
            {current?.name ||
              institutions.find((i) => i.id === institution)?.name ||
              "Kurumlar ve lokasyonlar"}
          </strong>
        </div>
        {canWrite && (
          <div className="ipam-actions">
            <button
              className="primary"
              onClick={() =>
                setForm({
                  resource: "sites",
                  institution_id: current?.institution_id || institution || "",
                  parent_id: parent,
                })
              }
            >
              <Plus size={17} />
              {parent ? "Oda ekle" : "Yeni kayıt"}
            </button>
            {!parent && (
              <button
                className="secondary"
                onClick={() => setForm({ resource: "institutions" })}
              >
                <Buildings size={17} />
                Yeni Kurum Ekle
              </button>
            )}
          </div>
        )}
      </div>
      {!parent && institution === null && (
        <section className="panel location-institutions" aria-label="Kurumlar">
          {institutions.length ? (
            institutions.map((r) => (
              <div className="location-institution" key={r.id}>
                <button
                  className="text-button"
                  onClick={() => setInstitution(r.id)}
                >
                  <Buildings size={19} />
                  <span>
                    {r.name}
                    <small>
                      {r.code} ·{" "}
                      {
                        sites.filter(
                          (s) => s.institution_id === r.id && !s.parent_id,
                        ).length
                      }{" "}
                      lokasyon
                    </small>
                  </span>
                  <ArrowRight size={18} />
                </button>
                {canWrite && (
                  <button
                    className="icon-button"
                    aria-label={`${r.name} kurumunu düzenle`}
                    onClick={() => setForm({ ...r, resource: "institutions" })}
                  >
                    <PencilSimple size={17} />
                  </button>
                )}
                {user.role === "admin" && (
                  <button
                    className="icon-button"
                    aria-label={`${r.name} kurumunu sil`}
                    onClick={() => remove("institutions", r)}
                  >
                    <Trash size={17} />
                  </button>
                )}
              </div>
            ))
          ) : (
            <p className="muted">
              Önce bir kurum ekleyin; lokasyonları bu kuruma bağlayın.
            </p>
          )}
        </section>
      )}
      <section className="panel table-panel">
        <div className="toolbar room-cabinet-toolbar">
          <div className="ipam-actions">
            <b>{parent ? "Odalar" : "Lokasyonlar"}</b>
            <span className="count-pill">{children.length}</span>
          </div>
          {parent && user.role === "admin" && (
            <button
              className="secondary danger"
              disabled={!picked.length}
              onClick={async () => {
                if (
                  !window.confirm(
                    `${picked.length} oda ve içindeki kabinetler silinsin mi? Kabinet yerleşimleri ve patch kayıtları kaldırılır; envanter cihazları ve IP adresleri korunur.`,
                  )
                )
                  return;
                try {
                  await api("/ipam/rooms/bulk-delete", "POST", { ids: picked });
                  setPicked([]);
                  onSaved();
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            >
              Seçilen odaları sil ({picked.length})
            </button>
          )}
        </div>
        <div
          className="table-scroll"
          role="region"
          aria-label="Lokasyon tablosu"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                {parent && user.role === "admin" && (
                  <th>
                    <input
                      type="checkbox"
                      aria-label="Tüm odaları seç"
                      checked={
                        children.length > 0 &&
                        children.every((r) => picked.includes(r.id))
                      }
                      onChange={(e) =>
                        setPicked(
                          e.target.checked ? children.map((r) => r.id) : [],
                        )
                      }
                    />
                  </th>
                )}
                <th>{parent ? "Oda ismi" : "Lokasyon"}</th>
                {parent && (
                  <>
                    <th>Kat numarası</th>
                    <th>Bölüm adı</th>
                  </>
                )}
                <th>Benzersiz kod</th>
                {!parent && <th>Kurum</th>}
                <th>Açıklama</th>
                <th>İşlemler</th>
              </tr>
            </thead>
            <tbody>
              {children.map((r) => (
                <tr key={r.id}>
                  {parent && user.role === "admin" && (
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${r.name} odasını seç`}
                        checked={picked.includes(r.id)}
                        onChange={(e) =>
                          setPicked(
                            e.target.checked
                              ? [...picked, r.id]
                              : picked.filter((id) => id !== r.id),
                          )
                        }
                      />
                    </td>
                  )}
                  <td>
                    {parent ? (
                      r.name
                    ) : (
                      <button
                        className="text-button"
                        onClick={() => setParent(r.id)}
                      >
                        {r.name}
                        <ArrowRight size={16} />
                      </button>
                    )}
                  </td>
                  {parent && (
                    <>
                      <td>{r.floor_number || "—"}</td>
                      <td>{r.department_name || "—"}</td>
                    </>
                  )}
                  <td className="mono">{r.code}</td>
                  {!parent && (
                    <td>
                      {institutions.find((i) => i.id === r.institution_id)
                        ?.name || "Kurum seçilmedi"}
                    </td>
                  )}
                  <td>{r.description || "—"}</td>
                  <td>
                    <div className="ipam-actions">
                      {canWrite && (
                        <button
                          className="icon-button"
                          aria-label={`${r.name} düzenle`}
                          onClick={() => setForm({ ...r, resource: "sites" })}
                        >
                          <PencilSimple size={17} />
                        </button>
                      )}
                      {user.role === "admin" && (
                        <button
                          className="icon-button"
                          aria-label={`${r.name} sil`}
                          onClick={() => remove("sites", r)}
                        >
                          <Trash size={17} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!children.length && (
          <div className="empty-state">
            <p>{parent ? "Henüz oda yok." : "Henüz lokasyon yok."}</p>
          </div>
        )}
      </section>
      {form && (
        <LocationForm
          row={form}
          refs={refs}
          close={() => setForm(null)}
          saved={onSaved}
        />
      )}
    </div>
  );
}
function LocationForm({
  row,
  refs,
  close,
  saved,
}: {
  row: Row;
  refs: Record<string, Row[]>;
  close: () => void;
  saved: () => void;
}) {
  const institution = row.resource === "institutions";
  const [values, setValues] = useState<Row>({
    name: row.name || "",
    code: row.code || "",
    institution_id: row.institution_id || "",
    parent_id: row.parent_id || null,
    description: row.description || "",
    timezone: row.timezone || "Europe/Istanbul",
    floor_number: row.floor_number || "",
    department_name: row.department_name || "",
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      title={`${row.id ? "Düzenle" : "Yeni kayıt"} · ${institution ? "Kurum" : row.parent_id ? "Oda" : "Lokasyon"}`}
      onClose={close}
    >
      <form
        className="ipam-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api(
              `/${row.resource}${row.id ? "/" + row.id : ""}`,
              row.id ? "PUT" : "POST",
              institution ? { name: values.name, code: values.code } : values,
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
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div className="ipam-fields">
          {!institution && (
            <Label name="Kurum">
              <select
                required
                disabled={!!row.parent_id}
                aria-label="Kurum"
                value={values.institution_id}
                onChange={(e) =>
                  setValues({ ...values, institution_id: e.target.value })
                }
              >
                <option value="">Kurum seçin</option>
                {(refs.institutions || []).map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </Label>
          )}
          <Label
            name={
              institution
                ? "Kurum adı"
                : row.parent_id
                  ? "Oda ismi *"
                  : "Lokasyon adı"
            }
          >
            <input
              required
              maxLength={institution ? 190 : 120}
              value={values.name}
              onChange={(e) => setValues({ ...values, name: e.target.value })}
            />
          </Label>
          {row.parent_id && (
            <>
              <Label name="Kat numarası *">
                <input
                  required
                  maxLength={40}
                  value={values.floor_number}
                  onChange={(e) =>
                    setValues({ ...values, floor_number: e.target.value })
                  }
                />
              </Label>
              <Label name="Bölüm adı *">
                <input
                  required
                  maxLength={120}
                  value={values.department_name}
                  onChange={(e) =>
                    setValues({ ...values, department_name: e.target.value })
                  }
                />
              </Label>
            </>
          )}
          {(!row.parent_id || row.id) && (
            <Label name={institution ? "Kurum kodu" : "Benzersiz kod"}>
              <input
                required={institution}
                readOnly={!!row.parent_id}
                placeholder={institution ? "01" : "Boş bırakılırsa otomatik"}
                value={values.code}
                onChange={(e) => setValues({ ...values, code: e.target.value })}
              />
            </Label>
          )}
          {!institution && !row.parent_id && (
            <Label name="Açıklama">
              <input
                value={values.description}
                onChange={(e) =>
                  setValues({ ...values, description: e.target.value })
                }
              />
            </Label>
          )}
        </div>
        {row.parent_id && (
          <p className="ipam-hint">
            Kod otomatik verilir; silinen odaların ilk boş kodu yeniden
            kullanılır.
          </p>
        )}
        <div className="ipam-actions">
          <button type="button" className="secondary" onClick={close}>
            Vazgeç
          </button>
          <button className="primary" disabled={busy}>
            Kaydı kaydet
          </button>
        </div>
      </form>
    </Dialog>
  );
}
export function Cabinets({
  refs,
  user,
  onSaved,
  onEdit,
}: Props & { onEdit: (row: Row) => void }) {
  const [roomId, setRoomId] = useState<string | null>(null);
  const [rack, setRack] = useState<Row | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [filterOpen, setFilterOpen] = useState(false);
  const [rules, setRules] = useState<
    { field: string; op: string; value: string; join: string }[]
  >([]);
  const columns = [
    { key: "name", label: "Oda ismi" },
    { key: "institution_name", label: "Kurum" },
    { key: "location_name", label: "Lokasyon" },
    { key: "cabinet_count", label: "Kabinet sayısı" },
  ];
  const normalize = (value: any) => String(value ?? "").toLocaleLowerCase("tr");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setPicked([]), [roomId]);
  const rooms = (refs.sites || []).filter((r) => r.parent_id);
  const cabinets = refs.cabinets || [];
  const unassigned = cabinets.filter(
    (c) => !rooms.some((r) => r.id === c.sub_site_id),
  );
  const groups = [
    ...rooms,
    ...(unassigned.length
      ? [{ id: "unassigned", name: "Odası seçilmemiş" }]
      : []),
  ];
  const current = rooms.find((r) => r.id === roomId);
  const roomCabinets =
    roomId === "unassigned"
      ? unassigned
      : cabinets.filter((c) => c.sub_site_id === roomId);
  const counts = new Map<string, number>();
  for (const cabinet of cabinets)
    counts.set(cabinet.sub_site_id, (counts.get(cabinet.sub_site_id) || 0) + 1);
  const filtered = groups
    .map((r): Row => ({
      ...r,
      institution_name:
        refs.institutions?.find((i) => i.id === r.institution_id)?.name || "—",
      location_name: refs.sites?.find((s) => s.id === r.parent_id)?.name || "—",
      cabinet_count:
        r.id === "unassigned" ? unassigned.length : counts.get(r.id) || 0,
    }))
    .filter((r) => {
      const text = normalize(columns.map((c) => r[c.key]).join(" "));
      if (
        !normalize(search)
          .trim()
          .split(/\s+/)
          .every((word) => text.includes(word))
      )
        return false;
      return (
        rules.reduce<boolean | undefined>((result, rule) => {
          const actual = normalize(r[rule.field]),
            expected = normalize(rule.value);
          const match =
            rule.op === "contains"
              ? actual.includes(expected)
              : rule.op === "not_contains"
                ? !actual.includes(expected)
                : rule.op === "eq"
                  ? actual === expected
                  : rule.op === "ne"
                    ? actual !== expected
                    : rule.op === "gt"
                      ? Number(actual) > Number(expected)
                      : rule.op === "lt"
                        ? Number(actual) < Number(expected)
                        : false;
          return result === undefined
            ? match
            : rule.join === "or"
              ? result || match
              : result && match;
        }, undefined) ?? true
      );
    });
  const rows = roomId ? roomCabinets : filtered;
  const remove = async (ids: string[]) => {
    if (
      !window.confirm(
        `${ids.length} kabinet silinsin mi? Yerleşimler, organizerler ve patch kayıtları kaldırılır. Envanter cihazları ve IP adresleri korunur.`,
      )
    )
      return;
    setBusy(true);
    setError("");
    try {
      await api("/ipam/cabinets/bulk-delete", "POST", {
        ids,
      });
      setPicked([]);
      onSaved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="ipam-workspace">
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <section className="panel table-panel">
        <div className="toolbar room-cabinet-toolbar">
          <div className="ipam-actions">
            {roomId && (
              <button className="secondary" onClick={() => setRoomId(null)}>
                <ArrowLeft size={17} aria-hidden="true" />
                Odalar
              </button>
            )}
            <b>
              {roomId ? current?.name || "Odası seçilmemiş" : "Kabinet odaları"}
            </b>
            <span className="count-pill">{rows.length}</span>
          </div>
          {!roomId && (
            <div className="room-list-controls">
              <label className="search-box">
                <MagnifyingGlass size={18} aria-hidden="true" />
                <input
                  type="search"
                  aria-label="Kabinet odalarında ara"
                  placeholder="Oda, kurum, lokasyon ara…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>
              <button className="secondary" onClick={() => setFilterOpen(true)}>
                <Funnel size={18} aria-hidden="true" />
                Filtreler{rules.length ? ` (${rules.length})` : ""}
              </button>
            </div>
          )}
          {roomId && user.role === "admin" && (
            <button
              className="secondary danger"
              disabled={!picked.length || busy}
              onClick={() => remove(picked)}
            >
              Seçilenleri sil ({picked.length})
            </button>
          )}
        </div>
        <div
          className="table-scroll"
          role="region"
          aria-label={roomId ? "Kabinet tablosu" : "Oda tablosu"}
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                {roomId && user.role === "admin" && (
                  <th>
                    <input
                      type="checkbox"
                      aria-label={
                        roomId ? "Tüm kabinetleri seç" : "Tüm odaları seç"
                      }
                      checked={
                        rows.length > 0 &&
                        rows
                          .filter((r) => r.id !== "unassigned")
                          .every((r) => picked.includes(r.id)) &&
                        picked.length > 0
                      }
                      onChange={(e) =>
                        setPicked(
                          e.target.checked
                            ? rows
                                .filter((r) => r.id !== "unassigned")
                                .map((r) => r.id)
                            : [],
                        )
                      }
                    />
                  </th>
                )}
                {(roomId
                  ? ["Kabinet no", "Kapasite (U)", "Açıklama", "İşlemler"]
                  : ["Oda ismi", "Kurum", "Lokasyon", "Kabinet sayısı"]
                ).map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  {roomId && user.role === "admin" && (
                    <td>
                      {r.id !== "unassigned" && (
                        <input
                          type="checkbox"
                          aria-label={`${r.name} ${roomId ? "kabinetini" : "odasını"} seç`}
                          checked={picked.includes(r.id)}
                          onChange={(e) =>
                            setPicked(
                              e.target.checked
                                ? [...picked, r.id]
                                : picked.filter((id) => id !== r.id),
                            )
                          }
                        />
                      )}
                    </td>
                  )}
                  <td>
                    <button
                      className="text-button"
                      onClick={() => (roomId ? setRack(r) : setRoomId(r.id))}
                    >
                      <HardDrives size={19} aria-hidden="true" />
                      {r.name}
                    </button>
                  </td>
                  {roomId ? (
                    <>
                      <td>{r.units} U</td>
                      <td>{r.description || "—"}</td>
                    </>
                  ) : (
                    <>
                      <td>{r.institution_name}</td>
                      <td>{r.location_name}</td>
                      <td>{r.cabinet_count}</td>
                    </>
                  )}
                  {roomId && (
                    <td>
                      <div className="ipam-actions">
                        {roomId && user.role !== "viewer" && (
                          <button
                            className="icon-button"
                            aria-label={`${r.name} düzenle`}
                            onClick={() => onEdit(r)}
                          >
                            <PencilSimple size={17} />
                          </button>
                        )}
                        {user.role === "admin" && r.id !== "unassigned" && (
                          <button
                            className="icon-button"
                            disabled={busy}
                            aria-label={`${r.name} sil`}
                            onClick={() => remove([r.id])}
                          >
                            <Trash size={17} />
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows.length && (
          <div className="empty-state">
            <p>
              {roomId
                ? "Bu odada henüz kabinet yok."
                : groups.length
                  ? "Arama veya filtrelere uygun oda yok. Arama ya da filtreleri değiştirin."
                  : "Henüz oda yok. Lokasyon menüsünden oda ekleyin."}
            </p>
          </div>
        )}
      </section>
      {filterOpen && (
        <Filters
          columns={columns}
          rules={rules}
          onSave={setRules}
          onClose={() => setFilterOpen(false)}
        />
      )}
      {rack && (
        <Rack row={rack} refs={refs} user={user} close={() => setRack(null)} />
      )}
    </div>
  );
}

function Rack({
  row,
  refs,
  user,
  close,
}: {
  row: Row;
  refs: Record<string, Row[]>;
  user: Row;
  close: () => void;
}) {
  const [data, setData] = useState<Row | null>(null);
  const [patchPanel, setPatchPanel] = useState<Row | null>(null);
  const [placementSource, setPlacementSource] = useState("inventory");
  const [imageValues, setImageValues] = useState({ url: "", source: "" });
  const [accessory, setAccessory] = useState<Row>({ start_unit: 1, units: 1 });
  const [accessoryError, setAccessoryError] = useState("");
  const [accessorySaved, setAccessorySaved] = useState(false);
  const [imageError, setImageError] = useState("");
  const [imageSaved, setImageSaved] = useState(false);
  const [imageLoading, setImageLoading] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [choice, setChoice] = useState<Row>({
    device_id: "",
    start_unit: 1,
    units: 1,
  });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setImageValues({ url: "", source: "" });
    setImageError("");
    setImageSaved(false);
    setImageLoading(!!choice.device_id);
    if (choice.device_id) {
      api(`/ipam/devices/${choice.device_id}/model-image`)
        .then((image) => {
          if (active) setImageValues(image);
        })
        .catch((e) => {
          if (active) setImageError(e.message);
        })
        .finally(() => {
          if (active) setImageLoading(false);
        });
    }
    return () => {
      active = false;
    };
  }, [choice.device_id]);
  const rackQuery = useLiveQuery<Row>(`/ipam/cabinets/${row.id}`, revision);
  useEffect(() => {
    if (rackQuery.data) setData(rackQuery.data);
    if (rackQuery.error) setError(rackQuery.error);
  }, [rackQuery.data, rackQuery.error]);
  const rackDevices: Row[] = [
    ...new Map<string, Row>([
      ...(refs.devices || []).map((d) => [d.id, d] as const),
      ...(data?.placements || []).map(
        (p: Row) => [p.device.id, p.device] as const,
      ),
    ]).values(),
  ];
  const placements: Row[] = [
    ...(data?.placements || []),
    ...(data?.accessories || []).map((a: Row) => ({ ...a, accessory: true })),
    ...(data?.patch_panels || []).map((p: Row) => ({ ...p, panel: true })),
  ];
  return (
    <Dialog wide title={`${row.name} · ${row.units} U`} onClose={close}>
      <div className="rack-dialog">
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <p className="ipam-hint">
          U numaraları aşağıdan yukarıya artar. Cihaz görselleri üreticinin
          model kaynağından gelir.
        </p>
        <div
          className="rack-elevation"
          role="region"
          aria-label="Kabinet yerleşimi"
          tabIndex={0}
        >
          {Array.from({ length: row.units }, (_, i) => row.units - i).map(
            (unit) => {
              const placement = placements.find(
                (p) => p.start_unit + p.units - 1 === unit,
              );
              const placementName = placement?.panel
                ? placement.name
                : placement?.accessory
                  ? "Fırçalı organizer"
                  : placement?.device.name;
              const occupied = placements.some(
                (p) => unit >= p.start_unit && unit < p.start_unit + p.units,
              );
              return (
                <div
                  className={`rack-unit ${occupied ? "occupied" : ""}`}
                  key={unit}
                >
                  <span className="rack-number">{unit}U</span>
                  <div className="rack-slot">
                    {placement ? (
                      <div
                        className="rack-device"
                        style={{ height: `${placement.units * 80 - 4}px` }}
                      >
                        {placement.panel ? (
                          <button
                            type="button"
                            className="rack-patch-face"
                            onClick={() => setPatchPanel(placement)}
                            aria-label={`${placement.name} portlarını aç`}
                          >
                            <strong>{panelKind(placement.kind)}</strong>
                            <span>
                              {placement.port_count} port · Portları aç
                            </span>
                          </button>
                        ) : placement.accessory ? (
                          <div
                            className="rack-organizer"
                            role="img"
                            aria-label="Fırçalı organizer şeması"
                          >
                            <span aria-hidden="true" />
                          </div>
                        ) : placement.image ? (
                          <img
                            key={placement.image.url}
                            src={placement.image.url}
                            referrerPolicy="no-referrer"
                            alt={`${placement.device.vendor} ${placement.device.model} üretici görseli`}
                            onError={(e) => {
                              e.currentTarget.hidden = true;
                              e.currentTarget.parentElement?.classList.add(
                                "image-unavailable",
                              );
                            }}
                          />
                        ) : null}
                        {!placement.accessory && !placement.panel && (
                          <span className="rack-fallback">
                            {placement.image
                              ? "Görsel yüklenemedi"
                              : "Üretici görseli henüz yok"}
                            <br />
                            {placement.device.model || placement.device.name}
                          </span>
                        )}
                      </div>
                    ) : !occupied ? (
                      <span className="rack-empty">Boş</span>
                    ) : null}
                  </div>
                  {placement && (
                    <div className="rack-info">
                      <ArrowRight size={20} aria-hidden="true" />
                      <div>
                        <strong title={placementName}>{placementName}</strong>
                        {placement.panel ? (
                          <small>
                            {panelKind(placement.kind)} · {placement.port_count}{" "}
                            port
                          </small>
                        ) : placement.accessory ? (
                          <small>Yatay kablo düzenleyici · Şematik</small>
                        ) : (
                          <small
                            title={`${placement.device.management_ip} · ${placement.device.vendor} ${placement.device.model}`}
                          >
                            {placement.device.management_ip} ·{" "}
                            {placement.device.vendor} {placement.device.model}
                          </small>
                        )}
                        <small>
                          {placement.start_unit}–
                          {placement.start_unit + placement.units - 1} U
                        </small>
                        {placement.image && (
                          <a
                            href={placement.image.source}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Üretici kaynağı
                          </a>
                        )}
                      </div>
                      {user.role !== "viewer" && !placement.panel && (
                        <div className="ipam-actions">
                          <button
                            className="icon-button"
                            aria-label={`${placementName} yerleşimini düzenle`}
                            disabled={busy}
                            onClick={() => {
                              if (placement.accessory) {
                                setAccessory(placement);
                                setAccessoryError("");
                                setAccessorySaved(false);
                                document
                                  .getElementById("organizer-start")
                                  ?.focus();
                              } else {
                                setPlacementSource("inventory");
                                setChoice({
                                  device_id: placement.device_id,
                                  start_unit: placement.start_unit,
                                  units: placement.units,
                                });
                              }
                            }}
                          >
                            <PencilSimple size={16} />
                          </button>
                          <button
                            className="icon-button"
                            aria-label={`${placementName} kabinetten çıkar`}
                            disabled={busy}
                            onClick={async () => {
                              setBusy(true);
                              setError("");
                              try {
                                await api(
                                  placement.accessory
                                    ? `/ipam/cabinets/${row.id}/accessories/${placement.id}`
                                    : `/ipam/cabinets/${row.id}/placements/${placement.device_id}`,
                                  "DELETE",
                                );
                                if (
                                  placement.accessory &&
                                  accessory.id === placement.id
                                ) {
                                  setAccessory({ start_unit: 1, units: 1 });
                                  setAccessorySaved(false);
                                }
                                setRevision((v) => v + 1);
                              } catch (e: any) {
                                setError(e.message);
                              } finally {
                                setBusy(false);
                              }
                            }}
                          >
                            <Trash size={16} />
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            },
          )}
        </div>
        <PatchPanels
          cabinet={row}
          panels={data?.patch_panels || []}
          user={user}
          saved={() => setRevision((v) => v + 1)}
          open={setPatchPanel}
        />
        {patchPanel && (
          <PatchPorts
            cabinet={row}
            panel={patchPanel}
            devices={refs.devices || []}
            user={user}
            close={() => setPatchPanel(null)}
            saved={() => setRevision((v) => v + 1)}
          />
        )}
        {user.role !== "viewer" && (
          <div className="rack-source">
            <Label name="Yerleşim kaynağı">
              <select
                disabled={busy}
                value={placementSource}
                onChange={(e) => setPlacementSource(e.target.value)}
              >
                <option value="inventory">Envanterden cihaz seç</option>
                <option value="ipam">VLAN / IP adreslerinden seç</option>
              </select>
            </Label>
            <p className="ipam-hint">
              Sunucu, storage, SAN switch ve ağ cihazlarını aynı kabinete
              yerleştirebilirsiniz.
            </p>
          </div>
        )}
        {user.role !== "viewer" && placementSource === "ipam" && (
          <RackIPPlacement
            cabinet={row}
            refs={refs}
            devices={rackDevices}
            busy={busy}
            setBusy={setBusy}
            saved={(result) => {
              setData(result);
              setChoice({
                device_id: result.selected_device_id,
                start_unit: 1,
                units: 1,
              });
              setRevision((v) => v + 1);
            }}
          />
        )}
        {user.role !== "viewer" && placementSource === "inventory" && (
          <form
            className="rack-placement-form"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                await api(`/ipam/cabinets/${row.id}/placements`, "PUT", choice);
                setRevision((v) => v + 1);
              } catch (e: any) {
                setError(e.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <Label name="Cihaz">
              <select
                required
                disabled={busy}
                value={choice.device_id}
                onChange={(e) =>
                  setChoice({ ...choice, device_id: e.target.value })
                }
              >
                <option value="">Envanterden seçin</option>
                {rackDevices.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} · {d.model || "Model belirtilmedi"}
                  </option>
                ))}
              </select>
            </Label>
            <Label name="Başlangıç U">
              <input
                type="number"
                required
                min={1}
                max={row.units}
                value={choice.start_unit}
                onChange={(e) =>
                  setChoice({ ...choice, start_unit: Number(e.target.value) })
                }
              />
            </Label>
            <Label name="Cihaz yüksekliği (U)">
              <input
                type="number"
                required
                min={1}
                max={row.units}
                value={choice.units}
                onChange={(e) =>
                  setChoice({ ...choice, units: Number(e.target.value) })
                }
              />
            </Label>
            <button className="primary" disabled={busy}>
              Yerleşimi kaydet
            </button>
          </form>
        )}
        {user.role !== "viewer" && (
          <section
            className="rack-organizer-section"
            aria-labelledby="organizer-title"
          >
            <h3 id="organizer-title">
              Yatay Kablo Düzenleyici / Fırçalı Organizer
            </h3>
            <p className="ipam-hint">
              Kabinet içindeki konumunu ve kapladığı U yüksekliğini seçin.
            </p>
            <form
              className="rack-organizer-form"
              onSubmit={async (e) => {
                e.preventDefault();
                setBusy(true);
                setAccessoryError("");
                setAccessorySaved(false);
                try {
                  await api(
                    `/ipam/cabinets/${row.id}/accessories${accessory.id ? `/${accessory.id}` : ""}`,
                    accessory.id ? "PUT" : "POST",
                    {
                      kind: "brush_organizer",
                      start_unit: accessory.start_unit,
                      units: accessory.units,
                    },
                  );
                  setAccessory({ start_unit: 1, units: 1 });
                  setAccessorySaved(true);
                  setRevision((v) => v + 1);
                } catch (e: any) {
                  setAccessoryError(e.message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <Label name="Organizer başlangıç U">
                <input
                  id="organizer-start"
                  type="number"
                  required
                  min={1}
                  max={row.units}
                  disabled={busy}
                  aria-describedby={
                    accessoryError ? "organizer-error" : undefined
                  }
                  value={accessory.start_unit}
                  onChange={(e) => {
                    setAccessorySaved(false);
                    setAccessory({
                      ...accessory,
                      start_unit: Number(e.target.value),
                    });
                  }}
                />
              </Label>
              <Label name="Organizer yüksekliği (U)">
                <input
                  type="number"
                  required
                  min={1}
                  max={row.units}
                  disabled={busy}
                  aria-describedby={
                    accessoryError ? "organizer-error" : undefined
                  }
                  value={accessory.units}
                  onChange={(e) => {
                    setAccessorySaved(false);
                    setAccessory({
                      ...accessory,
                      units: Number(e.target.value),
                    });
                  }}
                />
              </Label>
              <button className="primary" disabled={busy}>
                {busy
                  ? "Kaydediliyor…"
                  : accessory.id
                    ? "Organizeri güncelle"
                    : "Organizer ekle"}
              </button>
              {accessory.id && (
                <button
                  type="button"
                  className="secondary"
                  disabled={busy}
                  onClick={() => {
                    setAccessory({ start_unit: 1, units: 1 });
                    setAccessoryError("");
                  }}
                >
                  Düzenlemeden vazgeç
                </button>
              )}
              {accessoryError && (
                <div id="organizer-error" className="error" role="alert">
                  {accessoryError}
                </div>
              )}
              {accessorySaved && (
                <p className="ipam-hint" role="status">
                  Organizer kaydedildi.
                </p>
              )}
            </form>
          </section>
        )}
        {user.role !== "viewer" && (
          <details className="rack-image-settings">
            <summary>Üretici model görselini tanımla</summary>
            <form
              className="ipam-form"
              onSubmit={async (e) => {
                e.preventDefault();
                if (!choice.device_id) {
                  setImageError("Önce yerleşim alanından cihazı seçin");
                  return;
                }
                setBusy(true);
                setImageError("");
                setImageSaved(false);
                try {
                  const image = await api(
                    `/ipam/devices/${choice.device_id}/model-image`,
                    "PUT",
                    imageValues,
                  );
                  setImageValues(image);
                  setImageSaved(true);
                  setRevision((v) => v + 1);
                } catch (e: any) {
                  setImageError(e.message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <p className="ipam-hint">
                Görsel için HPE, Fortinet veya BlueAlly CDN bağlantısı; ürün
                sayfası için HPE veya Fortinet bağlantısı kullanın.
              </p>
              <Label name="Üretici görsel URL">
                <input
                  type="url"
                  required
                  disabled={imageLoading || busy}
                  value={imageValues.url}
                  onChange={(e) => {
                    setImageSaved(false);
                    setImageError("");
                    setImageValues({ ...imageValues, url: e.target.value });
                  }}
                />
              </Label>
              <Label name="Üretici ürün sayfası URL">
                <input
                  type="url"
                  required
                  disabled={imageLoading || busy}
                  value={imageValues.source}
                  onChange={(e) => {
                    setImageSaved(false);
                    setImageError("");
                    setImageValues({ ...imageValues, source: e.target.value });
                  }}
                />
              </Label>
              {imageError && (
                <div className="error" role="alert">
                  {imageError}
                </div>
              )}
              {imageSaved && (
                <p className="ipam-hint" role="status">
                  Model görseli ve ürün sayfası kaydedildi.
                </p>
              )}
              <button
                className="primary"
                disabled={busy || imageLoading || !choice.device_id}
              >
                {imageLoading
                  ? "Kayıtlı bağlantılar yükleniyor…"
                  : busy
                    ? "Kaydediliyor…"
                    : "Model görselini kaydet"}
              </button>
            </form>
          </details>
        )}
      </div>
    </Dialog>
  );
}

function RackIPPlacement({
  cabinet,
  refs,
  devices,
  busy,
  setBusy,
  saved,
}: {
  cabinet: Row;
  refs: Record<string, Row[]>;
  devices: Row[];
  busy: boolean;
  setBusy: (busy: boolean) => void;
  saved: (result: Row) => void;
}) {
  const [prefix, setPrefix] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<Row>({ items: [], total: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [values, setValues] = useState<Row>({
    address_id: "",
    name: "",
    kind: "server",
    vendor: "",
    model: "",
    start_unit: 1,
    units: 1,
  });
  useEffect(() => {
    let active = true;
    setPage({ items: [], total: 0 });
    setLoading(!!prefix);
    setError("");
    if (!prefix) return;
    const timer = window.setTimeout(() => {
      api(
        `/ipam/vlans/${prefix}/addresses?allocated=true&limit=100&offset=${offset}&q=${encodeURIComponent(query)}`,
      )
        .then((result) => {
          if (active) setPage(result);
        })
        .catch((e) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [prefix, query, offset]);
  const selected = (page.items || []).find(
    (r: Row) => r.id === values.address_id,
  );
  // IPAM's device_id can be the upstream switch. Match the physical endpoint itself.
  const existing =
    selected &&
    devices.find(
      (d) =>
        d.vrf_id === selected.vrf_id && d.management_ip === selected.address,
    );
  function resetSelection() {
    setValues((v) => ({
      ...v,
      address_id: "",
      name: "",
      vendor: "",
      model: "",
    }));
    setSuccess("");
  }
  return (
    <form
      className="rack-ip-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        setSuccess("");
        try {
          const result = await api(
            `/ipam/cabinets/${cabinet.id}/placements/from-ip`,
            "POST",
            values,
          );
          saved(result);
          setSuccess(`${values.name} kabinet yerleşimi kaydedildi.`);
        } catch (e: any) {
          setError(e.message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <Label name="VLAN">
        <select
          required
          disabled={busy}
          value={prefix}
          onChange={(e) => {
            setPrefix(e.target.value);
            setOffset(0);
            resetSelection();
          }}
        >
          <option value="">VLAN seçin</option>
          {(refs.vlans || []).map((p) => (
            <option key={p.id} value={p.id}>
              {p.display_name || p.cidr}
            </option>
          ))}
        </select>
      </Label>
      <Label name="IP veya hostname ara">
        <input
          type="search"
          maxLength={120}
          disabled={busy || !prefix}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
            resetSelection();
          }}
        />
      </Label>
      <div className="rack-ip-wide">
        <Label name="IP adresi / Hostname">
          <select
            required
            disabled={busy || loading || !prefix}
            value={values.address_id}
            onChange={(e) => {
              const ip = page.items.find((r: Row) => r.id === e.target.value);
              const device =
                ip &&
                devices.find(
                  (d) =>
                    d.vrf_id === ip.vrf_id && d.management_ip === ip.address,
                );
              setValues((v) => ({
                ...v,
                address_id: ip?.id || "",
                name:
                  device?.name ||
                  (ip?.hostname || ip?.address || "").slice(0, 120),
                kind: device?.kind || "server",
                vendor: device?.vendor || "",
                model: device?.model || "",
              }));
              setSuccess("");
              setError("");
            }}
          >
            <option value="">
              {loading ? "IP adresleri yükleniyor…" : "IP adresi seçin"}
            </option>
            {(page.items || []).map((ip: Row) => (
              <option key={ip.id} value={ip.id}>
                {ip.address} · {ip.hostname || "Hostname belirtilmedi"}
              </option>
            ))}
          </select>
        </Label>
        {!!prefix && (
          <div className="rack-ip-pagination">
            <small role="status">
              {loading
                ? "Yükleniyor…"
                : `${page.total} kayıt · ${offset + (page.items.length ? 1 : 0)}–${offset + page.items.length}`}
            </small>
            <button
              type="button"
              className="secondary"
              disabled={busy || loading || offset === 0}
              onClick={() => {
                setOffset((o) => Math.max(0, o - 100));
                resetSelection();
              }}
            >
              Önceki IP’ler
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy || loading || offset + 100 >= Number(page.total)}
              onClick={() => {
                setOffset((o) => o + 100);
                resetSelection();
              }}
            >
              Sonraki IP’ler
            </button>
          </div>
        )}
      </div>
      <Label name="Cihaz adı">
        <input
          required
          maxLength={120}
          disabled={busy || !!existing}
          value={values.name}
          onChange={(e) => setValues({ ...values, name: e.target.value })}
        />
      </Label>
      <Label name="Cihaz türü">
        <select
          required
          disabled={busy || !!existing}
          value={values.kind}
          onChange={(e) => setValues({ ...values, kind: e.target.value })}
        >
          <option value="">Cihaz türü seçin</option>
          {(refs["device-types"] || []).map((t) => (
            <option key={t.code} value={t.code}>
              {t.name}
            </option>
          ))}
        </select>
      </Label>
      <Label name="Üretici (isteğe bağlı)">
        <input
          maxLength={80}
          disabled={busy || !!existing}
          value={values.vendor}
          onChange={(e) => setValues({ ...values, vendor: e.target.value })}
        />
      </Label>
      <Label name="Model (isteğe bağlı)">
        <input
          maxLength={100}
          disabled={busy || !!existing}
          value={values.model}
          onChange={(e) => setValues({ ...values, model: e.target.value })}
        />
      </Label>
      <Label name="Başlangıç U">
        <input
          type="number"
          required
          min={1}
          max={cabinet.units}
          disabled={busy}
          value={values.start_unit}
          onChange={(e) =>
            setValues({ ...values, start_unit: Number(e.target.value) })
          }
        />
      </Label>
      <Label name="Cihaz yüksekliği (U)">
        <input
          type="number"
          required
          min={1}
          max={cabinet.units}
          disabled={busy}
          value={values.units}
          onChange={(e) =>
            setValues({ ...values, units: Number(e.target.value) })
          }
        />
      </Label>
      <p className="ipam-hint rack-ip-wide">
        {existing
          ? "Mevcut envanter kaydı kullanılacak."
          : "Seçilen fiziksel cihaz merkezi envantere kaydedilir. Cihazın kendi yönetim IP adresini seçin."}
      </p>
      {error && (
        <div className="error rack-ip-wide" role="alert">
          {error}
        </div>
      )}
      {success && (
        <p className="ipam-hint rack-ip-wide" role="status">
          {success}
        </p>
      )}
      <button
        className="primary rack-ip-wide"
        disabled={busy || loading || !values.address_id}
      >
        {busy ? "Kaydediliyor…" : "IP adresinden yerleştir"}
      </button>
    </form>
  );
}
