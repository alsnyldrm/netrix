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
  const [imageValues, setImageValues] = useState({ url: "", source: "" });
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
  const placements: Row[] = data?.placements || [];
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
                        {placement.image ? (
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
                        <span className="rack-fallback">
                          {placement.image
                            ? "Görsel yüklenemedi"
                            : "Üretici görseli henüz yok"}
                          <br />
                          {placement.device.model || placement.device.name}
                        </span>
                      </div>
                    ) : !occupied ? (
                      <span className="rack-empty">Boş</span>
                    ) : null}
                  </div>
                  {placement && (
                    <div className="rack-info">
                      <ArrowRight size={20} aria-hidden="true" />
                      <div>
                        <strong title={placement.device.name}>
                          {placement.device.name}
                        </strong>
                        <small
                          title={`${placement.device.management_ip} · ${placement.device.vendor} ${placement.device.model}`}
                        >
                          {placement.device.management_ip} ·{" "}
                          {placement.device.vendor} {placement.device.model}
                        </small>
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
                            aria-label={`${placement.device.name} yerleşimini düzenle`}
                            disabled={busy}
                            onClick={() =>
                              setChoice({
                                device_id: placement.device_id,
                                start_unit: placement.start_unit,
                                units: placement.units,
                              })
                            }
                          >
                            <PencilSimple size={16} />
                          </button>
                          <button
                            className="icon-button"
                            aria-label={`${placement.device.name} kabinetten çıkar`}
                            disabled={busy}
                            onClick={async () => {
                              try {
                                await api(
                                  `/ipam/cabinets/${row.id}/placements/${placement.device_id}`,
                                  "DELETE",
                                );
                                setRevision((v) => v + 1);
                              } catch (e: any) {
                                setError(e.message);
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
                {(refs.devices || []).map((d) => (
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
