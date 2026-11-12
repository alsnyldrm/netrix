import React, {
  useDeferredValue,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  Check,
  ArrowRight,
  SquaresFour,
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
  TextAa,
  Sun,
  Moon,
  Monitor,
} from "@phosphor-icons/react";
import { Filters } from "./inventory";
import { api, useLiveQuery } from "./data";
import { Dialog, tag } from "./main";
import {
  applyPreferences,
  currentPreferences,
  defaultPreferences,
} from "./preferences";
import type { Preferences, ThemePreference } from "./preferences";
import "./user-workspace.css";
import { colorPalettes } from "./appearance";
import { canSSH } from "./permissions";
import { applicationFonts } from "./application-fonts";
import type { ApplicationFont } from "./application-fonts";
import { AvatarEditor } from "./profile-avatar";
import type { AccountAvatar } from "./profile-avatar";
type Row = Record<string, any>;
export function Profile({
  avatar,
  user,
  themePreference,
  onThemeChange,
  onClose,
  onChanged,
  onPasswordChanged,
}: {
  avatar: AccountAvatar;
  user: Row;
  themePreference: ThemePreference;
  onThemeChange?: (mode: ThemePreference, origin?: HTMLElement) => void;
  onClose: () => void;
  onChanged: () => void;
  onPasswordChanged: () => void;
}) {
  const [tab, setTab] = useState("account");
  const content = useRef<HTMLElement>(null);
  const previousTab = useRef(tab);
  useLayoutEffect(() => {
    const panel = content.current;
    panel?.scrollTo(0, 0);
    if (
      previousTab.current === tab ||
      document.documentElement.dataset.reduceMotion === "true" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      previousTab.current = tab;
      return;
    }
    previousTab.current = tab;
    const transition = panel?.animate(
      [
        { opacity: 0, transform: "translateX(16px)" },
        { opacity: 1, transform: "none" },
      ],
      { duration: 360, easing: "cubic-bezier(0.19, 1, 0.22, 1)" },
    );
    return () => transition?.cancel();
  }, [tab]);
  const sshAllowed = canSSH(user);
  useEffect(() => {
    if (!sshAllowed && ["ssh", "device-groups"].includes(tab))
      setTab("account");
  }, [sshAllowed, tab]);
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
    ["design", "Tema", SquaresFour],
    ["palette", "Renk paleti", Palette],
    ["font", "Yazı tipi", TextAa],
    ["region", "Tarih, saat ve bölge", Clock],
    ["features", "Özellikler", SlidersHorizontal],
    ["ssh", "SSH Bağlantısı", Key],
    ["device-groups", "Cihaz grupları", ShieldCheck],
  ] as const;
  return (
    <Dialog title="Profil" onClose={onClose} wide className="profile-dialog">
      <div className="profile-layout">
        <nav className="profile-menu" aria-label="Profil bölümleri">
          {tabs
            .filter(
              ([id]) => sshAllowed || !["ssh", "device-groups"].includes(id),
            )
            .map(([id, name, Icon]) => (
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
        <section className="profile-content" ref={content}>
          {tab === "ssh" && sshAllowed && <SSHSettings />}
          {tab === "device-groups" && sshAllowed && (
            <AccessGroups user={user} />
          )}
          {tab === "account" && (
            <>
              <span className="eyebrow">Kişisel çalışma alanı</span>
              <h3>{user.display_name}</h3>
              <AvatarEditor name={user.display_name} avatar={avatar} />
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
              <PasswordChange onChanged={onPasswordChanged} />
            </>
          )}
          {tab === "design" && (
            <>
              <h3>Görünüm</h3>
              <p className="muted">
                {onThemeChange
                  ? "Bu tarayıcıda kullanacağınız görünümü seçin."
                  : "Karanlık paleti koyu görünümü kullanır. Açık görünüm için renk paletini değiştirin."}
              </p>
              <div className="lumelle-mode-options">
                {(
                  [
                    ["light", "Açık", Sun],
                    ["dark", "Koyu", Moon],
                    ["system", "Sistemle eşleş", Monitor],
                  ] as const
                ).map(([mode, label, Icon]) => (
                  <button
                    key={mode}
                    type="button"
                    className="lumelle-mode-card"
                    disabled={!onThemeChange}
                    aria-pressed={
                      (onThemeChange ? themePreference : "dark") === mode
                    }
                    onClick={(event) =>
                      onThemeChange?.(mode, event.currentTarget)
                    }
                  >
                    <span
                      className={`lumelle-mode-preview preview-${mode}`}
                      aria-hidden="true"
                    >
                      <i />
                      <i />
                      <i />
                    </span>
                    <span>
                      <Icon size={16} aria-hidden="true" /> {label}
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
          {tab === "palette" && (
            <>
              <h3>Çalışma alanınızın renkleri</h3>
              <p className="muted">
                Seçtiğiniz palet arka planı, menüleri, panelleri, tabloları ve
                butonları birlikte renklendirir. Durum ve hata renkleri anlamını
                korur. Karanlık paleti her zaman koyu görünümde çalışır.
              </p>
              <div className="palette-grid">
                {colorPalettes.map((p) => (
                  <button
                    disabled={busy}
                    key={p.id}
                    className="palette-option"
                    aria-pressed={values.palette === p.id}
                    onClick={() => void save({ ...values, palette: p.id })}
                  >
                    <span
                      className="palette-swatch"
                      aria-hidden="true"
                      style={{
                        background:
                          "tones" in p
                            ? p.tones[3]
                            : `hsl(${p.hue} ${p.saturation}% 59%)`,
                      }}
                    >
                      {values.palette === p.id && (
                        <Check size={18} weight="bold" />
                      )}
                    </span>
                    <b>{p.name}</b>
                  </button>
                ))}
              </div>
            </>
          )}
          {tab === "font" && (
            <>
              <h3>Uygulama yazı tipi</h3>
              <p className="muted" id="application-font-help">
                Menüler, başlıklar, tablolar ve formlar için 15 kurumsal yazı
                tipinden birini seçin. Seçiminiz hesabınıza kaydedilir ve tüm
                temalarda uygulanır.
              </p>
              <label className="application-font-picker">
                Yazı tipi
                <select
                  name="ui-font"
                  value={values.ui_font}
                  disabled={busy}
                  aria-describedby="application-font-help"
                  onChange={(e) =>
                    void save({
                      ...values,
                      ui_font: e.target.value as ApplicationFont,
                    })
                  }
                >
                  <option value="theme">Tema varsayılanı</option>
                  {applicationFonts.map((font) => (
                    <option key={font.id} value={font.id}>
                      {font.name}
                    </option>
                  ))}
                </select>
              </label>
              <section
                className="application-font-preview"
                aria-label="Yazı tipi önizlemesi"
              >
                <span className="eyebrow">
                  {applicationFonts.find((font) => font.id === values.ui_font)
                    ?.name || "Tema varsayılanı"}
                </span>
                <h4>Ağınızın tamamı, tek çalışma alanı.</h4>
                <p>
                  Cihaz envanteri, bağlantılar ve ağ yönetimi. Çç Ğğ Iı İi Öö Şş
                  Üü.
                </p>
                <dl className="application-font-samples">
                  <div>
                    <dt>Envanter</dt>
                    <dd>Cihaz yönetimi</dd>
                  </div>
                  <div>
                    <dt>Durum</dt>
                    <dd>Bağlantı etkin</dd>
                  </div>
                  <div>
                    <dt>Rakamlar</dt>
                    <dd>0123456789</dd>
                  </div>
                </dl>
              </section>
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
                ]
                  .filter(
                    ([id]) =>
                      sshAllowed ||
                      !["saved_commands", "session_dock"].includes(id),
                  )
                  .map(([id, name, desc]) => (
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

function SSHConnectionForm({
  profile,
  onClose,
  onSaved,
}: {
  profile: Row;
  onClose: () => void;
  onSaved: (profile: Row) => void;
}) {
  const [data, setData] = useState<Row>({
    name: "",
    username: "",
    port: 22,
    initial_command: "",
    connect_timeout: 10,
    idle_timeout_minutes: 15,
    group_ids: [],
    ...profile,
  });
  const groups = useLiveQuery("/access/groups");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    const { id, has_password, has_private_key, ...payload } = data;
    for (const key of ["password", "private_key", "passphrase"])
      if (!payload[key]) delete payload[key];
    try {
      const saved = await api(
        "/access/ssh-profiles" + (profile.id ? "/" + profile.id : ""),
        profile.id ? "PUT" : "POST",
        payload,
      );
      onSaved(saved);
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={profile.id ? "SSH bağlantısını düzenle" : "Yeni SSH bağlantısı"}
      wide
      onClose={onClose}
    >
      <form className="ssh-profile-form" onSubmit={submit}>
        <label>
          Bağlantı adı
          <input
            required
            maxLength={120}
            value={data.name}
            placeholder="Örnek: Merkez switch hesabı"
            onChange={(e) => setData({ ...data, name: e.target.value })}
          />
        </label>
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
                  key === "port" ? 1 : key === "connect_timeout" ? 3 : undefined
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
            Hareketsizlik süresi (dakika)
            <input
              type="number"
              min={1}
              max={240}
              required
              value={data.idle_timeout_minutes}
              onChange={(e) =>
                setData({
                  ...data,
                  idle_timeout_minutes: Number(e.target.value),
                })
              }
              aria-describedby="ssh-idle-timeout-hint"
            />
            <small id="ssh-idle-timeout-hint">
              1–240 dakika. Terminale giriş yapılmazsa exit gönderilir ve
              bağlantı kapatılır. Bu ayar yeni açılan oturumlarda uygulanır.
            </small>
          </label>
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
              onChange={(e) => setData({ ...data, passphrase: e.target.value })}
            />
          </label>
        </details>

        <fieldset className="ssh-profile-groups">
          <legend>Cihaz grupları</legend>
          <p className="muted">
            Bu bağlantının kullanacağı grupları seçin. Her gruba tek bir SSH
            bağlantısı atanabilir.
          </p>
          <label>
            Grup ara
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Grup adıyla ara"
            />
          </label>
          {groups.loading && <p role="status">Gruplar yükleniyor…</p>}
          {groups.error && (
            <p className="error" role="alert">
              {groups.error}
            </p>
          )}
          <div className="ssh-group-options">
            {groups.data?.items
              .filter((g: Row) =>
                g.name
                  .toLocaleLowerCase("tr")
                  .includes(query.toLocaleLowerCase("tr")),
              )
              .map((g: Row) => {
                const occupied = Boolean(
                  g.ssh_profile_id && g.ssh_profile_id !== profile.id,
                );
                return (
                  <label key={g.id}>
                    <input
                      type="checkbox"
                      disabled={occupied || busy}
                      checked={data.group_ids.includes(g.id)}
                      onChange={(e) =>
                        setData({
                          ...data,
                          group_ids: e.target.checked
                            ? [...data.group_ids, g.id]
                            : data.group_ids.filter(
                                (id: string) => id !== g.id,
                              ),
                        })
                      }
                    />
                    <span>
                      <b>{g.name}</b>
                      <small>
                        {g.device_ids.length} cihaz
                        {occupied ? " · Başka bağlantıya atanmış" : ""}
                      </small>
                    </span>
                  </label>
                );
              })}
          </div>
          {!groups.loading && !groups.data?.items.length && (
            <p>
              Önce Profil → Cihaz yetkisi → Cihaz grupları bölümünden grup
              oluşturun. Bağlantıyı şimdi kaydedip grupları daha sonra
              atayabilirsiniz.
            </p>
          )}
        </fieldset>
        <p className="muted">
          SSH bağlantısı rolünü süper yönetici Ekip & yetkiler bölümünden atar.
          Cihazın grubuna atanmış bağlantı otomatik kullanılır.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Vazgeç
          </button>
          <button className="primary" disabled={busy || groups.loading}>
            <Check size={18} />
            {busy ? "Kaydediliyor…" : "Bağlantıyı kaydet"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function SSHSettings() {
  const [refresh, setRefresh] = useState(0);
  const profiles = useLiveQuery("/access/ssh-profiles", refresh);
  const groups = useLiveQuery("/access/groups", refresh);
  const [savedProfile, setSavedProfile] = useState<{
    row: Row;
    source: unknown;
  } | null>(null);
  const [editing, setEditing] = useState<Row | null>(null);
  const [deleting, setDeleting] = useState<Row | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  return (
    <section className="panel access-settings">
      <div className="access-intro">
        <Key size={26} />
        <div>
          <h2>SSH bağlantıları</h2>
          <p>
            Farklı cihaz hesapları oluşturun ve her birine cihaz grupları
            atayın.
          </p>
        </div>
        <button className="primary" onClick={() => setEditing({})}>
          <Plus size={18} />
          Bağlantı ekle
        </button>
      </div>
      <label className="access-group-search">
        Bağlantı ara
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Bağlantı adı veya kullanıcı adı"
        />
      </label>
      {profiles.loading && <p role="status">Bağlantılar yükleniyor…</p>}
      {(profiles.error || error) && (
        <p className="error" role="alert">
          {profiles.error || error}
        </p>
      )}
      <div className="ssh-profile-cards">
        {profiles.data?.items
          // Keep the saved values if the editor reopens before the list read settles.
          // A fresh query result automatically supersedes this temporary response.
          .map((p: Row) =>
            savedProfile &&
            savedProfile.source === profiles.data &&
            savedProfile.row.id === p.id
              ? savedProfile.row
              : p,
          )
          .filter((p: Row) =>
            `${p.name} ${p.username}`
              .toLocaleLowerCase("tr")
              .includes(query.toLocaleLowerCase("tr")),
          )
          .map((p: Row) => (
            <article key={p.id}>
              <div>
                <h3>{p.name}</h3>
                <p className="mono">
                  {p.username} · Port {p.port}
                </p>
                <div className="ssh-assigned-groups">
                  {p.group_ids.length ? (
                    p.group_ids.map((id: string) => (
                      <span key={id}>
                        {groups.data?.items.find((g: Row) => g.id === id)
                          ?.name || "Cihaz grubu"}
                      </span>
                    ))
                  ) : (
                    <small>Grup atanmamış · Bağlantıda kullanılmaz</small>
                  )}
                </div>
              </div>
              <div className="access-actions">
                <button
                  className="icon-button"
                  aria-label={`${p.name} düzenle`}
                  onClick={() => setEditing(p)}
                >
                  <PencilSimple size={18} />
                </button>
                <button
                  className="icon-button"
                  aria-label={`${p.name} sil`}
                  onClick={() => setDeleting(p)}
                >
                  <Trash size={18} />
                </button>
              </div>
            </article>
          ))}
      </div>
      {!profiles.loading && !profiles.data?.items.length && (
        <div className="access-empty">
          <Key size={28} />
          <h3>Henüz SSH bağlantısı yok</h3>
          <p>
            İlk bağlantınızı ekleyin; farklı kullanıcı adları, portlar ve
            komutlarla yeni bağlantılar oluşturabilirsiniz.
          </p>
        </div>
      )}
      {editing && (
        <SSHConnectionForm
          profile={editing}
          onClose={() => setEditing(null)}
          onSaved={(row) => {
            setSavedProfile({ row, source: profiles.data });
            setRefresh((n) => n + 1);
          }}
        />
      )}
      {deleting && (
        <Dialog title="SSH bağlantısını sil" onClose={() => setDeleting(null)}>
          <p>
            {deleting.name} kaldırılacak. Atanmış gruplar korunur; yeni bir SSH
            bağlantısı atanıncaya kadar bu gruplardaki cihazlara bağlanılamaz.
          </p>
          <div className="dialog-actions">
            <button className="secondary" onClick={() => setDeleting(null)}>
              Vazgeç
            </button>
            <button
              className="primary"
              onClick={async () => {
                try {
                  await api(`/access/ssh-profiles/${deleting.id}`, "DELETE");
                  setRefresh((n) => n + 1);
                  setDeleting(null);
                } catch (e: any) {
                  setError(e.message);
                  setDeleting(null);
                }
              }}
            >
              Bağlantıyı sil
            </button>
          </div>
        </Dialog>
      )}
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
  const [selectionNotice, setSelectionNotice] = useState("");
  const pageCheck = useRef<HTMLInputElement>(null);
  const items: Row[] = devices.data?.items || [];
  const selected = new Set<string>(values.device_ids);
  const available = items.filter(
    (d) => !d.access_group_id || d.access_group_id === group.id,
  );
  const checkedCount = available.filter((d) => selected.has(d.id)).length;
  useEffect(() => {
    if (pageCheck.current)
      pageCheck.current.indeterminate =
        checkedCount > 0 && checkedCount < available.length;
  }, [checkedCount, available.length]);
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
              checked={
                available.length > 0 && checkedCount === available.length
              }
              disabled={devices.loading || selecting || !available.length}
              onChange={(e) =>
                mergeSelection(
                  available.map((d) => d.id),
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
                const result = await api(
                  `/access/device-selection?${params}&group_id=${encodeURIComponent(group.id || "")}`,
                );
                setSelectionNotice(
                  result.skipped
                    ? `${result.skipped} cihaz başka gruplarda olduğu için seçilmedi.`
                    : "",
                );
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
        <p className="muted">
          Bir cihaz kendi gruplarınızdan yalnız birinde bulunabilir. Başka
          gruptaki cihazlar seçilemez.
        </p>
        {selectionNotice && <p role="status">{selectionNotice}</p>}
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
                disabled={
                  devices.loading ||
                  selecting ||
                  Boolean(
                    device.access_group_id &&
                    device.access_group_id !== group.id,
                  )
                }
                checked={selected.has(device.id)}
                onChange={(e) => mergeSelection([device.id], e.target.checked)}
              />
              <span>
                <b>{device.name}</b>
                {device.access_group_id &&
                  device.access_group_id !== group.id && (
                    <small>Grubu: {device.access_group_name}</small>
                  )}
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

function PasswordChange({ onChanged }: { onChanged: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="profile-password"
      aria-labelledby="profile-password-title"
      aria-busy={busy}
      onSubmit={async (e) => {
        e.preventDefault();
        if (busy) return;
        setBusy(true);
        setError("");
        try {
          await api("/auth/password", "POST", {
            current_password: current,
            new_password: next,
          });
          setCurrent("");
          setNext("");
          onChanged();
        } catch (e: any) {
          setError(e.message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <h3 id="profile-password-title">Parolanızı değiştirin</h3>
      <label>
        Mevcut parola
        <input
          type="password"
          name="current_password"
          autoComplete="current-password"
          required
          maxLength={200}
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </label>
      <label>
        Yeni parola
        <input
          type="password"
          name="new_password"
          autoComplete="new-password"
          required
          minLength={12}
          maxLength={200}
          aria-describedby="profile-password-help"
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
      </label>
      <small id="profile-password-help" className="muted">
        En az 12 karakter. Değişiklikten sonra bütün oturumlar kapanır.
      </small>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <button className="primary" disabled={busy}>
        {busy ? "Güncelleniyor…" : "Parolayı güncelle"}
        <ArrowRight size={17} aria-hidden="true" />
      </button>
    </form>
  );
}
