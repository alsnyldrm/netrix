import { useState, useRef, useEffect, type FormEvent } from "react";
import { api, Dialog, resourceChoices } from "./main";
import "./discovery-scope-form.css";

type Row = Record<string, any>;

export function DiscoveryScopeForm({
  row,
  refs,
  onClose,
  onSaved,
}: {
  row?: Row;
  refs: Record<string, Row[]>;
  onClose: () => void;
  onSaved: (saved: Row) => void;
}) {
  const [values, setValues] = useState(() => ({
    name: row?.name || "",
    cidr: row?.cidr || "",
    vrf_id: row?.vrf_id || refs.vrfs?.[0]?.id || "",
    institution_id:
      row?.institution_id ||
      refs.sites?.find((site) => site.id === row?.site_id)?.institution_id ||
      "",
    site_id: row?.site_id || "",
    credential_ids: (row?.credential_ids ||
      (row?.credential_id ? [row.credential_id] : [])) as string[],
    exclusions: (row?.exclusions || []).join("\n"),
    seeds: (row?.seeds || []).join("\n"),
    enabled: row?.enabled ?? true,
    interval_seconds: row?.interval_seconds ?? 0,
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const errorBox = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (error) errorBox.current?.focus();
  }, [error]);
  const profiles = (refs.credentials || []).filter((profile) =>
    ["snmpv3", "snmpv2c"].includes(profile.protocol),
  );
  const sites = resourceChoices(
    { key: "site_id", label: "Lokasyon", ref: "sites" },
    refs,
    values,
    "discovery",
  );
  const set = (key: string, value: unknown) => {
    if (key === "credential_ids") setError("");
    setValues((current) => ({ ...current, [key]: value }));
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!values.credential_ids.length) {
      setError("En az bir SNMP erişim profili seçin.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const saved = await api(
        "/scopes" + (row?.id ? "/" + row.id : ""),
        row?.id ? "PUT" : "POST",
        {
          ...values,
          site_id: values.site_id || null,
          interval_seconds: Number(values.interval_seconds),
          exclusions: values.exclusions
            .split(/[\n,]+/)
            .map((v: string) => v.trim())
            .filter(Boolean),
          seeds: values.seeds
            .split(/[\n,]+/)
            .map((v: string) => v.trim())
            .filter(Boolean),
        },
      );
      onSaved(saved);
      onClose();
    } catch (error: any) {
      setError(error.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={(row?.id ? "Kaydı düzenle" : "Yeni kayıt") + " · Ağ keşfi"}
      onClose={onClose}
    >
      <form
        onSubmit={submit}
        className="discovery-scope-form"
        autoComplete="off"
      >
        <div className="form-grid">
          <label className="form-field">
            <span className="field-title">
              Ad <span className="required">*</span>
            </span>
            <input
              required
              maxLength={120}
              name="name"
              value={values.name}
              onChange={(e) => set("name", e.target.value)}
            />
          </label>
          <label className="form-field">
            <span className="field-title">
              Ağ (CIDR) <span className="required">*</span>
            </span>
            <input
              required
              placeholder="192.0.2.0/24"
              spellCheck={false}
              name="cidr"
              value={values.cidr}
              onChange={(e) => set("cidr", e.target.value)}
            />
          </label>
          <label className="form-field">
            <span className="field-title">
              Kurum <span className="required">*</span>
            </span>
            <select
              required
              name="institution_id"
              value={values.institution_id}
              onChange={(e) =>
                setValues((current) => ({
                  ...current,
                  institution_id: e.target.value,
                  site_id: "",
                }))
              }
            >
              <option value="">Kurum seçin</option>
              {(refs.institutions || []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            {!refs.institutions?.length && (
              <small>
                Önce IP Adres Yönetimi → Lokasyonlar bölümünden kurum ekleyin.
              </small>
            )}
          </label>
          <label className="form-field">
            <span className="field-title">Lokasyon</span>
            <select
              disabled={!values.institution_id}
              name="site_id"
              value={values.site_id}
              onChange={(e) => set("site_id", e.target.value)}
            >
              <option value="">
                {values.institution_id
                  ? "Lokasyon seçin (isteğe bağlı)"
                  : "Önce kurum seçin"}
              </option>
              {sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.name}
                </option>
              ))}
            </select>
            {values.institution_id && !sites.length && (
              <small>Bu kuruma ait lokasyon bulunmuyor.</small>
            )}
          </label>
          <label className="form-field">
            <span className="field-title">
              VRF <span className="required">*</span>
            </span>
            <select
              required
              name="vrf_id"
              value={values.vrf_id}
              onChange={(e) => set("vrf_id", e.target.value)}
            >
              <option value="">VRF seçin</option>
              {(refs.vrfs || []).map((vrf) => (
                <option key={vrf.id} value={vrf.id}>
                  {vrf.name}
                </option>
              ))}
            </select>
          </label>
          <label className="form-field">
            <span className="field-title">Tarama aralığı (saniye)</span>
            <input
              type="number"
              min={0}
              step={1}
              name="interval_seconds"
              value={values.interval_seconds}
              onChange={(e) => set("interval_seconds", e.target.value)}
            />
            <small>
              0: yalnızca elle başlatılır. Otomatik tarama: en az 300 saniye.
            </small>
          </label>
        </div>
        <fieldset
          className="discovery-profiles"
          aria-describedby="discovery-profile-hint"
        >
          <legend>
            SNMP erişim profilleri <span className="required">*</span>
          </legend>
          <p id="discovery-profile-hint">
            Birden fazla profil seçebilirsiniz. Profiller seçim sırasıyla
            denenir; yanıt veren profil kullanılır.
          </p>
          <div className="discovery-profile-list">
            {profiles.map((profile) => {
              const index = values.credential_ids.indexOf(profile.id);
              return (
                <label key={profile.id} className="discovery-profile-option">
                  <input
                    type="checkbox"
                    checked={index >= 0}
                    disabled={index < 0 && values.credential_ids.length >= 16}
                    onChange={(e) =>
                      set(
                        "credential_ids",
                        e.target.checked
                          ? [...values.credential_ids, profile.id]
                          : values.credential_ids.filter(
                              (id) => id !== profile.id,
                            ),
                      )
                    }
                  />
                  <span>
                    <b>{profile.name}</b>
                    <small>
                      {profile.protocol === "snmpv3" ? "SNMPv3" : "SNMPv2c"}
                    </small>
                  </span>
                  {index >= 0 && (
                    <span
                      className="discovery-profile-order"
                      aria-label={`${index + 1}. sırada`}
                    >
                      {index + 1}
                    </span>
                  )}
                </label>
              );
            })}
            {!profiles.length && (
              <p>
                SNMP profili bulunmuyor. Erişim profilleri bölümünden SNMPv3
                veya SNMPv2c profili ekleyin.
              </p>
            )}
          </div>
          <small aria-live="polite">
            {values.credential_ids.length} profil seçildi · En fazla 16
          </small>
        </fieldset>
        <div className="form-grid">
          <label className="form-field">
            <span className="field-title">Hariç tutulan ağlar</span>
            <textarea
              rows={3}
              spellCheck={false}
              name="exclusions"
              value={values.exclusions}
              onChange={(e) => set("exclusions", e.target.value)}
            />
            <small>Her satıra bir IP veya CIDR yazın.</small>
          </label>
          <label className="form-field">
            <span className="field-title">Hedef IP adresleri</span>
            <textarea
              rows={3}
              spellCheck={false}
              name="seeds"
              value={values.seeds}
              onChange={(e) => set("seeds", e.target.value)}
            />
            <small>
              IPv4 için isteğe bağlıdır; boşsa ağın tamamı taranır. IPv6 için
              zorunludur. Her satıra bir IP yazın.
            </small>
          </label>
          <label className="form-field full">
            <span className="field-title">Keşif kapsamı</span>
            <span className="checkbox-control">
              <input
                type="checkbox"
                checked={values.enabled}
                onChange={(e) => set("enabled", e.target.checked)}
              />
              <span>{values.enabled ? "Etkin" : "Kapalı"}</span>
            </span>
          </label>
        </div>
        {error && (
          <p className="error" role="alert" tabIndex={-1} ref={errorBox}>
            {error}
          </p>
        )}
        <div className="dialog-footer">
          <button type="button" className="secondary" onClick={onClose}>
            Vazgeç
          </button>
          <button
            type="submit"
            className="primary"
            disabled={busy || !profiles.length}
          >
            {busy ? "Kaydediliyor…" : "Kaydet"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
