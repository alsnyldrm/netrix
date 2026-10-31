import React, { useEffect, useState } from "react";
import {
  Plus,
  ArrowLeft,
  ArrowRight,
  PencilSimple,
  Trash,
  Buildings,
  HardDrives,
} from "@phosphor-icons/react";
import { api, Dialog } from "./main";
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
        `${row.name} silinsin mi? Bağlı kayıtlar varsa silinemez.`,
      )
    )
      return;
    try {
      await api(`/${resource}/${row.id}`, "DELETE");
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
              {parent ? "Alt lokasyon ekle" : "Yeni kayıt"}
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
        <div className="toolbar">
          <b>{parent ? "Alt lokasyonlar" : "Lokasyonlar"}</b>
          <span className="count-pill">{children.length}</span>
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
                <th>Lokasyon</th>
                <th>Benzersiz kod</th>
                {!parent && <th>Kurum</th>}
                <th>Açıklama</th>
                <th>İşlemler</th>
              </tr>
            </thead>
            <tbody>
              {children.map((r) => (
                <tr key={r.id}>
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
            <p>{parent ? "Henüz alt lokasyon yok." : "Henüz lokasyon yok."}</p>
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
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      title={`${row.id ? "Düzenle" : "Yeni kayıt"} · ${institution ? "Kurum" : row.parent_id ? "Alt lokasyon" : "Lokasyon"}`}
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
          <Label name={institution ? "Kurum adı" : "Lokasyon adı"}>
            <input
              required
              maxLength={institution ? 190 : 120}
              value={values.name}
              onChange={(e) => setValues({ ...values, name: e.target.value })}
            />
          </Label>
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
            Kod otomatik verilir; silinen alt lokasyonların ilk boş kodu yeniden
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
  const [selected, setSelected] = useState<Row | null>(null);
  const [error, setError] = useState("");
  return (
    <div className="ipam-workspace">
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <section className="panel table-panel">
        <div className="toolbar">
          <b>Kabinetler</b>
          <span className="count-pill">{refs.cabinets?.length || 0}</span>
        </div>
        <div
          className="table-scroll"
          role="region"
          aria-label="Kabinet tablosu"
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                {[
                  "Kabinet no",
                  "Lokasyon",
                  "Alt lokasyon",
                  "Kapasite",
                  "İşlemler",
                ].map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(refs.cabinets || []).map((r) => (
                <tr key={r.id}>
                  <td>
                    <button
                      className="text-button"
                      onClick={() => setSelected(r)}
                    >
                      <HardDrives size={19} />
                      {r.name}
                    </button>
                  </td>
                  <td>
                    {refs.sites?.find((s) => s.id === r.site_id)?.name || "—"}
                  </td>
                  <td>
                    {refs.sites?.find((s) => s.id === r.sub_site_id)?.name ||
                      "—"}
                  </td>
                  <td>{r.units} U</td>
                  <td>
                    <div className="ipam-actions">
                      {user.role !== "viewer" && (
                        <button
                          className="icon-button"
                          aria-label={`${r.name} düzenle`}
                          onClick={() => onEdit(r)}
                        >
                          <PencilSimple size={17} />
                        </button>
                      )}
                      {user.role === "admin" && (
                        <button
                          className="icon-button"
                          aria-label={`${r.name} sil`}
                          onClick={async () => {
                            if (!window.confirm(`${r.name} silinsin mi?`))
                              return;
                            try {
                              await api(`/cabinets/${r.id}`, "DELETE");
                              onSaved();
                            } catch (e: any) {
                              setError(e.message);
                            }
                          }}
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
        {!refs.cabinets?.length && (
          <div className="empty-state">
            <p>Henüz kabinet yok.</p>
          </div>
        )}
      </section>
      {selected && (
        <Rack
          row={selected}
          refs={refs}
          user={user}
          close={() => setSelected(null)}
        />
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
  useEffect(() => {
    let active = true;
    api(`/ipam/cabinets/${row.id}`)
      .then((r) => {
        if (active) setData(r);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [row.id, revision]);
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
              const placementName = placement?.accessory
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
                        {placement.accessory ? (
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
                        {!placement.accessory && (
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
                        {placement.accessory ? (
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
                      {user.role !== "viewer" && (
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
        `/ipam/prefixes/${prefix}/addresses?allocated=true&limit=100&offset=${offset}&q=${encodeURIComponent(query)}`,
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
      <Label name="VLAN / Ağ bloğu">
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
          <option value="">Ağ bloğu seçin</option>
          {(refs.prefixes || []).map((p) => (
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
