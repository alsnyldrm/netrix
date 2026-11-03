import React, { useDeferredValue, useEffect, useRef, useState } from "react";
import {
  Check,
  Funnel,
  Key,
  Palette,
  Clock,
  SlidersHorizontal,
  UserCircle,
  Plus,
  PencilSimple,
  Trash,
  MagnifyingGlass,
  ShieldCheck,
} from "@phosphor-icons/react";
import { Filters } from "./inventory";
import { api, useLiveQuery } from "./data";
import { Dialog, tag } from "./main";
import {
  applyPreferences,
  currentPreferences,
  defaultPreferences,
} from "./preferences";
import type { Preferences } from "./preferences";
import "./user-workspace.css";
type Row = Record<string, any>;
const palettes = [
  ["cobalt", "Teknik kobalt", "#1d4ed8"],
  ["teal", "Atlantik", "#0f766e"],
  ["violet", "Ametist", "#6d28d9"],
  ["amber", "Bakır", "#92400e"],
  ["forest", "Orman", "#166534"],
  ["slate", "Grafit", "#475569"],
];
export function Profile({
  user,
  onClose,
  onChanged,
}: {
  user: Row;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState("account");
  const [values, setValues] = useState<Preferences>(currentPreferences());
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async (next: Preferences) => {
    const previous = values;
    setValues(next);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = await api("/access/preferences", "PUT", next);
      setValues(saved);
      applyPreferences(saved);
      onChanged();
      setNotice("Tercihleriniz kaydedildi.");
    } catch (e: any) {
      setValues(previous);
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const tabs = [
    ["account", "Hesabım", UserCircle],
    ["palette", "Renk paleti", Palette],
    ["region", "Tarih, saat ve bölge", Clock],
    ["features", "Özellikler", SlidersHorizontal],
    ["ssh", "SSH Bağlantısı", Key],
    ["device-groups", "Cihaz grupları", ShieldCheck],
  ] as const;
  return (
    <Dialog title="Profil" onClose={onClose} wide>
      <div className="profile-layout">
        <nav className="profile-menu" aria-label="Profil bölümleri">
          {tabs.map(([id, name, Icon]) => (
            <React.Fragment key={id}>
              {id === "ssh" && (
                <h3 className="profile-menu-group">Cihaz yetkisi</h3>
              )}
              <button
                key={id}
                className={tab === id ? "selected" : ""}
                aria-current={tab === id ? "page" : undefined}
                onClick={() => {
                  setTab(id);
                  setNotice("");
                }}
              >
                <Icon size={20} />
                <span>{name}</span>
              </button>
            </React.Fragment>
          ))}
        </nav>
        <section className="profile-content">
          {tab === "ssh" && <SSHSettings />}
          {tab === "device-groups" && <AccessGroups user={user} />}
          {tab === "account" && (
            <>
              <span className="eyebrow">Kişisel çalışma alanı</span>
              <h3>{user.display_name}</h3>
              <dl className="profile-details">
                <div>
                  <dt>E-posta</dt>
                  <dd>{user.email}</dd>
                </div>
                <div>
                  <dt>Rol</dt>
                  <dd>{tag(user.role)}</dd>
                </div>
                <div>
                  <dt>Hesap durumu</dt>
                  <dd>Etkin</dd>
                </div>
                <div>
                  <dt>Saat dilimi</dt>
                  <dd>{values.timezone}</dd>
                </div>
              </dl>
              <p className="muted">
                Tercihleriniz hesabınıza özeldir ve diğer kullanıcıları
                etkilemez.
              </p>
            </>
          )}
          {tab === "palette" && (
            <>
              <h3>Çalışma alanınızın rengi</h3>
              <p className="muted">
                Her palet açık ve koyu temada ayrı renk değerleri kullanır.
              </p>
              <div className="palette-grid">
                {palettes.map(([id, name, color]) => (
                  <button
                    disabled={busy}
                    key={id}
                    className={
                      "palette-option" +
                      (values.palette === id ? " selected" : "")
                    }
                    aria-pressed={values.palette === id}
                    onClick={() => void save({ ...values, palette: id })}
                  >
                    <span
                      className="palette-swatch"
                      style={{ background: color }}
                    />
                    <b>{name}</b>
                    {values.palette === id && (
                      <Check size={20} aria-hidden="true" />
                    )}
                  </button>
                ))}
              </div>
            </>
          )}
          {tab === "region" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void save(values);
              }}
            >
              <h3>Tarih, saat ve bölge</h3>
              <label>
                Saat dilimi
                <input
                  list="netrix-timezones"
                  value={values.timezone}
                  onChange={(e) =>
                    setValues({ ...values, timezone: e.target.value })
                  }
                  required
                />
                <datalist id="netrix-timezones">
                  {[
                    "Europe/Istanbul",
                    "UTC",
                    "Europe/London",
                    "Europe/Berlin",
                    "America/New_York",
                    "Asia/Dubai",
                    "Asia/Tokyo",
                  ].map((v) => (
                    <option key={v} value={v} />
                  ))}
                </datalist>
              </label>
              <label>
                Bölgesel biçim
                <select
                  value={values.locale}
                  onChange={(e) =>
                    setValues({ ...values, locale: e.target.value })
                  }
                >
                  {[
                    ["tr-TR", "Türkçe · Türkiye"],
                    ["en-GB", "English · United Kingdom"],
                    ["en-US", "English · United States"],
                    ["de-DE", "Deutsch · Deutschland"],
                  ].map(([v, n]) => (
                    <option key={v} value={v}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Saat biçimi
                <select
                  value={String(values.hour12)}
                  onChange={(e) =>
                    setValues({ ...values, hour12: e.target.value === "true" })
                  }
                >
                  <option value="false">24 saat</option>
                  <option value="true">12 saat</option>
                </select>
              </label>
              <button className="primary" disabled={busy}>
                Tercihleri kaydet
              </button>
            </form>
          )}
          {tab === "features" && (
            <>
              <h3>Özellik ekle / çıkar</h3>
              <p className="muted">
                Kişisel araçlarınızı açıp kapatın. Erişim yetkileriniz bu
                tercihlerden etkilenmez.
              </p>
              <div className="feature-options">
                {[
                  [
                    "saved_commands",
                    "Hazır komutlar",
                    "Terminalde kişisel komut kitaplığını göster.",
                  ],
                  [
                    "session_dock",
                    "Oturum şeridi",
                    "SSH oturumlarını alta küçültmeyi etkinleştir.",
                  ],
                  [
                    "compact_tables",
                    "Sıkı tablo düzeni",
                    "Envanter satırlarında daha fazla kayıt göster.",
                  ],
                  [
                    "reduced_motion",
                    "Azaltılmış hareket",
                    "Arayüz geçişlerini ve animasyonları kapat.",
                  ],
                ].map(([id, name, desc]) => (
                  <label key={id}>
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={values.features.includes(id)}
                      onChange={(e) =>
                        void save({
                          ...values,
                          features: e.target.checked
                            ? [...values.features, id]
                            : values.features.filter((v) => v !== id),
                        })
                      }
                    />
                    <span>
                      <b>{name}</b>
                      <small>{desc}</small>
                    </span>
                  </label>
                ))}
              </div>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => void save({ ...defaultPreferences })}
              >
                Varsayılan tercihlere dön
              </button>
            </>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="success-note" role="status">
              {notice}
            </p>
          )}
        </section>
      </div>
    </Dialog>
  );
}

export function SSHSettings() {
  const [data, setData] = useState<Row>({
    username: "",
    port: 22,
    initial_command: "",
    connect_timeout: 10,
  });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    api("/access/ssh-profile")
      .then((v) => setData((d) => ({ ...d, ...v })))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    const { has_password, has_private_key, ...payload } = data;
    // Blank secret fields preserve the encrypted value; never repopulate secrets from the API.
    for (const key of ["password", "private_key", "passphrase"])
      if (!payload[key]) delete payload[key];
    try {
      const saved = await api("/access/ssh-profile", "PUT", payload);
      setData(saved);
      setNotice("Kişisel SSH bağlantınız kaydedildi.");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel access-settings">
      <div className="access-intro">
        <Key size={26} />
        <div>
          <h2>Kişisel SSH bağlantısı</h2>
          <p>
            Kendi cihaz hesabınızı tanımlayın. Envanterdeki bağlantı butonu bu
            bilgileri kullanır.
          </p>
        </div>
      </div>
      {loading ? (
        <p role="status">Bağlantı bilgileri yükleniyor…</p>
      ) : (
        <form onSubmit={submit}>
          <div className="form-grid">
            {[
              ["username", "Kullanıcı adı", "text"],
              ["port", "Port", "number"],
              ["password", "Şifre", "password"],
              ["connect_timeout", "Bağlantı zaman aşımı (saniye)", "number"],
            ].map(([key, label, type]) => (
              <label key={key}>
                {label}
                <input
                  type={type}
                  autoComplete={key === "password" ? "new-password" : "off"}
                  required={key === "username" || key === "port"}
                  min={
                    key === "port"
                      ? 1
                      : key === "connect_timeout"
                        ? 3
                        : undefined
                  }
                  max={
                    key === "port"
                      ? 65535
                      : key === "connect_timeout"
                        ? 30
                        : undefined
                  }
                  maxLength={key === "username" ? 120 : 4096}
                  value={data[key] ?? ""}
                  placeholder={
                    key === "password" && data.has_password
                      ? "Kayıtlı şifre korunur"
                      : ""
                  }
                  onChange={(e) =>
                    setData({
                      ...data,
                      [key]:
                        type === "number"
                          ? Number(e.target.value)
                          : e.target.value,
                    })
                  }
                />
              </label>
            ))}
            <label className="full">
              Bağlantıda ilk çalıştırılacak komut
              <textarea
                rows={3}
                maxLength={2000}
                value={data.initial_command || ""}
                onChange={(e) =>
                  setData({ ...data, initial_command: e.target.value })
                }
                placeholder="Örnek: terminal length 0"
              />
              <small>Her yeni SSH bağlantısında bir kez çalıştırılır.</small>
            </label>
          </div>
          <details className="ssh-key-settings">
            <summary>Özel anahtar ile bağlantı</summary>
            <label>
              Özel SSH anahtarı
              <textarea
                rows={4}
                autoComplete="off"
                spellCheck={false}
                maxLength={16384}
                value={data.private_key || ""}
                placeholder={
                  data.has_private_key
                    ? "Kayıtlı anahtar korunur"
                    : "PEM / OpenSSH özel anahtarı"
                }
                onChange={(e) =>
                  setData({ ...data, private_key: e.target.value })
                }
              />
            </label>
            <label>
              Anahtar parolası
              <input
                type="password"
                autoComplete="new-password"
                value={data.passphrase || ""}
                onChange={(e) =>
                  setData({ ...data, passphrase: e.target.value })
                }
              />
            </label>
          </details>
          <p className="muted">
            SSH bağlantısı rolünü yöneticiniz Ekip & yetkiler bölümünden atar.
            SSH host anahtarı, cihaz envanterindeki güven ayarına göre
            doğrulanır.
          </p>
          <div className="access-actions">
            <button className="primary" disabled={busy}>
              <Check size={18} />
              {busy ? "Kaydediliyor…" : "Bağlantıyı kaydet"}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await api("/access/ssh-profile", "DELETE");
                  setData({
                    username: "",
                    port: 22,
                    initial_command: "",
                    connect_timeout: 10,
                  });
                  setNotice("Kişisel SSH bilgileri kaldırıldı.");
                } catch (e: any) {
                  setError(e.message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Kayıtlı bağlantıyı kaldır
            </button>
          </div>
        </form>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}

type FilterRule = { field: string; op: string; value: string; join: string };
function GroupForm({
  group,
  onClose,
  onSaved,
}: {
  group: Row;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Row>({
    name: "",
    description: "",
    device_ids: [],
    ...group,
  });
  const [query, setQuery] = useState("");
  const [rules, setRules] = useState<FilterRule[]>([]);
  const [filterOpen, setFilterOpen] = useState(false);
  const [offset, setOffset] = useState(0);
  const deferred = useDeferredValue(query);
  const params = `q=${encodeURIComponent(deferred)}&filters=${encodeURIComponent(JSON.stringify(rules))}`;
  const devices = useLiveQuery(`/access/devices?${params}&offset=${offset}`);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const pageCheck = useRef<HTMLInputElement>(null);
  const items: Row[] = devices.data?.items || [];
  const selected = new Set<string>(values.device_ids);
  const checkedCount = items.filter((d) => selected.has(d.id)).length;
  useEffect(() => {
    if (pageCheck.current)
      pageCheck.current.indeterminate =
        checkedCount > 0 && checkedCount < items.length;
  }, [checkedCount, items.length]);
  const mergeSelection = (ids: string[], checked: boolean) =>
    setValues((v: Row) => ({
      ...v,
      device_ids: checked
        ? [...new Set([...v.device_ids, ...ids])]
        : v.device_ids.filter((id: string) => !ids.includes(id)),
    }));
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        "/access/groups" + (group.id ? "/" + group.id : ""),
        group.id ? "PUT" : "POST",
        {
          name: values.name,
          description: values.description,
          device_ids: values.device_ids,
        },
      );
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={group.id ? "Cihaz grubunu düzenle" : "Yeni cihaz grubu"}
      onClose={onClose}
      wide
    >
      <form className="access-group-form" onSubmit={submit}>
        <div className="form-grid">
          <label>
            Grup adı
            <input
              required
              maxLength={120}
              value={values.name}
              onChange={(e) => setValues({ ...values, name: e.target.value })}
            />
          </label>
          <label>
            Açıklama
            <input
              maxLength={400}
              value={values.description}
              onChange={(e) =>
                setValues({ ...values, description: e.target.value })
              }
            />
          </label>
        </div>
        <div className="group-picker-head">
          <h3>
            Cihazlar <small>· {values.device_ids.length} seçili</small>
          </h3>
          <button
            type="button"
            className="text-button"
            disabled={selecting}
            onClick={() => setValues({ ...values, device_ids: [] })}
          >
            Seçimi temizle
          </button>
        </div>
        <div className="group-search">
          <label>
            <span>Tüm alanlarda ara</span>
            <span className="search-input">
              <MagnifyingGlass size={18} />
              <input
                maxLength={120}
                value={query}
                placeholder="Cihaz adı, IP, model veya diğer alanlar"
                onChange={(e) => {
                  setQuery(e.target.value);
                  setOffset(0);
                }}
              />
            </span>
          </label>
          <button
            className="secondary"
            type="button"
            disabled={!devices.data?.columns}
            onClick={() => setFilterOpen(true)}
          >
            <Funnel size={18} />
            Filtreler{rules.length > 0 ? ` (${rules.length})` : ""}
          </button>
        </div>
        {rules.length > 0 && (
          <div className="group-filter-summary">
            <span>
              {rules.length} koşul etkin · {devices.data?.total ?? "…"} eşleşen
              cihaz
            </span>
            <button
              className="text-button"
              type="button"
              onClick={() => {
                setRules([]);
                setOffset(0);
              }}
            >
              Filtreleri temizle
            </button>
          </div>
        )}
        <div className="group-bulk-select">
          <label className="checkbox-label">
            <input
              ref={pageCheck}
              type="checkbox"
              checked={items.length > 0 && checkedCount === items.length}
              disabled={devices.loading || selecting || !items.length}
              onChange={(e) =>
                mergeSelection(
                  items.map((d) => d.id),
                  e.target.checked,
                )
              }
            />
            Bu sayfayı seç
          </label>
          <button
            type="button"
            className="secondary"
            disabled={
              devices.loading ||
              selecting ||
              deferred !== query ||
              !devices.data?.total
            }
            onClick={async () => {
              setSelecting(true);
              setError("");
              try {
                const result = await api(`/access/device-selection?${params}`);
                mergeSelection(result.ids, true);
              } catch (e: any) {
                setError(e.message);
              } finally {
                setSelecting(false);
              }
            }}
          >
            {selecting
              ? "Seçiliyor…"
              : `Tüm eşleşenleri seç (${devices.data?.total ?? 0})`}
          </button>
        </div>
        {devices.error && (
          <p className="error" role="alert">
            {devices.error}
          </p>
        )}
        <div
          className="group-device-list"
          aria-label="Gruba eklenecek cihazlar"
          aria-busy={devices.loading}
        >
          {devices.loading && <p role="status">Cihazlar yükleniyor…</p>}
          {!devices.loading && !items.length && (
            <p>Filtreye uygun cihaz bulunamadı.</p>
          )}
          {items.map((device) => (
            <label key={device.id}>
              <input
                type="checkbox"
                disabled={devices.loading || selecting}
                checked={selected.has(device.id)}
                onChange={(e) => mergeSelection([device.id], e.target.checked)}
              />
              <span>
                <b>{device.name}</b>
                <small className="mono">{device.management_ip}</small>
                <small>
                  {[device.vendor, device.model, device.site_name]
                    .filter(Boolean)
                    .join(" · ")}
                </small>
              </span>
              <small>{tag(device.kind)}</small>
            </label>
          ))}
        </div>
        <div className="access-actions group-pagination">
          <button
            type="button"
            className="secondary"
            disabled={!offset || devices.loading}
            onClick={() => setOffset(Math.max(0, offset - 100))}
          >
            Önceki
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!devices.data?.has_more || devices.loading}
            onClick={() => setOffset(offset + 100)}
          >
            Sonraki
          </button>
          <span className="muted">
            {devices.data?.total ?? 0} cihaz · Arama ve sayfa değişince seçimler
            korunur.
          </span>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Vazgeç
          </button>
          <button className="primary" disabled={busy || selecting}>
            Grubu kaydet
          </button>
        </div>
      </form>
      {filterOpen && (
        <Filters
          columns={devices.data?.columns || []}
          rules={
            rules.length
              ? rules
              : [{ field: "model", op: "eq", value: "", join: "and" }]
          }
          valueSuggestions
          wide
          onSave={(next) => {
            setRules(next);
            setOffset(0);
          }}
          onClose={() => setFilterOpen(false)}
        />
      )}
    </Dialog>
  );
}

export function AccessGroups({ user }: { user: Row }) {
  const [refresh, setRefresh] = useState(0);
  const groups = useLiveQuery("/access/groups", refresh);
  const [editing, setEditing] = useState<Row | null>(null);
  const [deleting, setDeleting] = useState<Row | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  return (
    <section className="panel access-settings">
      <div className="access-intro">
        <ShieldCheck size={26} />
        <div>
          <h2>Cihaz grupları</h2>
          <p>Envanter cihazlarını kişisel gruplarınızda düzenleyin.</p>
        </div>
        <button className="primary" onClick={() => setEditing({})}>
          <Plus size={18} />
          Grup oluştur
        </button>
      </div>
      <label className="access-group-search">
        Grup ara
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Grup adı"
        />
      </label>
      {groups.loading && <p role="status">Gruplar yükleniyor…</p>}
      {(groups.error || error) && (
        <p role="alert" className="error">
          {groups.error || error}
        </p>
      )}
      <div className="access-group-cards">
        {groups.data?.items
          .filter((g: Row) =>
            g.name
              .toLocaleLowerCase("tr")
              .includes(query.toLocaleLowerCase("tr")),
          )
          .map((g: Row) => (
            <article key={g.id}>
              <div>
                <h3>{g.name}</h3>
                <p>{g.description || "Açıklama eklenmedi"}</p>
                <small>{g.device_ids.length} cihaz</small>
              </div>
              <div className="access-actions">
                <button
                  className="icon-button"
                  aria-label={`${g.name} düzenle`}
                  onClick={() => setEditing(g)}
                >
                  <PencilSimple size={18} />
                </button>
                <button
                  className="icon-button"
                  aria-label={`${g.name} sil`}
                  onClick={() => setDeleting(g)}
                >
                  <Trash size={18} />
                </button>
              </div>
            </article>
          ))}
      </div>
      {!groups.loading && !groups.data?.items.length && (
        <div className="access-empty">
          <Key size={28} />
          <h3>Henüz cihaz grubu yok</h3>
          <p>İlk grubunuzu oluşturun ve cihazları filtreleyerek ekleyin.</p>
        </div>
      )}
      {editing && (
        <GroupForm
          group={editing}
          onClose={() => setEditing(null)}
          onSaved={() => setRefresh((v) => v + 1)}
        />
      )}
      {deleting && (
        <Dialog title="Cihaz grubunu sil" onClose={() => setDeleting(null)}>
          <p>{deleting.name} kişisel grubu kaldırılacak.</p>
          <div className="dialog-actions">
            <button className="secondary" onClick={() => setDeleting(null)}>
              Vazgeç
            </button>
            <button
              className="primary"
              onClick={async () => {
                try {
                  await api("/access/groups/" + deleting.id, "DELETE");
                  setRefresh((v) => v + 1);
                  setDeleting(null);
                } catch (e: any) {
                  setError(e.message);
                  setDeleting(null);
                }
              }}
            >
              Grubu sil
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
