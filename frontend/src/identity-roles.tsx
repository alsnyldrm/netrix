import { useState } from "react";
import { Trash } from "@phosphor-icons/react";
import { Dialog } from "./main";
import { api } from "./data";
import { isRecoveryOwner } from "./permissions";

export type UserDeleteTarget = {
  id: string;
  display_name: string;
  email: string;
  auth_source: string;
};

const authLabel = (account: UserDeleteTarget) =>
  account.auth_source === "saml" ? "Microsoft Entra ID" : "Yerel parola";
const accountLabel = (account: UserDeleteTarget) =>
  `${account.display_name} (${account.email}, ${authLabel(account)})`;

export function UserDeleteAction({
  account,
  onDelete,
}: {
  account?: UserDeleteTarget;
  onDelete: (account: UserDeleteTarget) => void;
}) {
  return (
    account && (
      <button
        className="icon-button delete-button user-delete-action"
        aria-label={`${accountLabel(account)} sil`}
        title="Kullanıcıyı sil"
        onClick={() => onDelete(account)}
      >
        <Trash size={17} aria-hidden="true" />
      </button>
    )
  );
}

export function UserDeleteSelection({
  account,
  checked,
  onSelect,
}: {
  account?: UserDeleteTarget;
  checked: boolean;
  onSelect: (checked: boolean) => void;
}) {
  return (
    <td className="user-select">
      {account && (
        <input
          type="checkbox"
          aria-label={`${accountLabel(account)} seç`}
          checked={checked}
          onChange={(event) => onSelect(event.target.checked)}
        />
      )}
    </td>
  );
}

export function UserDeleteDialog({
  accounts,
  bulk,
  onClose,
  onDeleted,
}: {
  accounts: UserDeleteTarget[];
  bulk: boolean;
  onClose: () => void;
  onDeleted: (count: number) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Dialog
      title={bulk ? "Seçili kullanıcıları sil" : "Kullanıcıyı sil"}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="user-delete-form"
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          setBusy(true);
          setError("");
          try {
            if (bulk) {
              const result = await api("/users/bulk-delete", "POST", {
                ids: accounts.map(({ id }) => id),
              });
              onDeleted(result.deleted);
            } else {
              await api(`/users/${accounts[0].id}`, "DELETE");
              onDeleted(1);
            }
          } catch (reason) {
            setError((reason as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <p>
          {bulk
            ? `${accounts.length} hesap silinecek ve açık oturumları kapatılacak.`
            : "Hesap silinecek ve açık oturumları kapatılacak."}{" "}
          Bu işlem geri alınamaz.
        </p>
        <ul
          className="user-delete-targets"
          tabIndex={0}
          aria-label="Silinecek hesaplar"
        >
          {accounts.map((account) => (
            <li key={account.id}>
              <strong>{account.display_name}</strong>
              <span className="muted">
                {account.email} · {authLabel(account)}
              </span>
            </li>
          ))}
        </ul>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <footer className="user-delete-actions">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onClose}
          >
            Vazgeç
          </button>
          <button
            type="submit"
            className="secondary user-delete-confirm"
            disabled={busy}
          >
            {busy ? "Siliniyor…" : bulk ? "Seçilenleri sil" : "Kullanıcıyı sil"}
          </button>
        </footer>
      </form>
    </Dialog>
  );
}

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
  const owner = isRecoveryOwner(user);
  return (
    <Dialog title="Kullanıcı rollerini düzenle" onClose={onClose} drawer>
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
          <span className="muted">
            {user.email} ·{" "}
            {user.auth_source === "saml"
              ? "Microsoft Entra ID"
              : "Yerel parola"}
          </span>
        </p>
        <label>
          Uygulama rolü
          <select
            value={role}
            disabled={owner || busy}
            aria-describedby={owner ? "recovery-role-help" : undefined}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="super_admin">Süper yönetici</option>
            <option value="viewer">İzleyici</option>
            <option value="operator">Operatör</option>
            <option value="admin">Yönetici</option>
          </select>
          {owner && (
            <small id="recovery-role-help" className="muted">
              Yerel kurtarma hesabının rolü korunur.
            </small>
          )}
        </label>
        <fieldset>
          <legend>Ek roller</legend>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={role === "super_admin" || ssh}
              disabled={role === "super_admin" || busy}
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
