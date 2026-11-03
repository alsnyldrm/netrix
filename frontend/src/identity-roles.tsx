import { useState } from "react";
import { Dialog } from "./main";
import { api } from "./data";
import { SUPER_ADMIN_EMAIL } from "./permissions";
export function UserRoleEditor({
  user,
  onClose,
  onSaved,
}: {
  user: Record<string, any>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [role, setRole] = useState(user.role);
  const [ssh, setSSH] = useState(Boolean(user.ssh_access));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const owner = user.email.toLowerCase() === SUPER_ADMIN_EMAIL;
  return (
    <Dialog title="Kullanıcı rollerini düzenle" onClose={onClose}>
      <form
        className="user-role-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api(`/users/${user.id}/roles`, "PUT", {
              role,
              ssh_access: ssh,
            });
            onSaved();
            onClose();
          } catch (e: any) {
            setError(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <p>
          <b>{user.display_name}</b>
          <br />
          <span className="muted">{user.email}</span>
        </p>
        <label>
          Uygulama rolü
          <select
            value={role}
            disabled={owner}
            onChange={(e) => setRole(e.target.value)}
          >
            {owner && <option value="super_admin">Süper yönetici</option>}
            <option value="viewer">İzleyici</option>
            <option value="operator">Operatör</option>
            <option value="admin">Yönetici</option>
          </select>
        </label>
        <fieldset>
          <legend>Ek roller</legend>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={role === "super_admin" || ssh}
              disabled={role === "super_admin"}
              onChange={(e) => setSSH(e.target.checked)}
            />
            SSH bağlantısı
          </label>
          <p className="muted">
            {role === "super_admin"
              ? "Süper yönetici uygulamadaki tüm yetkilere sahiptir."
              : "Envanter cihazlarına kendi SSH bilgileriyle bağlantı ve toplu komut gönderme yetkisi verir."}
          </p>
        </fieldset>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="secondary" onClick={onClose}>
            Vazgeç
          </button>
          <button className="primary" disabled={busy}>
            Rolleri kaydet
          </button>
        </div>
      </form>
    </Dialog>
  );
}
