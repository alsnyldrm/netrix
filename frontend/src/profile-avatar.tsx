import { useEffect, useRef, useState } from "react";
import { Camera, Check, Trash } from "@phosphor-icons/react";
import { api, clearReadCache } from "./data";
import "./profile-avatar.css";

type AvatarData = {
  url: string | null;
  preset_id: string | null;
  presets: { id: string; name: string; url: string }[];
};
export function useAccountAvatar(userId?: string) {
  const [state, setState] = useState<{
    owner?: string;
    data?: AvatarData;
    error: string;
  }>({ error: "" });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setState({ owner: userId, error: "" });
    if (userId)
      api("/access/avatar").then(
        (data) => {
          if (active) setState({ owner: userId, data, error: "" });
        },
        (e) => {
          if (active) setState({ owner: userId, error: e.message });
        },
      );
    return () => {
      active = false;
    };
  }, [userId, retry]);
  return {
    data: state.owner === userId ? state.data : undefined,
    error: state.owner === userId ? state.error : "",
    retry: () => setRetry((n) => n + 1),
    changed: (data: AvatarData) => setState({ owner: userId, data, error: "" }),
  };
}
export type AccountAvatar = ReturnType<typeof useAccountAvatar>;

export function UserPortrait({
  name,
  url,
  className = "avatar",
}: {
  name: string;
  url?: string | null;
  className?: string;
}) {
  return (
    <span className={className} aria-hidden="true">
      {url ? (
        <img src={url} alt="" width="88" height="88" />
      ) : (
        name
          .split(" ")
          .filter(Boolean)
          .slice(0, 2)
          .map((n) => n[0])
          .join("")
      )}
    </span>
  );
}

export function AvatarEditor({
  name,
  avatar,
}: {
  name: string;
  avatar: AccountAvatar;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  async function save(action: () => Promise<AvatarData>, message: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      avatar.changed(await action());
      setNotice(message);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function upload(file?: File) {
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setError("Fotoğraf en çok 5 MB olabilir.");
      return;
    }
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError("JPG, PNG veya WebP dosyası seçin.");
      return;
    }
    await save(async () => {
      const response = await fetch("/api/v1/access/avatar", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Netrix-Request": "1", "Content-Type": file.type },
        body: file,
      });
      const data = await response
        .json()
        .catch(() => ({ detail: "Fotoğraf yüklenemedi. Yeniden deneyin." }));
      if (!response.ok) {
        if (response.status === 401)
          window.dispatchEvent(new Event("netrix:session-expired"));
        throw new Error(data.detail || "Fotoğraf yüklenemedi.");
      }
      clearReadCache();
      return data;
    }, "Profil fotoğrafınız kaydedildi.");
  }
  return (
    <section
      className="profile-avatar-editor"
      aria-labelledby="profile-avatar-title"
      aria-busy={busy}
    >
      <h4 id="profile-avatar-title">Profil görseli</h4>
      <div className="profile-avatar-upload">
        <UserPortrait
          name={name}
          url={avatar.data?.url}
          className="profile-avatar-preview"
        />
        <div className="profile-avatar-upload-content">
          <div className="profile-avatar-actions">
            <button
              type="button"
              className="primary"
              disabled={busy || !avatar.data}
              onClick={() => input.current?.click()}
            >
              <Camera size={18} aria-hidden="true" />
              Fotoğraf yükle
            </button>
            {avatar.data?.url && (
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() =>
                  void save(
                    () => api("/access/avatar", "DELETE"),
                    "Profil görseliniz kaldırıldı.",
                  )
                }
              >
                <Trash size={18} aria-hidden="true" />
                Kaldır
              </button>
            )}
          </div>
          <p className="muted" id="profile-avatar-help">
            JPG, PNG veya WebP · En çok 5 MB.
            <br />
            Fotoğrafınız kare olarak ortalanır.
          </p>
          <input
            ref={input}
            type="file"
            name="profile_photo"
            accept="image/jpeg,image/png,image/webp"
            aria-label="Profil fotoğrafı dosyası"
            aria-describedby="profile-avatar-help"
            hidden
            disabled={busy}
            onChange={(event) => {
              void upload(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </div>
      </div>
      {avatar.error ? (
        <div role="alert">
          {avatar.error}{" "}
          <button type="button" className="secondary" onClick={avatar.retry}>
            Yeniden dene
          </button>
        </div>
      ) : !avatar.data ? (
        <p role="status">Profil görselleri yükleniyor…</p>
      ) : (
        <>
          <p className="profile-avatar-label">Ya da bir anime avatarı seçin</p>
          <div
            className="profile-avatar-grid"
            role="group"
            aria-label="Anime avatarları"
          >
            {avatar.data.presets.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className="profile-avatar-option"
                aria-label={preset.name}
                aria-pressed={avatar.data?.preset_id === preset.id}
                disabled={busy}
                onClick={() =>
                  void save(
                    () =>
                      api("/access/avatar", "PUT", { preset_id: preset.id }),
                    `${preset.name} avatarınız olarak seçildi.`,
                  )
                }
              >
                <span className="profile-avatar-option-image">
                  <img
                    src={preset.url}
                    alt=""
                    loading="lazy"
                    width="64"
                    height="64"
                  />
                  {avatar.data?.preset_id === preset.id && (
                    <span className="profile-avatar-check">
                      <Check size={14} weight="bold" aria-hidden="true" />
                    </span>
                  )}
                </span>
                <span>{preset.name}</span>
              </button>
            ))}
          </div>
        </>
      )}
      {error && (
        <p className="profile-avatar-error" role="alert">
          {error}
        </p>
      )}
      <p className="profile-avatar-notice" role="status">
        {busy ? "Profil görseliniz kaydediliyor…" : notice}
      </p>
    </section>
  );
}
