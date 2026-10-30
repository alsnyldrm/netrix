import React, { useDeferredValue, useEffect, useRef, useState } from "react";
import {
  Funnel,
  Columns,
  Trash,
  PencilSimple,
  Plus,
  X,
  ArrowLeft,
  Eye,
  DownloadSimple,
  ArrowsClockwise,
} from "@phosphor-icons/react";
import { api, Badge, Dialog, PAGES, tag, date, speed } from "./main";
import "./inventory.css";
type Row = Record<string, any>;
type Column = { key: string; label: string };
type Rule = { field: string; op: string; value: string; join: string };
const BULK = [
  "vrf_id",
  "site_id",
  "vendor",
  "kind",
  "model",
  "lifecycle_status",
  "adapter",
  "snmp_credential_id",
  "config_credential_id",
  "ssh_trust_host_key",
  "monitoring_enabled",
  "monitor_interval",
  "backup_interval",
];
const DEFAULTS: Record<string, string[]> = {
  "backup-devices": [
    "name",
    "management_ip",
    "backup_group",
    "snapshot_count",
    "latest_snapshot_at",
  ],
  devices: [
    "name",
    "management_ip",
    "kind",
    "vendor",
    "model",
    "site_name",
    "lifecycle_status",
  ],
  interfaces: [
    "name",
    "device_name",
    "device_kind",
    "if_index",
    "capacity",
    "oper_status",
    "monitoring_enabled",
  ],
  snapshots: [
    "device_name",
    "backup_group",
    "created_at",
    "size_bytes",
    "changed",
  ],
};
export async function allRows(path: string) {
  const rows: Row[] = [];
  let offset = 0;
  while (true) {
    const d = await api(
      `${path}${path.includes("?") ? "&" : "?"}limit=200&offset=${offset}`,
    );
    rows.push(...d.items);
    offset += d.items.length;
    if (offset >= d.total || !d.items.length) return rows;
  }
}
function value(key: string, v: any) {
  if (v == null || v === "") return "—";
  if (key === "lifecycle_status" || key === "reachability")
    return (
      <Badge
        value={v}
        tone={
          (key === "lifecycle_status" ? v === "active" : v === "reachable")
            ? "success"
            : "danger"
        }
      />
    );
  if (key.endsWith("_at")) return date(v);
  if (key === "speed_bps") return speed(v);
  if (key === "changed") return v ? "Değişti" : "Değişmedi";
  if (["backup_retention", "effective_retention"].includes(key))
    return v ? String(v) : "Sınırsız";
  if (["backup_interval", "effective_backup_interval"].includes(key))
    return v ? `${v} sn` : "Kapalı";
  if (typeof v === "boolean") return v ? "Etkin" : "Kapalı";
  return tag(String(v));
}
function Filters({
  columns,
  rules,
  onSave,
  onClose,
}: {
  columns: Column[];
  rules: Rule[];
  onSave: (r: Rule[]) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(rules);
  const change = (i: number, k: string, v: string) =>
    setDraft(draft.map((r, j) => (i === j ? { ...r, [k]: v } : r)));
  return (
    <Dialog title="Filtreler" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSave(draft);
          onClose();
        }}
      >
        <p className="muted">
          Koşullar sırayla, soldan sağa değerlendirilir. Her yeni koşulu önceki
          sonuca VE / VEYA ile bağlayın.
        </p>
        {draft.map((r, i) => (
          <div className="filter-rule" key={i}>
            <label>
              Bağlantı
              <select
                aria-label={`Koşul ${i + 1} bağlantısı`}
                disabled={!i}
                value={r.join}
                onChange={(e) => change(i, "join", e.target.value)}
              >
                <option value="and">VE</option>
                <option value="or">VEYA</option>
              </select>
            </label>
            <label>
              Alan
              <select
                aria-label={`Koşul ${i + 1} alanı`}
                value={r.field}
                onChange={(e) => change(i, "field", e.target.value)}
              >
                {columns.map((c) => (
                  <option key={c.key} value={c.key}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              İşlem
              <select
                aria-label={`Koşul ${i + 1} işlemi`}
                value={r.op}
                onChange={(e) => change(i, "op", e.target.value)}
              >
                {[
                  ["contains", "İçerir"],
                  ["eq", "Eşittir"],
                  ["ne", "Eşit değil"],
                  ["gt", "Büyüktür"],
                  ["lt", "Küçüktür"],
                ].map(([v, t]) => (
                  <option key={v} value={v}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Değer
              <input
                aria-label={`Koşul ${i + 1} değeri`}
                value={r.value}
                onChange={(e) => change(i, "value", e.target.value)}
              />
            </label>
            <button
              type="button"
              className="icon-button"
              aria-label={`Koşul ${i + 1} sil`}
              onClick={() => setDraft(draft.filter((_, j) => j !== i))}
            >
              <X size={18} />
            </button>
          </div>
        ))}
        <button
          type="button"
          className="secondary"
          disabled={draft.length >= 20}
          onClick={() =>
            setDraft([
              ...draft,
              { field: columns[0].key, op: "contains", value: "", join: "and" },
            ])
          }
        >
          <Plus size={16} />
          Koşul ekle
        </button>
        <div className="dialog-footer">
          <button
            type="button"
            className="secondary"
            onClick={() => setDraft([])}
          >
            Temizle
          </button>
          <button className="primary">Filtreleri uygula</button>
        </div>
      </form>
    </Dialog>
  );
}
function ColumnPicker({
  columns,
  shown,
  onSave,
  onClose,
}: {
  columns: Column[];
  shown: string[];
  onSave: (s: string[]) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(shown);
  return (
    <Dialog title="Sütunlar" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSave(draft);
          onClose();
        }}
      >
        <div className="choice-grid">
          {columns.map((c) => (
            <label className="choice-row" key={c.key}>
              <input
                type="checkbox"
                checked={draft.includes(c.key)}
                onChange={(e) =>
                  setDraft(
                    e.target.checked
                      ? [...draft, c.key]
                      : draft.filter((k) => k !== c.key),
                  )
                }
              />
              <span>{c.label}</span>
            </label>
          ))}
        </div>
        <div className="dialog-footer">
          <button className="primary" disabled={!draft.length}>
            Sütunları uygula
          </button>
        </div>
      </form>
    </Dialog>
  );
}
export function BulkEditor({
  ids,
  backup = false,
  onClose,
  onSaved,
}: {
  ids: string[];
  backup?: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [changes, setChanges] = useState<Row>({});
  const [refs, setRefs] = useState<Record<string, Row[]>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fields = backup
    ? [
        {
          key: "backup_group_id",
          label: "Yedek grubu",
          ref: "backup-groups",
          type: "select",
        },
        {
          key: "backup_interval",
          label: "Grupsuz cihaz aralığı (saniye)",
          type: "number",
        },
        {
          key: "backup_retention",
          label: "Grupsuz cihaz yedek sınırı",
          type: "number",
        },
      ]
    : PAGES.find((p) => p.key === "devices")!.fields!.filter((f) =>
        BULK.includes(f.key),
      );
  useEffect(() => {
    let active = true;
    Promise.all(
      ["vrfs", "sites", "credentials", "backup-groups"].map(async (key) => [
        key,
        await allRows("/" + key),
      ]),
    )
      .then((r) => {
        if (active) setRefs(Object.fromEntries(r));
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <Dialog
      title={backup ? "Yedekleme ayarlarını uygula" : "Toplu değiştir"}
      onClose={onClose}
    >
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api(
              backup ? "/backup-settings" : "/inventory/devices/bulk",
              "POST",
              { ids, action: "update", changes },
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
        <p className="muted">
          {ids.length} cihaz seçildi. Yalnızca işaretlediğiniz alanlar
          değiştirilir.
          {backup &&
            " Grup seçiliyse grubun aralık ve saklama ayarları kullanılır. 0: zamanlama kapalı / saklama sınırsız."}
        </p>
        <div className="bulk-fields">
          {fields.map((f: any) => {
            const enabled = f.key in changes;
            return (
              <div className="bulk-field" key={f.key}>
                <label className="choice-row">
                  <input
                    type="checkbox"
                    aria-label={`${f.label} değiştir`}
                    checked={enabled}
                    onChange={(e) => {
                      const next = { ...changes };
                      if (e.target.checked)
                        next[f.key] =
                          f.type === "checkbox"
                            ? false
                            : f.ref
                              ? null
                              : (f.default ?? "");
                      else delete next[f.key];
                      setChanges(next);
                    }}
                  />
                  <span>{f.label}</span>
                </label>
                {f.type === "checkbox" ? (
                  <select
                    aria-label={`${f.label} değeri`}
                    disabled={!enabled}
                    value={String(changes[f.key] ?? false)}
                    onChange={(e) =>
                      setChanges({
                        ...changes,
                        [f.key]: e.target.value === "true",
                      })
                    }
                  >
                    <option value="true">Etkin</option>
                    <option value="false">Kapalı</option>
                  </select>
                ) : f.type === "select" ? (
                  <select
                    aria-label={`${f.label} değeri`}
                    disabled={!enabled}
                    value={changes[f.key] ?? ""}
                    onChange={(e) =>
                      setChanges({
                        ...changes,
                        [f.key]: e.target.value || null,
                      })
                    }
                  >
                    <option value="">Seçiniz / atamayı kaldır</option>
                    {(f.ref
                      ? (refs[f.ref] || [])
                          .filter(
                            (r) =>
                              f.key !== "snmp_credential_id" ||
                              ["snmpv3", "snmpv2c"].includes(r.protocol),
                          )
                          .filter(
                            (r) =>
                              f.key !== "config_credential_id" ||
                              ["ssh", "rest"].includes(r.protocol),
                          )
                          .map((r) => [r.id, r.name])
                      : (f.options || []).map((o: any) =>
                          Array.isArray(o) ? o : [o, tag(o)],
                        )
                    ).map(([k, t]: string[]) => (
                      <option key={k} value={k}>
                        {t}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    aria-label={`${f.label} değeri`}
                    disabled={!enabled}
                    type={f.type || "text"}
                    value={changes[f.key] ?? ""}
                    onChange={(e) =>
                      setChanges({
                        ...changes,
                        [f.key]:
                          f.type === "number"
                            ? Number(e.target.value)
                            : e.target.value,
                      })
                    }
                  />
                )}
              </div>
            );
          })}
        </div>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="dialog-footer">
          <button type="button" className="secondary" onClick={onClose}>
            Vazgeç
          </button>
          <button
            className="primary"
            disabled={busy || !Object.keys(changes).length}
          >
            {busy ? "Uygulanıyor…" : "Seçilenlere uygula"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
export function InventoryTable({
  resource = "devices",
  purpose = "devices",
  deviceId,
  refresh,
  user,
  onDevice,
  onEdit,
  onSaved,
  onContent,
}: {
  resource?: string;
  purpose?: string;
  deviceId?: string;
  refresh: number;
  user: Row;
  onDevice?: (r: Row) => void;
  onEdit?: (r: Row) => void;
  onSaved: () => void;
  onContent?: (r: Row, action: string) => void;
}) {
  const [query, setQuery] = useState("");
  const search = useDeferredValue(query);
  const [rules, setRules] = useState<Rule[]>([]);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<Row>({ items: [], total: 0, columns: [] });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const loaded = useRef("");
  const [dialog, setDialog] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [group, setGroup] = useState("");
  const pref = `netrix-columns:${user.id}:${purpose}`;
  const [shown, setShown] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(pref) || "null");
      return (
        (Array.isArray(stored) &&
        stored.length &&
        stored.every((k) => typeof k === "string")
          ? stored
          : null) ||
        (purpose === "backup-settings"
          ? [
              "name",
              "backup_group",
              "effective_backup_interval",
              "effective_retention",
              "last_backup_at",
            ]
          : DEFAULTS[resource])
      );
    } catch {
      return purpose === "backup-settings"
        ? [
            "name",
            "backup_group",
            "effective_backup_interval",
            "effective_retention",
            "last_backup_at",
          ]
        : DEFAULTS[resource];
    }
  });
  const effective = rules;
  const encoded = JSON.stringify(effective);
  useEffect(() => {
    setSelected([]);
  }, [search, encoded, offset, deviceId, group]);
  useEffect(() => {
    let active = true;
    const qs = new URLSearchParams({
      q: search,
      filters: encoded,
      offset: String(offset),
      limit: "25",
      group_by: group,
      changed_only: String(purpose === "changes"),
    });
    if (deviceId) qs.set("device_id", deviceId);
    const key = qs.toString();
    setLoading(loaded.current !== key);
    api(`/inventory/${resource}?${qs}`)
      .then((d) => {
        if (active) {
          setData(d);
          if (offset && offset >= d.total)
            setOffset(Math.max(0, Math.ceil(d.total / 25) - 1) * 25);
          loaded.current = key;
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [resource, deviceId, refresh, search, encoded, offset, group]);
  const columns: Column[] = data.columns;
  const visible = columns.filter((c) => shown.includes(c.key));
  const writable = user.role !== "viewer";
  const hasActions =
    (["devices", "backup-devices"].includes(resource) &&
      Boolean(onDevice || (writable && onEdit))) ||
    (resource === "snapshots" && writable);
  const selectRows =
    writable &&
    purpose !== "interface-devices" &&
    ["devices", "interfaces"].includes(resource);
  const apply = async (action: string) => {
    setBusy(true);
    setError("");
    try {
      await api(`/inventory/${resource}/bulk`, "POST", {
        ids: selected,
        action,
      });
      setSelected([]);
      setDialog("");
      onSaved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel inventory-panel">
      <div className="inventory-toolbar">
        <label className="inventory-search">
          <span className="sr-only">Kayıtlarda ara</span>
          <input
            placeholder="Kayıtlarda ara…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <button
          className="secondary"
          disabled={!columns.length}
          onClick={() => setDialog("filters")}
        >
          <Funnel size={18} />
          Filtreler{rules.length ? ` (${rules.length})` : ""}
        </button>
        <button
          className="secondary"
          disabled={!columns.length}
          onClick={() => setDialog("columns")}
        >
          <Columns size={18} />
          Sütunlar
        </button>
        {resource === "snapshots" && !deviceId && (
          <label>
            Grupla
            <select
              value={group}
              onChange={(e) => {
                setGroup(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Gruplama yok</option>
              <option value="device_name">Cihaz</option>
              <option value="backup_group">Yedek grubu</option>
            </select>
          </label>
        )}
      </div>
      {selected.length > 0 && (
        <div className="inventory-selection">
          <b>{selected.length} kayıt seçildi</b>
          {resource === "devices" ? (
            <button className="secondary" onClick={() => setDialog("bulk")}>
              <PencilSimple size={16} />
              {purpose === "backup-settings"
                ? "Ayarları uygula"
                : "Toplu değiştir"}
            </button>
          ) : (
            <>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => apply("disable")}
              >
                Devre dışı bırak
              </button>
              <button
                className="secondary"
                disabled={busy}
                onClick={() => apply("enable")}
              >
                Etkinleştir
              </button>
            </>
          )}
          {user.role === "admin" && (
            <button className="secondary" onClick={() => setDialog("delete")}>
              <Trash size={16} />
              Sil
            </button>
          )}
          <button className="text-button" onClick={() => setSelected([])}>
            Seçimi kaldır
          </button>
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading && (
        <p role="status" className="muted">
          Kayıtlar yükleniyor…
        </p>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {selectRows && (
                <th className="selection-cell">
                  <input
                    aria-label="Bu sayfadaki kayıtları seç"
                    disabled={loading}
                    type="checkbox"
                    checked={
                      data.items.length > 0 &&
                      data.items.every((r: Row) => selected.includes(r.id))
                    }
                    ref={(el) => {
                      if (el)
                        el.indeterminate =
                          selected.length > 0 &&
                          !data.items.every((r: Row) =>
                            selected.includes(r.id),
                          );
                    }}
                    onChange={(e) =>
                      setSelected(
                        e.target.checked
                          ? data.items.map((r: Row) => r.id)
                          : [],
                      )
                    }
                  />
                </th>
              )}
              {visible.map((c) => (
                <th key={c.key}>{c.label}</th>
              ))}
              {hasActions && <th>İşlemler</th>}
            </tr>
          </thead>
          <tbody>
            {data.items.map((row: Row, i: number) => (
              <React.Fragment key={row.id}>
                {group &&
                  (i === 0 || row[group] !== data.items[i - 1][group]) && (
                    <tr className="inventory-group">
                      <th
                        colSpan={
                          visible.length +
                          (hasActions ? 1 : 0) +
                          (selectRows ? 1 : 0)
                        }
                      >
                        {row[group] || "Grupsuz"}
                      </th>
                    </tr>
                  )}
                <tr>
                  {selectRows && (
                    <td className="selection-cell">
                      <input
                        type="checkbox"
                        aria-label={`${row.name} seç`}
                        disabled={loading}
                        checked={selected.includes(row.id)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, row.id]
                              : selected.filter((id) => id !== row.id),
                          )
                        }
                      />
                    </td>
                  )}
                  {visible.map((c) => (
                    <td key={c.key}>
                      {c.key === "name" && onDevice ? (
                        <button
                          className="text-button"
                          onClick={() => onDevice(row)}
                        >
                          {row.name}
                        </button>
                      ) : (
                        value(c.key, row[c.key])
                      )}
                    </td>
                  ))}
                  {hasActions && (
                    <td>
                      <div className="inventory-actions">
                        {["devices", "backup-devices"].includes(resource) && (
                          <>
                            {onDevice && (
                              <button
                                className="icon-button"
                                aria-label={`${row.name} ${resource === "backup-devices" ? "yedekleri" : purpose === "interface-devices" ? "arayüzleri" : "ayrıntıları"}`}
                                onClick={() => onDevice(row)}
                              >
                                <Eye size={18} />
                              </button>
                            )}
                            {writable && onEdit && (
                              <button
                                className="icon-button"
                                aria-label="Kaydı düzenle"
                                onClick={() => onEdit(row)}
                              >
                                <PencilSimple size={18} />
                              </button>
                            )}
                          </>
                        )}
                        {resource === "snapshots" && writable && (
                          <>
                            <button
                              className="text-button"
                              onClick={() =>
                                onContent?.(
                                  row,
                                  purpose === "compare" ? "compare" : "content",
                                )
                              }
                            >
                              {purpose === "compare"
                                ? "Aktif config ile karşılaştır"
                                : "Görüntüle"}
                            </button>
                            <button
                              className="icon-button"
                              aria-label="Yedeği indir"
                              onClick={() => onContent?.(row, "download")}
                            >
                              <DownloadSimple size={18} />
                            </button>
                            <button
                              className="text-button"
                              onClick={() => onContent?.(row, "diff")}
                            >
                              Fark
                            </button>
                            {user.role === "admin" && (
                              <button
                                className="icon-button"
                                aria-label="Yedeği sil"
                                onClick={() => onContent?.(row, "delete")}
                              >
                                <Trash size={18} />
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {!loading && !data.items.length && (
        <p className="empty-inline">Bu koşullara uyan kayıt bulunamadı.</p>
      )}
      <footer className="inventory-pagination">
        <span>
          {data.total} {resource === "backup-devices" ? "cihaz" : "kayıt"}
          {selectRows ? ` · ${selected.length} seçili` : ""}
        </span>
        <div>
          <button
            className="secondary"
            disabled={!offset || loading}
            onClick={() => setOffset(Math.max(0, offset - 25))}
          >
            Önceki
          </button>
          <span>{Math.floor(offset / 25) + 1}</span>
          <button
            className="secondary"
            disabled={offset + 25 >= data.total || loading}
            onClick={() => setOffset(offset + 25)}
          >
            Sonraki
          </button>
        </div>
      </footer>
      {dialog === "filters" && (
        <Filters
          columns={columns}
          rules={rules}
          onSave={(r) => {
            setRules(r);
            setOffset(0);
          }}
          onClose={() => setDialog("")}
        />
      )}
      {dialog === "columns" && (
        <ColumnPicker
          columns={columns}
          shown={shown}
          onSave={(s) => {
            setShown(s);
            try {
              localStorage.setItem(pref, JSON.stringify(s));
            } catch {}
          }}
          onClose={() => setDialog("")}
        />
      )}
      {dialog === "bulk" && (
        <BulkEditor
          ids={selected}
          backup={purpose === "backup-settings"}
          onSaved={() => {
            onSaved();
            setSelected([]);
          }}
          onClose={() => setDialog("")}
        />
      )}
      {dialog === "delete" && (
        <Dialog title="Seçilen kayıtları sil" onClose={() => setDialog("")}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              apply("delete");
            }}
          >
            <p>
              {selected.length} kayıt uygulama listesinden kaldırılacak. Geçmiş
              kayıtlar korunur.
            </p>
            <div className="dialog-footer">
              <button
                className="secondary"
                type="button"
                onClick={() => setDialog("")}
              >
                Vazgeç
              </button>
              <button className="primary" disabled={busy}>
                Seçilenleri sil
              </button>
            </div>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
          </form>
        </Dialog>
      )}
    </section>
  );
}
export function InterfaceWorkspace(props: any) {
  const [device, setDevice] = useState<Row | null>(null);
  return (
    <>
      {device && (
        <div className="inventory-breadcrumb">
          <button className="secondary" onClick={() => setDevice(null)}>
            <ArrowLeft size={18} />
            Cihazlara dön
          </button>
          <h2>
            {device.name} · {tag(device.kind)}
          </h2>
        </div>
      )}
      <InventoryTable
        {...props}
        key={device?.id || "devices"}
        resource={device ? "interfaces" : "devices"}
        purpose={device ? "interfaces" : "interface-devices"}
        deviceId={device?.id}
        onDevice={device ? undefined : setDevice}
        onEdit={undefined}
      />
    </>
  );
}
export function InterfacePicker({
  device,
  canWrite,
  onSaved,
}: {
  device: Row;
  canWrite: boolean;
  onSaved: () => void;
}) {
  const [ports, setPorts] = useState<Row[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    allRows(`/inventory/interfaces?candidates=true&device_id=${device.id}`)
      .then((rows) => {
        if (active) {
          setPorts(rows);
          setSelected(
            rows.filter((r) => r.is_managed && !r.is_deleted).map((r) => r.id),
          );
          setReady(true);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [device.id]);
  const visible = ports.filter((r) =>
    Object.values(r).some((v) =>
      String(v ?? "")
        .toLocaleLowerCase("tr")
        .includes(query.toLocaleLowerCase("tr")),
    ),
  );
  return (
    <section className="interface-picker">
      <h3>
        Arayüz seçimi{" "}
        <span className="count-pill">
          {selected.length} / {ports.length}
        </span>
      </h3>
      <p className="muted">
        Uygulamaya eklenecek arayüzleri seçin. Port durumları cihazdan
        gözlemlenir; bu seçim cihaz yapılandırmasını değiştirmez.
      </p>
      <div className="inventory-toolbar">
        <label className="inventory-search">
          <span className="sr-only">Arayüzlerde ara</span>
          <input
            placeholder="Arayüzlerde ara…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        {canWrite && (
          <>
            <button
              className="secondary"
              type="button"
              onClick={() =>
                setSelected([
                  ...new Set([...selected, ...visible.map((p) => p.id)]),
                ])
              }
            >
              Görünenleri seç
            </button>
            <button
              className="secondary"
              type="button"
              onClick={() =>
                setSelected(
                  selected.filter((id) => !visible.some((p) => p.id === id)),
                )
              }
            >
              Görünenleri kaldır
            </button>
          </>
        )}
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="port-grid selectable-ports">
        {visible.map((p) => (
          <label className="port-choice" key={p.id}>
            <input
              type="checkbox"
              disabled={!canWrite || busy}
              aria-label={`${p.name} uygulamaya ekle`}
              checked={selected.includes(p.id)}
              onChange={(e) =>
                setSelected(
                  e.target.checked
                    ? [...selected, p.id]
                    : selected.filter((id) => id !== p.id),
                )
              }
            />
            <span>
              <b>{p.name}</b>
              <small>
                {speed(p.speed_bps)} · {tag(p.oper_status)}
              </small>
            </span>
          </label>
        ))}
      </div>
      {!ports.length && (
        <p className="muted">
          {ready
            ? "İlk başarılı SNMP gözleminden sonra arayüzler burada görünür."
            : "Arayüzler yükleniyor…"}
        </p>
      )}
      {canWrite && (
        <div className="dialog-footer">
          <button
            className="primary"
            disabled={!ready || busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await api(`/devices/${device.id}/interfaces`, "PUT", {
                  ids: selected,
                });
                onSaved();
              } catch (e: any) {
                setError(e.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Kaydediliyor…" : "Arayüz seçimini kaydet"}
          </button>
        </div>
      )}
    </section>
  );
}
