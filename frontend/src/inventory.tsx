import { useLiveQuery } from "./data";
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
  ArrowCounterClockwise,
  ArrowUp,
  ArrowDown,
  ArrowsDownUp,
} from "@phosphor-icons/react";
import {
  api,
  Badge,
  Dialog,
  PAGES,
  tag,
  date,
  speed,
  resourceChoices,
} from "./main";
import "./inventory.css";
import { LinkLabelEditor } from "./link-label-editor";
import { LinkDeleteDialog } from "./link-delete-dialog";
import {
  DeviceTransferImport,
  TransferMenu,
  downloadDevices,
} from "./device-csv";
type Row = Record<string, any>;
type Column = { key: string; label: string };
type Rule = { field: string; op: string; value: string; join: string };
const BULK = [
  "backup_group_id",
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
  "backup_interval",
];
const DEFAULTS: Record<string, string[]> = {
  links: [
    "device_name",
    "interface_name",
    "remote_name",
    "remote_port",
    "source",
    "confidence_percent",
  ],
  "topology-devices": [
    "name",
    "management_ip",
    "kind",
    "neighbor_count",
    "latest_neighbor_at",
  ],
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
  ],
  snapshots: [
    "device_name",
    "backup_group",
    "created_at",
    "size_bytes",
    "is_base",
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
  if (key === "confidence_percent")
    return `${Math.round(v)}% · ${v < 90 ? "Belirsiz" : "Doğrulandı"}`;
  if (key === "source")
    return v === "manual"
      ? "Kullanıcı doğrulaması"
      : String(v).toUpperCase().replace("+", " + ");
  if (key.endsWith("_at")) return date(v);
  if (key === "speed_bps") return speed(v);
  if (key === "is_base")
    return v ? <span className="base-config-label">Base config</span> : "—";
  if (key === "changed") return v ? "Değişti" : "Değişmedi";
  if (["backup_retention", "effective_retention"].includes(key))
    return v ? String(v) : "Sınırsız";
  if (["backup_interval", "effective_backup_interval"].includes(key))
    return v ? `${v} sn` : "Kapalı";
  if (typeof v === "boolean") return v ? "Etkin" : "Kapalı";
  return tag(String(v));
}
export function Filters({
  columns,
  wide = false,
  rules,
  onSave,
  onClose,
}: {
  columns: Column[];
  wide?: boolean;
  rules: Rule[];
  onSave: (r: Rule[]) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(rules);
  const change = (i: number, k: string, v: string) =>
    setDraft(draft.map((r, j) => (i === j ? { ...r, [k]: v } : r)));
  return (
    <Dialog title="Filtreler" onClose={onClose} wide={wide}>
      <form
        className={wide ? "topology-filter-form" : undefined}
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
                  ["not_contains", "İçermez"],
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
export function ColumnPicker({
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
      ["vrfs", "sites", "credentials", "backup-groups", "device-types"].map(
        async (key) => [key, await allRows("/" + key)],
      ),
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
          {backup
            ? " Grup seçiliyse grubun aralık ve saklama ayarları kullanılır. 0: zamanlama kapalı / saklama sınırsız."
            : " Üretici, cihaz türü ve model için uyguladığınız değerler cihaz sorgularında korunur."}
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
                      ? resourceChoices(f, refs, changes, "devices")
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
                          .map((r) => [
                            f.ref === "device-types" ? r.code : r.id,
                            r.name,
                          ])
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
  onDelete,
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
  onDelete?: (r: Row) => void;
  onSaved: () => void;
  onContent?: (r: Row, action: string) => void;
}) {
  const [query, setQuery] = useState("");
  const search = useDeferredValue(query);
  const [rules, setRules] = useState<Rule[]>([]);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<{ key: string; direction: "asc" | "desc" }>({
    key: "",
    direction: "asc",
  });
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [group, setGroup] = useState("");
  const [notice, setNotice] = useState("");
  const archive = purpose === "archive";
  const deletedLinks = purpose === "deleted-links";
  const restorable = archive || deletedLinks;
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
  }, [search, encoded, offset, deviceId, group, sort]);
  const qs = new URLSearchParams({
    q: search,
    filters: encoded,
    offset: String(offset),
    limit: "25",
    group_by: group,
    changed_only: String(purpose === "changes"),
    archived: String(archive),
    deleted: String(deletedLinks),
    sort_by: sort.key,
    sort_direction: sort.direction,
  });
  if (deviceId) qs.set("device_id", deviceId);
  const listing = useLiveQuery(
    `/inventory/${resource}?${qs}`,
    refresh,
    undefined,
    search ? 200 : 0,
  );
  const data: Row = listing.data || { items: [], total: 0, columns: [] };
  const loading = listing.loading;
  useEffect(() => {
    if (listing.data && offset && offset >= listing.data.total)
      setOffset(Math.max(0, Math.ceil(listing.data.total / 25) - 1) * 25);
  }, [listing.data, offset]);
  useEffect(() => {
    setError(listing.error);
  }, [listing.error]);
  const columns: Column[] = data.columns;
  const visible = columns.filter((c) => shown.includes(c.key));
  const writable = user.role !== "viewer";
  const hasActions =
    (restorable && user.role === "admin") ||
    (["devices", "backup-devices", "topology-devices"].includes(resource) &&
      Boolean(onDevice || (writable && onEdit))) ||
    (resource === "snapshots" && writable) ||
    (resource === "links" &&
      Boolean(
        onContent ||
        (writable && onEdit) ||
        (user.role === "admin" && onDelete),
      ));
  const selectRows =
    writable &&
    (!archive || user.role === "admin") &&
    purpose !== "interface-devices" &&
    (["devices", "interfaces"].includes(resource) ||
      (resource === "links" && user.role === "admin"));
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
      setNotice(
        action === "purge"
          ? `${selected.length} cihaz kalıcı silindi.`
          : action === "restore"
            ? deletedLinks
              ? `${selected.length} komşuluk kaydı geri yüklendi. Tarama engelleri kaldırıldı.`
              : `${selected.length} cihaz geri yüklendi. Cihaz envanterinde Bakımda durumunda görünecek.`
            : action === "delete" && resource === "devices"
              ? `${selected.length} cihaz arşivlendi. Envanter → Arşivlenmiş cihazlar menüsünden geri yükleyebilirsiniz.`
              : action === "delete" && resource === "links"
                ? `${selected.length} komşuluk kaydı silindi. Sonraki taramalarda yeniden eklenmeleri engellendi.`
                : "İşlem tamamlandı.",
      );
      onSaved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      className={`panel inventory-panel ${["links", "topology-devices"].includes(resource) ? "topology-table" : ""}`}
      aria-label={
        deletedLinks
          ? "Silinen komşuluk kayıtları"
          : resource === "links"
            ? "Bağlantı kayıtları"
            : resource === "topology-devices"
              ? "Bağlantı cihazları"
              : undefined
      }
    >
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
        {purpose === "devices" && writable && (
          <>
            <TransferMenu
              mode="import"
              disabled={busy}
              onSelect={(format) => setDialog(format)}
            />
            <TransferMenu
              mode="export"
              disabled={!selected.length || busy || loading}
              onSelect={async (format) => {
                setBusy(true);
                setError("");
                try {
                  await downloadDevices(format, selected);
                } catch (e: any) {
                  setError(e.message);
                } finally {
                  setBusy(false);
                }
              }}
            />
          </>
        )}
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
      {(selected.length > 0 || (archive && user.role === "admin")) && (
        <div
          className={`inventory-selection${archive ? " archive-selection" : ""}`}
        >
          <b role="status">{selected.length} kayıt seçildi</b>
          {restorable ? (
            <button
              className="secondary"
              disabled={busy || loading || !selected.length}
              onClick={() => setDialog("restore")}
            >
              <ArrowCounterClockwise size={16} />
              {archive ? "Toplu geri yükle" : "Geri yükle"}
            </button>
          ) : resource === "devices" ? (
            <button className="secondary" onClick={() => setDialog("bulk")}>
              <PencilSimple size={16} />
              {purpose === "backup-settings"
                ? "Ayarları uygula"
                : "Toplu değiştir"}
            </button>
          ) : null}
          {archive && user.role === "admin" && (
            <button
              className="secondary delete-confirm archive-delete"
              disabled={busy || loading || !selected.length}
              onClick={() => setDialog("purge")}
            >
              <Trash size={16} aria-hidden="true" />
              Kalıcı sil
            </button>
          )}
          {user.role === "admin" && !restorable && (
            <button className="secondary" onClick={() => setDialog("delete")}>
              <Trash size={16} aria-hidden="true" />
              Sil
            </button>
          )}
          {selected.length > 0 && (
            <button className="text-button" onClick={() => setSelected([])}>
              Seçimi kaldır
            </button>
          )}
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
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
                  <label
                    className={
                      resource === "links"
                        ? "neighbor-selection-control"
                        : "inventory-selection-control"
                    }
                  >
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
                  </label>
                </th>
              )}
              {visible.map((c) => (
                <th
                  key={c.key}
                  className="sortable-heading"
                  aria-label={c.label}
                  aria-sort={
                    sort.key === c.key
                      ? sort.direction === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                >
                  <button
                    type="button"
                    className="column-sort"
                    aria-label={`${c.label}: ${sort.key === c.key && sort.direction === "asc" ? "azalan" : "artan"} sırala`}
                    onClick={() => {
                      setSort((current) => ({
                        key: c.key,
                        direction:
                          current.key === c.key && current.direction === "asc"
                            ? "desc"
                            : "asc",
                      }));
                      setOffset(0);
                    }}
                  >
                    <span>{c.label}</span>
                    {sort.key !== c.key ? (
                      <ArrowsDownUp size={16} aria-hidden="true" />
                    ) : sort.direction === "asc" ? (
                      <ArrowUp size={16} aria-hidden="true" />
                    ) : (
                      <ArrowDown size={16} aria-hidden="true" />
                    )}
                  </button>
                </th>
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
                <tr className={row.is_base ? "base-config-row" : undefined}>
                  {selectRows && (
                    <td className="selection-cell">
                      <label
                        className={
                          resource === "links"
                            ? "neighbor-selection-control"
                            : "inventory-selection-control"
                        }
                      >
                        <input
                          type="checkbox"
                          aria-label={
                            resource === "links"
                              ? `${row.interface_name || "Bilinmeyen port"} · ${row.remote_name} komşuluğunu seç`
                              : `${row.name} seç`
                          }
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
                      </label>
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
                      ) : c.key === "kind" ? (
                        row.kind_name || row.kind
                      ) : c.key === "device_kind" ? (
                        row.device_kind_name || tag(row.device_kind)
                      ) : resource === "links" &&
                        ["remote_name", "remote_port"].includes(c.key) &&
                        row[`manual_${c.key}`] != null ? (
                        <span className="edited-link-value">
                          {value(c.key, row[c.key])}
                          <small className="muted">Düzenlendi</small>
                        </span>
                      ) : (
                        value(c.key, row[c.key])
                      )}
                    </td>
                  ))}
                  {hasActions && (
                    <td>
                      <div className="inventory-actions">
                        {resource === "links" && writable && onEdit && (
                          <button
                            className="icon-button"
                            aria-label={`${row.interface_name || "Portsuz"} komşuluğunu düzenle`}
                            onClick={() => onEdit(row)}
                          >
                            <PencilSimple size={18} aria-hidden="true" />
                          </button>
                        )}
                        {resource === "links" &&
                          user.role === "admin" &&
                          onDelete && (
                            <button
                              className="icon-button"
                              aria-label={`${row.interface_name || "Portsuz"} komşuluğunu sil`}
                              onClick={() => onDelete(row)}
                            >
                              <Trash size={18} aria-hidden="true" />
                            </button>
                          )}
                        {resource === "links" && onContent && (
                          <button
                            className="icon-button"
                            aria-label="Kayıt ayrıntıları"
                            onClick={() => onContent?.(row, "details")}
                          >
                            <Eye size={18} aria-hidden="true" />
                          </button>
                        )}
                        {archive && user.role === "admin" && (
                          <button
                            className="secondary delete-confirm archive-delete"
                            disabled={busy || loading}
                            aria-label={`${row.name} kalıcı sil`}
                            onClick={() => {
                              setSelected([row.id]);
                              setDialog("purge");
                            }}
                          >
                            <Trash size={18} aria-hidden="true" />
                            Kalıcı sil
                          </button>
                        )}
                        {restorable && user.role === "admin" && (
                          <button
                            className="secondary"
                            disabled={busy || loading}
                            aria-label={
                              deletedLinks
                                ? `${row.interface_name || "Bilinmeyen port"} · ${row.remote_name} komşuluğunu geri yükle`
                                : `${row.name} geri yükle`
                            }
                            onClick={() => {
                              setSelected([row.id]);
                              setDialog("restore");
                            }}
                          >
                            <ArrowCounterClockwise
                              size={18}
                              aria-hidden="true"
                            />
                            Geri yükle
                          </button>
                        )}
                        {[
                          "devices",
                          "backup-devices",
                          "topology-devices",
                        ].includes(resource) && (
                          <>
                            {onDevice && (
                              <button
                                className="icon-button"
                                aria-label={`${row.name} ${resource === "topology-devices" ? "komşulukları" : resource === "backup-devices" ? "yedekleri" : purpose === "interface-devices" ? "arayüzleri" : "ayrıntıları"}`}
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
                            {!row.is_base && (
                              <button
                                className="text-button"
                                onClick={() => onContent?.(row, "base")}
                              >
                                Base config yap
                              </button>
                            )}
                            {purpose === "changes" && (
                              <button
                                className="secondary"
                                onClick={() => onContent?.(row, "approve")}
                              >
                                Onayla
                              </button>
                            )}
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
        <div className="empty-state">
          <p>Bu koşullara uyan kayıt bulunamadı.</p>
        </div>
      )}
      <footer className="inventory-pagination">
        <span>
          {data.total}{" "}
          {["backup-devices", "topology-devices"].includes(resource)
            ? "cihaz"
            : "kayıt"}
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
      {(dialog === "csv" || dialog === "xlsx") && (
        <DeviceTransferImport
          format={dialog}
          onClose={() => setDialog("")}
          onSaved={() => {
            setSelected([]);
            onSaved();
          }}
        />
      )}
      {dialog === "filters" && (
        <Filters
          wide={["links", "topology-devices"].includes(resource)}
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
        <Dialog
          title={
            resource === "devices"
              ? "Seçilen cihazları arşivle"
              : resource === "links"
                ? "Seçilen komşulukları sil"
                : "Seçilen kayıtları sil"
          }
          onClose={() => {
            if (!busy) setDialog("");
          }}
        >
          <form
            className={resource === "links" ? "link-delete-form" : undefined}
            onSubmit={(e) => {
              e.preventDefault();
              apply("delete");
            }}
          >
            <p>
              {resource === "devices"
                ? `${selected.length} cihaz arşivlenecek. Geçmişi korunur; Envanter → Arşivlenmiş cihazlar menüsünden geri yükleyebilirsiniz.`
                : resource === "links"
                  ? `${selected.length} komşuluk kaydı silinecek ve sonraki taramalarda yeniden eklenmeleri engellenecek. Silinen komşuluklar menüsünden geri yükleyebilirsiniz.`
                  : `${selected.length} kayıt uygulama listesinden kaldırılacak. Geçmiş kayıtlar korunur.`}
            </p>
            <div className="dialog-footer">
              <button
                className="secondary"
                type="button"
                disabled={busy}
                onClick={() => setDialog("")}
              >
                Vazgeç
              </button>
              <button
                className={
                  resource === "links" ? "secondary delete-confirm" : "primary"
                }
                disabled={busy || !selected.length}
              >
                {busy
                  ? "İşleniyor…"
                  : resource === "links"
                    ? "Seçilenleri sil ve engelle"
                    : resource === "devices"
                      ? "Seçilenleri arşivle"
                      : "Seçilenleri sil"}
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
      {dialog === "purge" && (
        <Dialog
          title="Cihazları kalıcı sil"
          onClose={() => {
            if (!busy) setDialog("");
          }}
        >
          <form
            className="archive-purge-form"
            onSubmit={(e) => {
              e.preventDefault();
              apply("purge");
            }}
          >
            <p>
              <strong>
                {selected.length} cihaz kalıcı silinecek. Bu işlem geri
                alınamaz.
              </strong>
            </p>
            <p>
              Cihazların arayüzleri, konfigürasyon yedekleri (base config
              dahil), keşif gözlemleri, alarm kayıtları, bağlantıları ve kabin
              yerleşimleri silinir.
            </p>
            <p className="muted">
              IPAM adresleri, ortak profiller ve işlem geçmişi korunur; silinen
              cihazlarla ilişkileri kaldırılır. Etkin bir keşif aynı cihazı
              yeniden bulursa yeni kayıt oluşturabilir.
            </p>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <div className="dialog-footer">
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setDialog("")}
              >
                Vazgeç
              </button>
              <button
                className="secondary delete-confirm archive-delete"
                disabled={busy || !selected.length}
              >
                <Trash size={18} aria-hidden="true" />
                {busy ? "Siliniyor…" : `${selected.length} cihazı kalıcı sil`}
              </button>
            </div>
          </form>
        </Dialog>
      )}
      {dialog === "restore" && (
        <Dialog
          title={
            deletedLinks ? "Komşulukları geri yükle" : "Cihazları geri yükle"
          }
          onClose={() => {
            if (!busy) setDialog("");
          }}
        >
          <form
            className={deletedLinks ? "link-restore-form" : undefined}
            onSubmit={(e) => {
              e.preventDefault();
              apply("restore");
            }}
          >
            <p>
              {deletedLinks
                ? `${selected.length} komşuluk kaydı bağlantı haritasına geri yüklenecek ve sonraki taramalarda yeniden güncellenebilecek.`
                : `${selected.length} cihaz, aynı kayıt kimliği ve geçmişiyle cihaz envanterine dönecek.`}
            </p>
            <p className="muted">
              {deletedLinks ? (
                "Düzenlediğiniz komşu ve uzak port değerleri korunur. Son görülme tarihi değişmez."
              ) : (
                <>
                  Cihazlar Bakımda durumuyla geri yüklenir; otomatik yedekleme
                  başlamaz. Cihaz ayarlarından yaşam döngüsünü Aktif yapabilir,
                  zamanlamaları düzenleyebilirsiniz.
                </>
              )}
            </p>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <div className="dialog-footer">
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setDialog("")}
              >
                Vazgeç
              </button>
              <button className="primary" disabled={busy || !selected.length}>
                <ArrowCounterClockwise size={18} aria-hidden="true" />
                {busy ? "Geri yükleniyor…" : "Geri yükle"}
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </section>
  );
}
export function TopologyRecords(
  props: Pick<
    React.ComponentProps<typeof InventoryTable>,
    "refresh" | "user" | "onSaved" | "onContent"
  >,
) {
  const [device, setDevice] = useState<Row | null>(null);
  const [deleting, setDeleting] = useState<Row | null>(null);
  const [editing, setEditing] = useState<Row | null>(null);
  const [notice, setNotice] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (device) heading.current?.focus();
    else trigger.current?.focus();
  }, [device]);
  return (
    <>
      {notice && <p role="status">{notice}</p>}
      <div className="topology-directory" hidden={Boolean(device)}>
        <InventoryTable
          {...props}
          resource="topology-devices"
          purpose="topology-devices"
          onDevice={(row) => {
            trigger.current = document.activeElement as HTMLElement;
            setDevice(row);
          }}
        />
      </div>
      {device && (
        <>
          <div className="inventory-breadcrumb topology-breadcrumb">
            <button className="secondary" onClick={() => setDevice(null)}>
              <ArrowLeft size={18} aria-hidden="true" /> Cihazlara dön
            </button>
            <div>
              <h2 ref={heading} tabIndex={-1}>
                {device.name} komşulukları
              </h2>
              <p>{device.management_ip}</p>
            </div>
          </div>
          <InventoryTable
            {...props}
            key={device.id}
            resource="links"
            purpose="topology"
            deviceId={device.id}
            onDelete={(row) => {
              setNotice("");
              setDeleting(row);
            }}
            onEdit={(row) => {
              setNotice("");
              setEditing(row);
            }}
          />
        </>
      )}
      {deleting && (
        <LinkDeleteDialog
          row={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => {
            setDeleting(null);
            setNotice(
              "Komşuluk silindi. Sonraki taramalarda yeniden eklenmeyecek.",
            );
            props.onSaved();
            heading.current?.focus();
          }}
        />
      )}
      {editing && (
        <LinkLabelEditor
          row={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            setNotice("Komşuluk kaydı güncellendi.");
            props.onSaved();
          }}
        />
      )}
    </>
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
            {device.name} · {device.kind_name || tag(device.kind)}
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
  refresh,
  canWrite,
  onSaved,
}: {
  device: Row;
  refresh: number;
  canWrite: boolean;
  onSaved: () => void;
}) {
  const [ports, setPorts] = useState<Row[]>([]);
  const [changes, setChanges] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const selected = ports
    .filter((p) => changes[p.id] ?? (p.is_managed && !p.is_deleted))
    .map((p) => p.id);
  const choose = (ids: string[], checked: boolean) =>
    setChanges((current) => ({
      ...current,
      ...Object.fromEntries(ids.map((id) => [id, checked])),
    }));
  useEffect(() => {
    if (busy) return;
    let active = true;
    allRows(`/inventory/interfaces?candidates=true&device_id=${device.id}`)
      .then((rows) => {
        if (active) {
          setPorts(rows);
          setReady(true);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [device.id, refresh, busy]);
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
        Açık portlar otomatik eklenir; kapalı portlar açıldıklarında eklenir.
        İşaretini kaldırıp kaydettiğiniz portlar tekrar açılsa da eklenmez.
        Önceden eklenen portlar kapandığında listede kalır. Bu seçim cihaz
        yapılandırmasını değiştirmez.
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
              disabled={!ready || busy}
              onClick={() =>
                choose(
                  visible.map((p) => p.id),
                  true,
                )
              }
            >
              Görünenleri seç
            </button>
            <button
              className="secondary"
              type="button"
              disabled={!ready || busy}
              onClick={() =>
                choose(
                  visible.map((p) => p.id),
                  false,
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
              onChange={(e) => choose([p.id], e.target.checked)}
            />
            <span>
              <b>{p.name}</b>
              <small>
                {speed(p.speed_bps)} · {tag(p.oper_status)}
              </small>
              {(changes[p.id] === false ||
                (changes[p.id] === undefined && p.auto_add_excluded)) && (
                <small>Otomatik ekleme kapalı</small>
              )}
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
            disabled={!ready || busy || !Object.keys(changes).length}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await api(`/devices/${device.id}/interfaces`, "PUT", {
                  include_ids: Object.keys(changes).filter((id) => changes[id]),
                  exclude_ids: Object.keys(changes).filter(
                    (id) => !changes[id],
                  ),
                });
                setPorts((current) =>
                  current.map((p) =>
                    p.id in changes
                      ? {
                          ...p,
                          is_managed: changes[p.id],
                          auto_add_excluded: !changes[p.id],
                          is_deleted: changes[p.id] ? false : p.is_deleted,
                        }
                      : p,
                  ),
                );
                setChanges({});
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
