import { useEffect, useState } from "react";
import { DownloadSimple, FloppyDisk, ShieldCheck } from "@phosphor-icons/react";
import { api } from "./data";
import "./saml-settings.css";

type Settings = {
  enabled: boolean;
  sp_entity_id: string;
  sp_acs_url: string;
  sp_metadata_url: string;
  sp_login_url: string;
  idp_metadata_url: string;
  idp_entity_id: string;
  sso_url: string;
  slo_url: string;
  x509_certificate: string;
  email_attribute: string;
  display_name_attribute: string;
  nameid_mapping: string;
  role_mapping: Record<string, string>;
};

export function SamlSettings() {
  const [values, setValues] = useState<Settings | null>(null);
  const [mapping, setMapping] = useState("{}");
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState("");
  const [importNotice, setImportNotice] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    api("/saml/settings")
      .then((result: Settings) => {
        if (!active) return;
        setValues(result);
        setMapping(JSON.stringify(result.role_mapping, null, 2));
      })
      .catch((e: Error) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  if (!values)
    return error ? (
      <div className="error" role="alert">
        {error}
      </div>
    ) : (
      <p role="status">SAML ayarları yükleniyor…</p>
    );

  const change = (key: keyof Settings, value: string | boolean) => {
    setValues({ ...values, [key]: value });
    setNotice("");
  };
  const pullMetadata = async () => {
    if (saving || importing || !values.idp_metadata_url.trim()) return;
    setImporting(true);
    setImportError("");
    setImportNotice("");
    setNotice("");
    try {
      const result: Pick<
        Settings,
        | "idp_metadata_url"
        | "idp_entity_id"
        | "sso_url"
        | "slo_url"
        | "x509_certificate"
      > = await api("/saml/metadata/import", "POST", {
        url: values.idp_metadata_url,
      });
      setValues((current) => current && { ...current, ...result });
      setImportNotice(
        "Metadata forma aktarıldı. Alanları kontrol edip SAML ayarlarını kaydedin.",
      );
    } catch (e) {
      setImportError(e instanceof Error ? e.message : "Metadata aktarılamadı.");
    } finally {
      setImporting(false);
    }
  };
  const field = (
    key: Exclude<keyof Settings, "enabled" | "role_mapping">,
    title: string,
    options: {
      full?: boolean;
      readOnly?: boolean;
      placeholder?: string;
      type?: "url" | "text";
    } = {},
  ) => (
    <label className={options.full ? "saml-full" : undefined}>
      <span>{title}</span>
      <input
        name={key}
        type={options.type ?? "text"}
        value={values[key]}
        readOnly={options.readOnly}
        placeholder={options.placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(e) => change(key, e.target.value)}
      />
    </label>
  );

  return (
    <section className="panel saml-panel" aria-labelledby="saml-panel-title">
      <div className="saml-panel-header">
        <div className="saml-title">
          <ShieldCheck size={21} aria-hidden="true" />
          <h2 id="saml-panel-title">SAML / Microsoft Entra ID</h2>
        </div>
        <span className="saml-role-pill">Varsayılan rol: Salt okunur</span>
      </div>
      <form
        className="saml-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (importing || saving) return;
          setError("");
          setNotice("");
          let role_mapping: Settings["role_mapping"];
          try {
            role_mapping = JSON.parse(mapping);
            if (
              !role_mapping ||
              Array.isArray(role_mapping) ||
              typeof role_mapping !== "object"
            )
              throw new Error();
          } catch {
            setError(
              "Rol eşlemesi geçerli bir JSON nesnesi olmalıdır. Boş eşleme için {} kullanın.",
            );
            e.currentTarget
              .querySelector<HTMLTextAreaElement>('[name="role_mapping"]')
              ?.focus();
            return;
          }
          setSaving(true);
          try {
            const { sp_acs_url, sp_metadata_url, sp_login_url, ...config } =
              values;
            const result: Settings = await api("/saml/settings", "PUT", {
              ...config,
              role_mapping,
            });
            setValues(result);
            setMapping(JSON.stringify(result.role_mapping, null, 2));
            setNotice("SAML ayarları kaydedildi.");
            setImportNotice("");
            setImportError("");
          } catch (e: any) {
            setError(e.message);
          } finally {
            setSaving(false);
          }
        }}
      >
        <fieldset disabled={saving || importing}>
          <label className="saml-checkbox">
            <input
              type="checkbox"
              name="enabled"
              checked={values.enabled}
              onChange={(e) => change("enabled", e.target.checked)}
            />
            SAML ile girişi etkinleştir
          </label>
          <div className="saml-fields">
            {field("sp_entity_id", "SP Entity ID")}
            {field("sp_acs_url", "SP ACS URL", { readOnly: true })}
            {field("sp_metadata_url", "SP Metadata URL", {
              readOnly: true,
              full: true,
            })}
            <div className="saml-full saml-metadata">
              <a
                href="/api/v1/auth/saml/metadata?download=true"
                download="netrix-saml-metadata.xml"
              >
                <DownloadSimple size={18} aria-hidden="true" /> SP metadata XML
                indir
              </a>
            </div>
            <div className="saml-full saml-import" aria-busy={importing}>
              <div className="saml-import-controls">
                <label>
                  <span>Microsoft Entra ID Metadata XML URL</span>
                  <input
                    name="idp_metadata_url"
                    type="url"
                    autoComplete="off"
                    spellCheck={false}
                    maxLength={1024}
                    value={values.idp_metadata_url}
                    placeholder="https://login.microsoftonline.com/…"
                    aria-describedby="saml-import-help"
                    onChange={(e) => {
                      change("idp_metadata_url", e.target.value);
                      setImportError("");
                      setImportNotice("");
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        void pullMetadata();
                      }
                    }}
                  />
                </label>
                <button
                  className="secondary"
                  type="button"
                  disabled={!values.idp_metadata_url.trim()}
                  onClick={() => void pullMetadata()}
                >
                  {importing ? "Metadata alınıyor…" : "Metadata’yı aktar"}
                </button>
              </div>
              <p className="muted" id="saml-import-help">
                Entra’daki SAML ekranından App Federation Metadata URL değerini
                kopyalayın.
              </p>
              {importError && (
                <div className="error" role="alert">
                  {importError}
                </div>
              )}
              {importNotice && (
                <p className="muted" role="status">
                  {importNotice}
                </p>
              )}
            </div>
            {field("idp_entity_id", "IdP Entity ID", {
              full: true,
              placeholder: "https://sts.windows.net/<kiracı-kimliği>/…",
            })}
            {field("sso_url", "IdP SSO URL", { full: true, type: "url" })}
            {field("slo_url", "IdP SLO URL (isteğe bağlı)", {
              full: true,
              type: "url",
            })}
            <label className="saml-full">
              <span>X.509 imzalama sertifikaları</span>
              <textarea
                name="x509_certificate"
                rows={6}
                spellCheck={false}
                maxLength={16000}
                value={values.x509_certificate}
                onChange={(e) => change("x509_certificate", e.target.value)}
                placeholder="-----BEGIN CERTIFICATE-----"
              />
            </label>
            {field("email_attribute", "E-posta Attribute")}
            {field("display_name_attribute", "Görünen Ad Attribute")}
            {field("nameid_mapping", "NameID Mapping", { full: true })}
            <label className="saml-full">
              <span>Rol Mapping JSON</span>
              <textarea
                name="role_mapping"
                rows={4}
                spellCheck={false}
                value={mapping}
                aria-describedby="saml-role-help"
                onChange={(e) => {
                  setMapping(e.target.value);
                  setNotice("");
                }}
              />
            </label>
          </div>
        </fieldset>
        <p id="saml-role-help" className="muted">
          Entra rolünü veya grup kimliğini <code>viewer</code>,{" "}
          <code>operator</code> ya da <code>admin</code> ile eşleştirin. Eşleşme
          yoksa salt okunur rol atanır. Elle verilen rol, Ekip &amp; yetkiler
          ekranından yönetilir.
        </p>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <div className="saml-form-actions">
          <button
            type="submit"
            className="primary"
            disabled={saving || importing}
          >
            <FloppyDisk size={18} aria-hidden="true" />{" "}
            {saving ? "Kaydediliyor…" : "SAML ayarlarını kaydet"}
          </button>
          <span role="status">{notice}</span>
        </div>
      </form>
    </section>
  );
}
