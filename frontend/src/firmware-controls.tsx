import { useEffect, useState } from "react";
import { Stop, Trash, WarningOctagon } from "@phosphor-icons/react";
import { api } from "./data";
import { Dialog } from "./main";

type Row = Record<string, any>;
export type PlanAction = "delete" | "cancel" | "force-stop";
const LABELS = {
  delete: "Sil",
  cancel: "Durdur",
  "force-stop": "Zorla durdur",
};

export function PlanActions({
  plan,
  onAction,
}: {
  plan: Row;
  onAction: (action: PlanAction) => void;
}) {
  const terminal = ["succeeded", "cancelled"].includes(plan.status);
  const canDelete =
    !["queued", "running", "ready"].includes(plan.status) &&
    !plan.counts?.attention &&
    (!plan.counts?.queued || plan.status === "draft");
  return (
    <div className="fw-plan-actions">
      <button
        className="secondary"
        disabled={terminal || plan.cancel_requested}
        aria-label={`${plan.name} planını durdur`}
        onClick={() => onAction("cancel")}
      >
        <Stop size={16} aria-hidden="true" />
        Durdur
      </button>
      <button
        className="secondary fw-destructive"
        disabled={
          terminal ||
          plan.force_stop_requested ||
          !["queued", "running", "paused"].includes(plan.status)
        }
        aria-label={`${plan.name} planını zorla durdur`}
        onClick={() => onAction("force-stop")}
      >
        <WarningOctagon size={16} aria-hidden="true" />
        Zorla durdur
      </button>
      <button
        className="secondary fw-destructive"
        disabled={!canDelete}
        title={
          canDelete
            ? "Planı listeden kaldır"
            : "Önce planı durdurun ve cihaz sonuçlarını doğrulayın"
        }
        aria-label={`${plan.name} planını sil`}
        onClick={() => onAction("delete")}
      >
        <Trash size={16} aria-hidden="true" />
        Sil
      </button>
    </div>
  );
}

export function PlanActionDialog({
  plan,
  action,
  onClose,
  onSaved,
}: {
  plan: Row;
  action: PlanAction;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <Dialog title={`${plan.name} · ${LABELS[action]}`} onClose={onClose}>
      <form
        className="fw-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api(
              `/firmware/plans/${plan.id}${action === "delete" ? "" : "/" + action}`,
              action === "delete" ? "DELETE" : "POST",
              action === "force-stop"
                ? { plan_name: name, confirmed: true }
                : undefined,
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
        <p>
          <b>{plan.name}</b> planı için{" "}
          {LABELS[action].toLocaleLowerCase("tr-TR")} işlemini onaylayın.
        </p>
        <p
          className={
            action === "force-stop" ? "fw-note fw-force-note" : "fw-note"
          }
        >
          {action === "delete"
            ? "Plan güncelleme planları listesinden kaldırılır. İşlem geçmişi, cihaz yanıtları ve konfigürasyon yedekleri korunur."
            : action === "cancel"
              ? "Yeni cihaz işlemleri başlamaz. Devam eden aktarım ve yazımın güvenle tamamlanması beklenir; yeni yeniden başlatma işlemi gönderilmez."
              : "NETRIX aktarım ve SSH oturumları kapatılır. Cihazda başlamış yazım devam edebilir veya yarım kalabilir. Bu cihazlar sonuç belirsiz durumunda kilitli kalır; yeniden doğrulama veya manuel kurtarma gerekir."}
        </p>
        {action === "force-stop" && (
          <label>
            Onay için planın tam adı
            <input
              required
              autoComplete="off"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <small>{plan.name}</small>
          </label>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="fw-form-actions">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={onClose}
          >
            Vazgeç
          </button>
          <button
            className={
              action === "force-stop" ? "secondary fw-destructive" : "primary"
            }
            disabled={busy || (action === "force-stop" && name !== plan.name)}
          >
            {busy ? "İşleniyor…" : LABELS[action]}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function PlanConcurrency({
  plan,
  onSaved,
}: {
  plan: Row;
  onSaved: () => void;
}) {
  const [value, setValue] = useState(plan.concurrency),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => setValue(plan.concurrency), [plan.id, plan.concurrency]);
  const disabled =
    plan.cancel_requested || ["cancelled", "succeeded"].includes(plan.status);
  return (
    <div className="fw-concurrency-panel">
      <div className="fw-concurrency-controls">
        <label>
          Eşzamanlı cihaz
          <select
            aria-label="Planın eşzamanlı cihaz sayısı"
            value={value}
            disabled={disabled || busy}
            onChange={(e) => setValue(Number(e.target.value))}
          >
            {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <button
          className="secondary"
          disabled={disabled || busy || value === plan.concurrency}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              await api(`/firmware/plans/${plan.id}/concurrency`, "PATCH", {
                concurrency: value,
              });
              onSaved();
            } catch (e: any) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Kaydediliyor…" : "Eşzamanlılığı kaydet"}
        </button>
      </div>
      <p className="muted">
        Sınır azaltıldığında devam eden cihaz işlemleri kesilmez. Sonraki
        hedefler yeni sınıra göre başlar.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}
