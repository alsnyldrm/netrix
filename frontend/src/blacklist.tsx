import {
  ArrowCounterClockwise,
  ArrowsClockwise,
  Eye,
  Info,
  ListPlus,
  MagnifyingGlass,
  PaperPlaneTilt,
  PencilSimple,
  Plus,
  Trash,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { api, useLiveQuery } from "./data";
import { Dialog, date } from "./main";
import "./blacklist.css";

type Profile = { type: string; name: string | null; number: number | null };
type Group = {
  id: string;
  name: string;
  device_ids: string[];
  profiles: Record<string, Profile>;
  status: "active" | "deleting";
  active_entries: number;
  applied_devices: number;
  pending_devices: number;
};
type Job = {
  job_id: string;
  status: string;
  phase: string;
  error: string;
  ports: string[];
  added: string[];
  removed: string[];
  acl_removed: boolean;
  finished_at: string | null;
  cancel_requested: boolean;
};
type EntryDevice = {
  device_id: string;
  name: string;
  desired: boolean;
  applied: boolean | null;
  job: Job | null;
};
type EntryStatus = "draft" | "active" | "disabled" | "deleting";
type Entry = {
  id: string;
  address: string;
  description: string;
  group_ids: string[];
  status: EntryStatus;
  expires_at: string | null;
  updated_at: string;
  devices: EntryDevice[];
  state: string;
};
type DeviceState = {
  device_id: string;
  name: string;
  management_ip: string;
  model: string;
  groups: string[];
  desired_acl: string | null;
  desired_count: number;
  applied_acl: string | null;
  applied_count: number;
  verified_at: string | null;
  recorded: boolean;
  status: string;
  issue: string;
  will_remove_acl: boolean;
  job: Job | null;
};
type Device = {
  id: string;
  name: string;
  model: string;
  management_ip: string;
  family: string;
};
type Family = {
  label: string;
  types: { id: string; label: string; number_range: [number, number] | null }[];
};
type Inventory = { items: Device[]; families: Record<string, Family> };
type Preview = {
  address: string;
  groups: { id: string; name: string }[];
  targets: (Omit<Device, "id" | "family"> & {
    device_id: string;
    profile: Profile | null;
    group_ids: string[];
    issue: string;
  })[];
};
type Skipped = { device_id: string | null; name: string; reason: string };
type ActionResult = {
  job_ids: string[];
  devices: number;
  skipped?: Skipped[];
  deleted?: number;
};
type EntryAction = "send" | "remove" | "delete";
export type BlacklistPage = "entries" | "groups" | "devices";

const root = "/blacklist";
const ACTIVE_JOB = ["queued", "running"];
const keyText = (value: string) => value.toLocaleLowerCase("tr-TR");
const toggle = (ids: string[], id: string) =>
  ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id];
const aclLabel = (profile: Profile) =>
  [profile.name, profile.number === null ? null : `#${profile.number}`]
    .filter(Boolean)
    .join(" · ");
const busyJob = (job: Job | null) => !!job && ACTIVE_JOB.includes(job.status);

/** Local datetime-local value for an ISO timestamp, or "". */
function localInput(value: string | null | undefined) {
  if (!value) return "";
  const at = new Date(value);
  const shifted = new Date(at.getTime() - at.getTimezoneOffset() * 60000);
  return shifted.toISOString().slice(0, 16);
}
const isoFromLocal = (value: FormDataEntryValue | null) =>
  value ? new Date(String(value)).toISOString() : null;

const ENTRY_STATES: Record<string, [string, string]> = {
  draft: ["Taslak", ""],
  queued: ["Sırada", "queued"],
  running: ["Uygulanıyor", "running"],
  blocked: ["Engelli", "active"],
  partial: ["Kısmi", "partial"],
  pending: ["Gönderilmeyi bekliyor", "pending"],
  failed: ["Hata", "failed"],
  disabled: ["Kaldırıldı", ""],
  remove_pending: ["Kaldırılmayı bekliyor", "warning"],
  deleting: ["Siliniyor", "queued"],
  delete_failed: ["Silinemedi", "failed"],
  no_target: ["Hedef yok", "warning"],
};
const DEVICE_STATES: Record<string, [string, string]> = {
  synced: ["Eşit", "active"],
  pending: ["Eşitleme bekliyor", "pending"],
  queued: ["Sırada", "queued"],
  running: ["Uygulanıyor", "running"],
  failed: ["Hata", "failed"],
  issue: ["Uygun değil", "warning"],
};
const JOB_STATES: Record<string, string> = {
  queued: "Sırada",
  running: "Uygulanıyor",
  succeeded: "Doğrulandı",
  failed: "Başarısız",
  partial: "Kısmi",
  cancelled: "İptal edildi",
};
const PHASES: Record<string, string> = {
  queued: "Kuyrukta",
  preflight: "Ön kontrol",
  removing: "Eski ACL kaldırılıyor",
  applying: "ACL ve portlar eşitleniyor",
  verifying: "Çalışan konfigürasyon doğrulanıyor",
  saving: "Kalıcı konfigürasyona kaydediliyor",
  verified: "Tüm portlar ve kalıcı konfigürasyon doğrulandı",
  removed: "NETRIX ACL’si cihazdan kaldırıldı",
};
const ACTION_TEXT: Record<
  EntryAction,
  { title: string; button: string; busy: string; done: string }
> = {
  send: {
    title: "Cihazlara gönder",
    button: "Cihazlara gönder",
    busy: "Kuyruğa alınıyor…",
    done: "Gönderim kuyruğa alındı.",
  },
  remove: {
    title: "Engeli kaldır",
    button: "Cihazlardan kaldır",
    busy: "Kuyruğa alınıyor…",
    done: "Kaldırma kuyruğa alındı.",
  },
  delete: {
    title: "IP kaydını sil",
    button: "Kaldır ve sil",
    busy: "Siliniyor…",
    done: "Silme işlemi başlatıldı.",
  },
};

function StateBadge({
  map,
  value,
}: {
  map: Record<string, [string, string]>;
  value: string;
}) {
  const [label, tone] = map[value] ?? [value, ""];
  return (
    <span className={"badge " + tone}>
      <i />
      {label}
    </span>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="info-note blacklist-notice">
      <Info size={18} aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}

function ErrorText({ children }: { children: React.ReactNode }) {
  return children ? (
    <p className="error" role="alert">
      {children}
    </p>
  ) : null;
}

function FormActions({
  busy,
  disabled,
  close,
  label,
  busyLabel = "Kaydediliyor…",
  danger = false,
}: {
  busy: boolean;
  disabled: boolean;
  close: () => void;
  label: string;
  busyLabel?: string;
  danger?: boolean;
}) {
  return (
    <div className="blacklist-form-actions">
      <button
        type="button"
        className="secondary"
        onClick={close}
        disabled={busy}
      >
        Vazgeç
      </button>
      <button
        type="submit"
        className={danger ? "secondary blacklist-danger" : "primary"}
        disabled={busy || disabled}
      >
        {busy ? busyLabel : label}
      </button>
    </div>
  );
}

function GroupChecklist({
  groups,
  value,
  onChange,
}: {
  groups: Group[];
  value: string[];
  onChange: (ids: string[]) => void;
}) {
  return (
    <fieldset className="blacklist-fieldset">
      <legend>Hedef ACL grupları</legend>
      <div className="blacklist-checklist">
        {groups.map((group) => (
          <label key={group.id}>
            <input
              type="checkbox"
              checked={value.includes(group.id)}
              onChange={() => onChange(toggle(value, group.id))}
            />
            <span>{group.name}</span>
            <small>{group.device_ids.length} cihaz</small>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function ExpiryField({ value }: { value?: string | null }) {
  return (
    <label>
      Bitiş zamanı · yerel saat (isteğe bağlı)
      <input
        type="datetime-local"
        name="expires_at"
        defaultValue={localInput(value)}
      />
      <small className="blacklist-hint">
        Süre dolduğunda engel otomatik olarak cihazlardan kaldırılır.
      </small>
    </label>
  );
}

function EntryEditor({
  entry,
  groups,
  close,
  saved,
}: {
  entry?: Entry;
  groups: Group[];
  close: () => void;
  saved: () => void;
}) {
  const [groupIds, setGroupIds] = useState(entry?.group_ids ?? []);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const locked = !!entry && entry.status === "active";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const values = new FormData(event.currentTarget);
    if (!groupIds.length) {
      setError("En az bir ACL grubu seçin.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api(
        root + "/entries" + (entry ? `/${entry.id}` : ""),
        entry ? "PATCH" : "POST",
        {
          address: values.get("address") ?? entry?.address,
          description: values.get("description"),
          group_ids: groupIds,
          expires_at: isoFromLocal(values.get("expires_at")),
        },
      );
      saved();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={entry ? "IP kaydını düzenle" : "Yeni IP kaydı"}
      onClose={busy ? () => {} : close}
    >
      <form className="blacklist-form" onSubmit={submit} aria-busy={busy}>
        <label>
          IP adresi
          <input
            name="address"
            defaultValue={entry?.address}
            maxLength={45}
            required
            readOnly={locked}
            autoComplete="off"
            spellCheck={false}
            placeholder="Örn. 192.0.2.10"
            className="mono"
          />
          {locked && (
            <small className="blacklist-hint">
              Uygulanmış adres değiştirilemez. Önce engeli kaldırın.
            </small>
          )}
        </label>
        <label>
          Açıklama (isteğe bağlı)
          <textarea
            name="description"
            defaultValue={entry?.description}
            maxLength={300}
            rows={2}
          />
        </label>
        <ExpiryField value={entry?.expires_at} />
        <GroupChecklist
          groups={groups}
          value={groupIds}
          onChange={setGroupIds}
        />
        {locked && (
          <Notice>
            Grup veya süre değişikliği cihazlara ancak yeniden gönderimle
            yansır.
          </Notice>
        )}
        <ErrorText>{error}</ErrorText>
        <FormActions
          busy={busy}
          disabled={!groups.length}
          close={close}
          label="Kaydet"
        />
      </form>
    </Dialog>
  );
}

const splitAddresses = (text: string) =>
  text
    .split(/[\s,;]+/)
    .map((value) => value.trim())
    .filter(Boolean);

function BulkEditor({
  groups,
  close,
  saved,
}: {
  groups: Group[];
  close: () => void;
  saved: (message: string) => void;
}) {
  const [text, setText] = useState("");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const addresses = splitAddresses(text);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const values = new FormData(event.currentTarget);
    if (!addresses.length || !groupIds.length) {
      setError(
        !addresses.length
          ? "En az bir IP adresi girin."
          : "En az bir ACL grubu seçin.",
      );
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api(root + "/entries/bulk", "POST", {
        addresses,
        description: values.get("description"),
        group_ids: groupIds,
        expires_at: isoFromLocal(values.get("expires_at")),
      });
      saved(
        `${result.created} IP kaydı eklendi.` +
          (result.skipped.length
            ? ` Zaten kayıtlı ${result.skipped.length} adres atlandı.`
            : ""),
      );
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog title="Toplu IP ekle" onClose={busy ? () => {} : close}>
      <form className="blacklist-form" onSubmit={submit} aria-busy={busy}>
        <label>
          IP adresleri
          <textarea
            className="mono"
            value={text}
            onChange={(event) => setText(event.target.value)}
            rows={6}
            spellCheck={false}
            placeholder={"192.0.2.10\n192.0.2.11, 192.0.2.12"}
          />
          <small className="blacklist-hint" role="status">
            {addresses.length} adres · satır, boşluk, virgül veya noktalı
            virgülle ayırın. En fazla 500.
          </small>
        </label>
        <label>
          Açıklama (isteğe bağlı)
          <textarea name="description" maxLength={300} rows={2} />
        </label>
        <ExpiryField />
        <GroupChecklist
          groups={groups}
          value={groupIds}
          onChange={setGroupIds}
        />
        <Notice>
          Kayıtlar taslak olarak eklenir. Cihazlara uygulamak için seçip
          gönderin.
        </Notice>
        <ErrorText>{error}</ErrorText>
        <FormActions
          busy={busy}
          disabled={!groups.length || addresses.length > 500}
          close={close}
          label="Kayıtları ekle"
        />
      </form>
    </Dialog>
  );
}

function GroupEditor({
  group,
  close,
  saved,
}: {
  group?: Group;
  close: () => void;
  saved: () => void;
}) {
  const inventory = useLiveQuery<Inventory>(root + "/devices");
  const [deviceIds, setDeviceIds] = useState(group?.device_ids ?? []);
  const [filter, setFilter] = useState("");
  const [visible, setVisible] = useState(30);
  const [profiles, setProfiles] = useState(group?.profiles ?? {});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const devices = inventory.data?.items;
  const families = inventory.data?.families;
  const selected = useMemo(() => new Set(deviceIds), [deviceIds]);
  const selectedFamilies = new Set(
    devices?.filter((item) => selected.has(item.id)).map((item) => item.family),
  );
  const availableIds = new Set(devices?.map((item) => item.id));
  const missingIds = devices
    ? deviceIds.filter((id) => !availableIds.has(id))
    : [];
  const displayed =
    devices?.filter((item) =>
      keyText(`${item.name} ${item.model} ${item.management_ip}`).includes(
        keyText(filter.trim()),
      ),
    ) ?? [];

  function profileFor(family: string): Profile {
    return (
      profiles[family] ?? {
        type: families![family].types[0].id,
        name: null,
        number: null,
      }
    );
  }

  function changeProfile(family: string, changes: Partial<Profile>) {
    setProfiles({
      ...profiles,
      [family]: { ...profileFor(family), ...changes },
    });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    const configured = Object.fromEntries(
      [...selectedFamilies].map((family) => {
        const profile = profileFor(family);
        return [family, { ...profile, name: profile.name?.trim() || null }];
      }),
    );
    const incomplete = Object.entries(configured).find(([family, profile]) =>
      family === "comware_1950"
        ? profile.number === null
        : !profile.name && profile.number === null,
    );
    if (!deviceIds.length || missingIds.length || incomplete) {
      setError(
        !deviceIds.length
          ? "En az bir cihaz seçin."
          : missingIds.length
            ? "Kaydetmeden önce uygun olmayan cihazları seçimden çıkarın."
            : `${families![incomplete![0]].label} için ACL bilgisi girin.`,
      );
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api(
        root + "/groups" + (group ? `/${group.id}` : ""),
        group ? "PATCH" : "POST",
        {
          name: data.get("name"),
          device_ids: deviceIds,
          profiles: configured,
        },
      );
      saved();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={group ? "ACL grubunu düzenle" : "Yeni ACL grubu"}
      onClose={busy ? () => {} : close}
      wide
    >
      <form className="blacklist-form" onSubmit={submit} aria-busy={busy}>
        <label>
          Grup adı
          <input
            name="name"
            defaultValue={group?.name}
            maxLength={120}
            required
            autoComplete="off"
          />
        </label>
        <fieldset className="blacklist-fieldset">
          <legend>Grup cihazları</legend>
          <div className="blacklist-picker-bar">
            <label className="search-box">
              <MagnifyingGlass size={17} aria-hidden="true" />
              <input
                aria-label="Cihaz ara"
                type="search"
                value={filter}
                placeholder="Cihaz ara…"
                onChange={(event) => {
                  setFilter(event.target.value);
                  setVisible(30);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") event.preventDefault();
                }}
              />
            </label>
            <span role="status">{deviceIds.length} cihaz seçildi</span>
          </div>
          {inventory.loading && <p role="status">Cihazlar yükleniyor…</p>}
          <ErrorText>{inventory.error}</ErrorText>
          {missingIds.length > 0 && (
            <button
              className="secondary blacklist-prune"
              type="button"
              onClick={() =>
                setDeviceIds((ids) => ids.filter((id) => availableIds.has(id)))
              }
            >
              Uygun olmayan {missingIds.length} cihazı çıkar
            </button>
          )}
          {devices && displayed.length === 0 && (
            <p className="blacklist-empty">Uygun cihaz bulunamadı.</p>
          )}
          {displayed.length > 0 && (
            <div className="blacklist-checklist">
              {displayed.slice(0, visible).map((device) => (
                <label key={device.id}>
                  <input
                    type="checkbox"
                    checked={selected.has(device.id)}
                    onChange={() =>
                      setDeviceIds((ids) => toggle(ids, device.id))
                    }
                  />
                  <span>
                    <strong>{device.name}</strong>
                    <small>{device.model}</small>
                  </span>
                  <small className="mono">{device.management_ip}</small>
                </label>
              ))}
              {displayed.length > visible && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setVisible((count) => count + 30)}
                >
                  Daha fazla cihaz göster
                </button>
              )}
            </div>
          )}
        </fieldset>
        {families &&
          Object.entries(families)
            .filter(([id]) => selectedFamilies.has(id))
            .map(([family, options]) => {
              const profile = profileFor(family);
              const numberRange = options.types.find(
                (item) => item.id === profile.type,
              )?.number_range;
              return (
                <fieldset
                  className="blacklist-fieldset blacklist-profile"
                  key={family}
                >
                  <legend>{options.label}</legend>
                  <div className="blacklist-profile-fields">
                    <label>
                      <span>ACL türü</span>
                      <select
                        name={`${family}-type`}
                        value={profile.type}
                        onChange={(event) =>
                          changeProfile(family, {
                            type: event.target.value,
                            number: null,
                          })
                        }
                      >
                        {options.types.map((item) => (
                          <option value={item.id} key={item.id}>
                            {item.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>
                        {family === "comware_1950"
                          ? "ACL adı (isteğe bağlı)"
                          : "ACL adı"}
                      </span>
                      <input
                        name={`${family}-name`}
                        value={profile.name ?? ""}
                        maxLength={64}
                        onChange={(event) =>
                          changeProfile(family, {
                            name: event.target.value || null,
                          })
                        }
                        required={!numberRange}
                        autoComplete="off"
                        spellCheck={false}
                      />
                    </label>
                    {numberRange && (
                      <label>
                        <span>ACL numarası</span>
                        <input
                          name={`${family}-number`}
                          type="number"
                          min={numberRange[0]}
                          max={numberRange[1]}
                          placeholder={numberRange.join("–")}
                          value={profile.number ?? ""}
                          required={family === "comware_1950"}
                          onChange={(event) =>
                            changeProfile(family, {
                              number:
                                event.target.value === ""
                                  ? null
                                  : event.target.valueAsNumber,
                            })
                          }
                        />
                      </label>
                    )}
                  </div>
                  {family === "aos_switch" && (
                    <p>ACL adı veya numarasından birini girin.</p>
                  )}
                  {family === "comware_1950" && (
                    <p>
                      Genişletilmiş CLI gerekiyorsa parolasını cihazın SSH
                      profiline girin.
                    </p>
                  )}
                </fieldset>
              );
            })}
        {group && (
          <Notice>
            ACL kimliği veya cihaz değişikliği cihazlara Eşitle ile yansır. Eski
            NETRIX ACL’si önce kaldırılır, gruptan çıkarılan cihazlardaki
            engeller temizlenir.
          </Notice>
        )}
        <ErrorText>{error}</ErrorText>
        <FormActions
          busy={busy}
          disabled={!devices?.length}
          close={close}
          label="Grubu kaydet"
        />
      </form>
    </Dialog>
  );
}

function SkippedList({ items }: { items: Skipped[] }) {
  if (!items.length) return null;
  return (
    <div className="blacklist-skipped" role="alert">
      <strong>{items.length} cihaz kuyruğa alınamadı</strong>
      <ul>
        {items.map((item, index) => (
          <li key={(item.device_id ?? "") + index}>{item.reason}</li>
        ))}
      </ul>
    </div>
  );
}

function EntryActionDialog({
  action,
  entries,
  groups,
  close,
  done,
}: {
  action: EntryAction;
  entries: Entry[];
  groups: Group[];
  close: () => void;
  done: (message: string, skipped: Skipped[]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const text = ACTION_TEXT[action];
  const single = entries.length === 1 ? entries[0] : undefined;
  const preview = useLiveQuery<Preview>(
    action === "send" && single ? `${root}/entries/${single.id}/preview` : null,
  );
  const groupDevices = new Map(groups.map((g) => [g.id, g.device_ids]));
  const deviceCount =
    action === "send"
      ? new Set(
          entries.flatMap((entry) =>
            entry.group_ids.flatMap((id) => groupDevices.get(id) ?? []),
          ),
        ).size
      : new Set(
          entries.flatMap((entry) =>
            entry.devices
              .filter((device) => device.applied !== false)
              .map((device) => device.device_id),
          ),
        ).size;
  const issues = preview.data?.targets.filter((target) => target.issue) ?? [];
  const ipv6 = entries.filter((entry) => entry.address.includes(":"));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result: ActionResult = await api(
        root + "/entries/actions",
        "POST",
        {
          action,
          entry_ids: entries.map((entry) => entry.id),
        },
      );
      done(
        text.done +
          (result.devices ? ` ${result.devices} cihaz eşitlenecek.` : "") +
          (result.deleted ? ` ${result.deleted} kayıt silindi.` : ""),
        result.skipped ?? [],
      );
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={
        single
          ? text.title
          : `${entries.length} kayıt · ${text.title.toLocaleLowerCase("tr-TR")}`
      }
      onClose={busy ? () => {} : close}
    >
      <form className="blacklist-preview" onSubmit={submit} aria-busy={busy}>
        <p>
          {single ? (
            <strong className="mono">{single.address}</strong>
          ) : (
            <strong>{entries.length} IP adresi</strong>
          )}{" "}
          {action === "send" &&
            (deviceCount
              ? `seçili gruplardaki ${deviceCount} cihazın tüm portlarında engellenecek.`
              : "için hedef cihaz bulunmuyor.")}
          {action === "remove" &&
            (deviceCount
              ? `${deviceCount} cihazdan kaldırılacak. Kayıt saklanır ve yeniden gönderilebilir.`
              : "cihazlarda uygulanmış değil. Kayıt Kaldırıldı durumuna alınır.")}
          {action === "delete" &&
            (deviceCount
              ? `önce ${deviceCount} cihazdan kaldırılacak, doğrulandıktan sonra kayıt silinecek.`
              : "hiçbir cihazda uygulanmamış. Kayıt hemen silinecek.")}
        </p>
        {!single && (
          <ul
            className="blacklist-address-list mono"
            tabIndex={0}
            aria-label="Seçili IP adresleri"
          >
            {entries.map((entry) => (
              <li key={entry.id}>{entry.address}</li>
            ))}
          </ul>
        )}
        <Notice>
          {action === "send"
            ? "Her cihazdaki NETRIX ACL’si etkin IP kayıtlarıyla eşitlenir, giriş yönünde tüm portlara uygulanır ve kalıcı konfigürasyona kaydedilir."
            : "Cihazdaki deny kuralı silinir. ACL’de başka IP kalmazsa NETRIX ACL’si ve port bağlantıları da kaldırılır; değişiklik kalıcı konfigürasyonda doğrulanır."}
        </Notice>
        {action === "send" && single && preview.loading && (
          <p role="status">Hedefler yükleniyor…</p>
        )}
        {issues.map((target) => (
          <p className="error" key={target.device_id}>
            {target.name} · {target.issue}
          </p>
        ))}
        {action === "send" && ipv6.length > 0 && (
          <p className="error">
            IPv6 adresleri ({ipv6.map((entry) => entry.address).join(", ")}) şu
            anda cihazlara gönderilemez.
          </p>
        )}
        <ErrorText>{error || preview.error}</ErrorText>
        <FormActions
          busy={busy}
          disabled={
            (action === "send" &&
              (!deviceCount || issues.length > 0 || ipv6.length > 0)) ||
            preview.loading
          }
          close={close}
          label={text.button}
          busyLabel={text.busy}
          danger={action !== "send"}
        />
      </form>
    </Dialog>
  );
}

function JobLine({
  job,
  canWrite,
  pending,
  cancel,
}: {
  job: Job;
  canWrite: boolean;
  pending: boolean;
  cancel: (id: string) => void;
}) {
  return (
    <>
      <strong>{JOB_STATES[job.status] ?? job.status}</strong>
      {job.phase && job.phase !== "queued" && (
        <small>
          {busyJob(job) || job.status === "succeeded"
            ? PHASES[job.phase] || job.phase
            : `Son aşama · ${PHASES[job.phase] || job.phase}`}
        </small>
      )}
      {(job.added.length > 0 || job.removed.length > 0) && (
        <small>
          {job.added.length} eklendi · {job.removed.length} kaldırıldı
        </small>
      )}
      <a href="#jobs">Görev merkezini aç</a>
      {canWrite && busyJob(job) && (
        <button
          type="button"
          className="secondary"
          disabled={pending || job.cancel_requested}
          onClick={() => cancel(job.job_id)}
        >
          {job.cancel_requested ? "Durdurma istendi" : "Durdur"}
        </button>
      )}
    </>
  );
}

function useCancel(refresh: () => void) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState("");
  async function cancel(id: string) {
    setPending(id);
    setError("");
    try {
      await api("/jobs/" + id + "/cancel", "POST");
      refresh();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setPending("");
    }
  }
  return { error, pending, cancel };
}

function EntryDetail({
  entry,
  groups,
  canWrite,
  close,
  refresh,
}: {
  entry: Entry;
  groups: Map<string, string>;
  canWrite: boolean;
  close: () => void;
  refresh: () => void;
}) {
  const { error, pending, cancel } = useCancel(refresh);
  const preview = useLiveQuery<Preview>(
    entry.devices.length ? null : `${root}/entries/${entry.id}/preview`,
  );
  return (
    <Dialog title="IP kaydı ayrıntısı" onClose={close} wide>
      <div className="blacklist-preview">
        <dl className="blacklist-preview-summary">
          <div>
            <dt>IP adresi</dt>
            <dd className="mono">{entry.address}</dd>
          </div>
          <div>
            <dt>Durum</dt>
            <dd>
              <StateBadge map={ENTRY_STATES} value={entry.state} />
            </dd>
          </div>
          <div>
            <dt>Bitiş</dt>
            <dd>{entry.expires_at ? date(entry.expires_at) : "Süresiz"}</dd>
          </div>
        </dl>
        {entry.description && <p>{entry.description}</p>}
        <p className="blacklist-meta">
          ACL grupları:{" "}
          {entry.group_ids
            .map((id) => groups.get(id))
            .filter(Boolean)
            .join(", ") || "—"}
        </p>
        <ErrorText>{error || preview.error}</ErrorText>
        {entry.devices.length > 0 ? (
          <ul
            className="blacklist-targets"
            tabIndex={0}
            aria-label="Cihaz durumları"
          >
            {entry.devices.map((device) => (
              <li key={device.device_id}>
                <div>
                  <strong>{device.name}</strong>
                  <small>
                    {device.desired ? "Engellenmeli" : "Kaldırılmalı"} · Cihazda{" "}
                    {device.applied === null
                      ? "belirsiz"
                      : device.applied
                        ? "uygulandı"
                        : "yok"}
                  </small>
                </div>
                <div>
                  {device.job ? (
                    <JobLine
                      job={device.job}
                      canWrite={canWrite}
                      pending={!!pending}
                      cancel={cancel}
                    />
                  ) : (
                    <small>
                      {device.applied
                        ? "Önceki doğrulama kaydı"
                        : "Henüz gönderim yok"}
                    </small>
                  )}
                </div>
                {device.job?.error && device.desired !== device.applied && (
                  <p className="blacklist-target-issue">{device.job.error}</p>
                )}
              </li>
            ))}
          </ul>
        ) : preview.loading ? (
          <p role="status">Hedefler yükleniyor…</p>
        ) : preview.data?.targets.length ? (
          <ul
            className="blacklist-targets"
            tabIndex={0}
            aria-label="Hedef cihazlar"
          >
            {preview.data.targets.map((target) => (
              <li
                key={`${target.device_id}/${target.profile ? aclLabel(target.profile) + target.profile.type : ""}`}
              >
                <div>
                  <strong>{target.name}</strong>
                  <small>
                    <span className="mono">{target.management_ip}</span> ·{" "}
                    {target.model}
                  </small>
                </div>
                <div>
                  <strong className="mono">
                    {target.profile
                      ? aclLabel(target.profile)
                      : "ACL bilgisi yok"}
                  </strong>
                  <small>Gönderildiğinde uygulanır</small>
                </div>
                {target.issue && (
                  <p className="blacklist-target-issue">{target.issue}</p>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="blacklist-empty">Bu kayıtta hedef cihaz bulunmuyor.</p>
        )}
        <Notice>
          Durdurma, sonraki komutları keser. Uygulanmış kurallar geçerli kalır;
          tekrar gönderim cihazı okuyarak eksik adımları tamamlar.
        </Notice>
      </div>
    </Dialog>
  );
}

function GroupDeleteDialog({
  group,
  close,
  done,
}: {
  group: Group;
  close: () => void;
  done: (message: string, skipped: Skipped[]) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result: ActionResult = await api(
        `${root}/groups/${group.id}`,
        "DELETE",
      );
      done(
        result.deleted
          ? "ACL grubu silindi."
          : `ACL grubu ${result.devices} cihazdan kaldırıldıktan sonra silinecek.`,
        result.skipped ?? [],
      );
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title="ACL grubunu sil" onClose={busy ? () => {} : close}>
      <form className="blacklist-preview" onSubmit={submit} aria-busy={busy}>
        <p>
          <strong>{group.name}</strong>{" "}
          {group.applied_devices
            ? `grubunun engelleri ${group.applied_devices} cihazdan kaldırılacak; doğrulandıktan sonra grup silinecek.`
            : "grubu hiçbir cihazda uygulanmamış. Grup hemen silinecek."}
        </p>
        <Notice>
          Cihaz başka bir etkin grupta da bulunuyorsa yalnız bu gruba ait IP’ler
          kaldırılır. Başka engel kalmazsa NETRIX ACL’si ve port bağlantıları
          silinir. IP kayıtları korunur.
        </Notice>
        <ErrorText>{error}</ErrorText>
        <FormActions
          busy={busy}
          disabled={false}
          close={close}
          label="Grubu sil"
          busyLabel="Siliniyor…"
          danger
        />
      </form>
    </Dialog>
  );
}

function ForgetDialog({
  device,
  close,
  done,
}: {
  device: DeviceState;
  close: () => void;
  done: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await api(`${root}/device-states/${device.device_id}`, "DELETE");
      done("Cihaz durumu unutuldu.");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title="Cihaz durumunu unut" onClose={busy ? () => {} : close}>
      <form className="blacklist-preview" onSubmit={submit} aria-busy={busy}>
        <p>
          <strong>{device.name}</strong> için kayıtlı NETRIX ACL durumu
          silinecek. Cihaza bağlanılmaz ve cihazdaki kurallar değişmez.
        </p>
        <Notice>
          Bu işlemi yalnız cihaz erişilemez durumdaysa veya ACL elle
          temizlendiyse kullanın. Silinmeyi bekleyen kayıtlar bu cihazı artık
          beklemez.
        </Notice>
        <ErrorText>{error}</ErrorText>
        <FormActions
          busy={busy}
          disabled={false}
          close={close}
          label="Durumu unut"
          busyLabel="Siliniyor…"
          danger
        />
      </form>
    </Dialog>
  );
}

function SelectAll({
  ids,
  selected,
  setSelected,
  label,
}: {
  ids: string[];
  selected: string[];
  setSelected: (ids: string[]) => void;
  label: string;
}) {
  const count = ids.filter((id) => selected.includes(id)).length;
  return (
    <input
      type="checkbox"
      aria-label={label}
      disabled={!ids.length}
      checked={!!ids.length && count === ids.length}
      ref={(element) => {
        if (element) element.indeterminate = count > 0 && count < ids.length;
      }}
      onChange={(event) =>
        setSelected(
          event.target.checked
            ? [...new Set([...selected, ...ids])]
            : selected.filter((id) => !ids.includes(id)),
        )
      }
    />
  );
}

function SelectionBar({
  count,
  noun,
  clear,
  children,
}: {
  count: number;
  noun: string;
  clear: () => void;
  children: React.ReactNode;
}) {
  if (!count) return null;
  return (
    <div
      className="blacklist-selection"
      role="region"
      aria-label="Seçim işlemleri"
    >
      <span role="status">
        {count} {noun} seçildi
      </span>
      <div className="blacklist-selection-actions">{children}</div>
      <button
        type="button"
        className="icon-button blacklist-selection-clear"
        onClick={clear}
        aria-label="Seçimi temizle"
        title="Seçimi temizle"
      >
        <X size={18} aria-hidden="true" />
      </button>
    </div>
  );
}

function EmptyState({ title, text }: { title: string; text: string }) {
  return (
    <div className="blacklist-empty">
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}

function usePolling(active: boolean, tick: () => void) {
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) tick();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [active]);
}

function Feedback({
  message,
  skipped,
  clear,
}: {
  message: string;
  skipped: Skipped[];
  clear: () => void;
}) {
  if (!message && !skipped.length) return null;
  return (
    <div className="blacklist-feedback">
      <div>
        {message && <p role="status">{message}</p>}
        <SkippedList items={skipped} />
      </div>
      <button
        type="button"
        className="icon-button"
        aria-label="Bildirimi kapat"
        title="Bildirimi kapat"
        onClick={clear}
      >
        <X size={18} aria-hidden="true" />
      </button>
    </div>
  );
}

function EntriesPage({
  canWrite,
  refresh,
}: {
  canWrite: boolean;
  refresh: number;
}) {
  const [revision, setRevision] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [editor, setEditor] = useState<{ entry?: Entry } | "bulk">();
  const [action, setAction] = useState<{ kind: EntryAction; ids: string[] }>();
  const [detail, setDetail] = useState("");
  const [feedback, setFeedback] = useState<{
    message: string;
    skipped: Skipped[];
  }>({
    message: "",
    skipped: [],
  });
  const reload = () => setRevision((value) => value + 1);
  const groups = useLiveQuery<{ items: Group[] }>(
    root + "/groups",
    refresh + revision,
  );
  const entries = useLiveQuery<{ items: Entry[] }>(
    root + "/entries",
    refresh + revision,
  );
  const items = entries.data?.items ?? [];
  const activeGroups = (groups.data?.items ?? []).filter(
    (group) => group.status === "active",
  );
  const groupNames = new Map(
    groups.data?.items.map((group) => [group.id, group.name]),
  );
  usePolling(
    items.some((entry) => entry.devices.some((device) => busyJob(device.job))),
    reload,
  );
  const visible = items.filter(
    (entry) =>
      (!filter || entry.state === filter) &&
      keyText(
        `${entry.address} ${entry.description} ${entry.group_ids
          .map((id) => groupNames.get(id))
          .join(" ")}`,
      ).includes(keyText(query.trim())),
  );
  const existing = new Set(items.map((entry) => entry.id));
  const chosen = selected.filter((id) => existing.has(id));
  const loading = groups.loading || entries.loading;
  const error = groups.error || entries.error;
  const detailEntry = items.find((entry) => entry.id === detail);
  const states = [...new Set(items.map((entry) => entry.state))];

  function finished(message: string, skipped: Skipped[] = []) {
    setEditor(undefined);
    setAction(undefined);
    setSelected([]);
    setFeedback({ message, skipped });
    reload();
  }

  return (
    <div className="blacklist-workspace">
      <section
        className="panel blacklist-panel"
        aria-label="Kayıtlı IP adresleri"
      >
        <div className="panel-header blacklist-toolbar">
          <div className="blacklist-filters">
            <label className="search-box">
              <MagnifyingGlass size={17} aria-hidden="true" />
              <input
                type="search"
                aria-label="IP kaydı ara"
                placeholder="IP, açıklama veya grup ara…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <select
              aria-label="Duruma göre filtrele"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="">Tüm durumlar</option>
              {states.map((value) => (
                <option value={value} key={value}>
                  {ENTRY_STATES[value]?.[0] ?? value}
                </option>
              ))}
            </select>
            <span className="blacklist-count">
              {visible.length === items.length
                ? `${items.length} IP kaydı`
                : `${visible.length} / ${items.length} IP kaydı`}
            </span>
          </div>
          {canWrite &&
            (activeGroups.length > 0 ? (
              <div className="blacklist-row-actions">
                <button className="secondary" onClick={() => setEditor("bulk")}>
                  <ListPlus size={18} aria-hidden="true" />
                  Toplu ekle
                </button>
                <button className="primary" onClick={() => setEditor({})}>
                  <Plus size={18} aria-hidden="true" />
                  Yeni IP
                </button>
              </div>
            ) : (
              !loading &&
              !error && (
                <a className="secondary" href="#blacklist-groups">
                  ACL gruplarını aç
                </a>
              )
            ))}
        </div>
        <Feedback
          {...feedback}
          clear={() => setFeedback({ message: "", skipped: [] })}
        />
        {canWrite && (
          <SelectionBar
            count={chosen.length}
            noun="kayıt"
            clear={() => setSelected([])}
          >
            <button
              className="primary"
              onClick={() => setAction({ kind: "send", ids: chosen })}
            >
              <PaperPlaneTilt size={16} aria-hidden="true" />
              Gönder
            </button>
            <button
              className="secondary"
              onClick={() => setAction({ kind: "remove", ids: chosen })}
            >
              <ArrowCounterClockwise size={16} aria-hidden="true" />
              Kaldır
            </button>
            <button
              className="secondary blacklist-danger"
              onClick={() => setAction({ kind: "delete", ids: chosen })}
            >
              <Trash size={16} aria-hidden="true" />
              Sil
            </button>
          </SelectionBar>
        )}
        <ErrorText>{error}</ErrorText>
        {loading && (
          <p className="blacklist-empty" role="status">
            Kayıtlar yükleniyor…
          </p>
        )}
        {!loading && !error && items.length === 0 && (
          <EmptyState
            title="Henüz IP kaydı yok"
            text={
              activeGroups.length
                ? "Bir IP adresi girip uygulanacağı grupları seçin."
                : "IP kaydı hazırlamak için önce bir ACL grubu oluşturun."
            }
          />
        )}
        {!loading && items.length > 0 && visible.length === 0 && (
          <EmptyState
            title="Sonuç bulunamadı"
            text="Aramayı veya durum filtresini değiştirin."
          />
        )}
        {visible.length > 0 && (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="IP kaydı tablosu"
          >
            <table>
              <thead>
                <tr>
                  {canWrite && (
                    <th scope="col" className="blacklist-check">
                      <SelectAll
                        ids={visible.map((entry) => entry.id)}
                        selected={selected}
                        setSelected={setSelected}
                        label="Görünen kayıtların tümünü seç"
                      />
                    </th>
                  )}
                  <th scope="col">IP adresi</th>
                  <th scope="col">ACL grupları</th>
                  <th scope="col">Durum</th>
                  <th scope="col">Son düzenleme</th>
                  <th scope="col">İşlemler</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((entry) => {
                  const running = entry.devices.some((device) =>
                    busyJob(device.job),
                  );
                  const applied = entry.devices.filter(
                    (device) => device.applied,
                  ).length;
                  return (
                    <tr key={entry.id}>
                      {canWrite && (
                        <td className="blacklist-check">
                          <input
                            type="checkbox"
                            aria-label={`${entry.address} kaydını seç`}
                            checked={selected.includes(entry.id)}
                            onChange={() =>
                              setSelected((ids) => toggle(ids, entry.id))
                            }
                          />
                        </td>
                      )}
                      <td>
                        <strong className="mono">{entry.address}</strong>
                        {entry.description && (
                          <small>{entry.description}</small>
                        )}
                        {entry.expires_at && entry.status === "active" && (
                          <small>Bitiş · {date(entry.expires_at)}</small>
                        )}
                      </td>
                      <td>
                        {entry.group_ids
                          .map((id) => groupNames.get(id))
                          .filter(Boolean)
                          .join(", ") || "—"}
                      </td>
                      <td>
                        <StateBadge map={ENTRY_STATES} value={entry.state} />
                        {entry.devices.length > 0 && (
                          <small>
                            {applied} / {entry.devices.length} cihazda uygulandı
                          </small>
                        )}
                      </td>
                      <td>{date(entry.updated_at)}</td>
                      <td>
                        <div className="blacklist-row-actions">
                          <button
                            className="secondary"
                            onClick={() => setDetail(entry.id)}
                            aria-label={`${entry.address} ayrıntısı`}
                          >
                            <Eye size={16} aria-hidden="true" />
                            Ayrıntı
                          </button>
                          {canWrite && (
                            <>
                              <button
                                className="primary"
                                onClick={() =>
                                  setAction({ kind: "send", ids: [entry.id] })
                                }
                                disabled={running}
                                aria-label={entry.address + " cihazlara gönder"}
                              >
                                <PaperPlaneTilt size={16} aria-hidden="true" />
                                Gönder
                              </button>
                              <button
                                className="icon-button"
                                onClick={() => setEditor({ entry })}
                                disabled={entry.status === "deleting"}
                                aria-label={`${entry.address} kaydını düzenle`}
                                title="Düzenle"
                              >
                                <PencilSimple size={18} aria-hidden="true" />
                              </button>
                              <button
                                className="icon-button"
                                onClick={() =>
                                  setAction({ kind: "remove", ids: [entry.id] })
                                }
                                disabled={
                                  running ||
                                  entry.state === "disabled" ||
                                  entry.state === "draft"
                                }
                                aria-label={`${entry.address} engelini kaldır`}
                                title="Engeli kaldır"
                              >
                                <ArrowCounterClockwise
                                  size={18}
                                  aria-hidden="true"
                                />
                              </button>
                              <button
                                className="icon-button delete-button"
                                onClick={() =>
                                  setAction({ kind: "delete", ids: [entry.id] })
                                }
                                disabled={running}
                                aria-label={`${entry.address} kaydını sil`}
                                title="Sil"
                              >
                                <Trash size={18} aria-hidden="true" />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {editor === "bulk" && (
        <BulkEditor
          groups={activeGroups}
          close={() => setEditor(undefined)}
          saved={(message) => finished(message)}
        />
      )}
      {editor && editor !== "bulk" && (
        <EntryEditor
          entry={editor.entry}
          groups={activeGroups}
          close={() => setEditor(undefined)}
          saved={() => finished("IP kaydı kaydedildi.")}
        />
      )}
      {action && (
        <EntryActionDialog
          action={action.kind}
          entries={items.filter((entry) => action.ids.includes(entry.id))}
          groups={activeGroups}
          close={() => setAction(undefined)}
          done={finished}
        />
      )}
      {detailEntry && (
        <EntryDetail
          entry={detailEntry}
          groups={groupNames}
          canWrite={canWrite}
          close={() => setDetail("")}
          refresh={reload}
        />
      )}
    </div>
  );
}

function GroupsPage({
  canEditGroups,
  canSync,
  refresh,
}: {
  canEditGroups: boolean;
  canSync: boolean;
  refresh: number;
}) {
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<{ group?: Group }>();
  const [removing, setRemoving] = useState<Group>();
  const [syncing, setSyncing] = useState("");
  const [feedback, setFeedback] = useState<{
    message: string;
    skipped: Skipped[];
  }>({
    message: "",
    skipped: [],
  });
  const [error, setError] = useState("");
  const reload = () => setRevision((value) => value + 1);
  const groups = useLiveQuery<{ items: Group[] }>(
    root + "/groups",
    refresh + revision,
  );
  const items = groups.data?.items ?? [];
  usePolling(
    items.some(
      (group) => group.status === "deleting" || group.pending_devices > 0,
    ),
    reload,
  );

  async function sync(group: Group) {
    setSyncing(group.id);
    setError("");
    try {
      const result: ActionResult = await api(
        `${root}/groups/${group.id}/sync`,
        "POST",
      );
      setFeedback({
        message: result.devices
          ? `${group.name} · ${result.devices} cihaz eşitleme kuyruğuna alındı.`
          : `${group.name} · eşitleme işi oluşturulamadı; aşağıdaki cihaz gerekçelerini kontrol edin.`,
        skipped: result.skipped ?? [],
      });
      reload();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setSyncing("");
    }
  }

  return (
    <div className="blacklist-workspace">
      <section
        className="panel blacklist-panel"
        aria-label="Kayıtlı ACL grupları"
      >
        <div className="panel-header blacklist-toolbar">
          <span className="blacklist-count">{items.length} grup</span>
          {canEditGroups && (
            <button className="primary" onClick={() => setEditor({})}>
              <Plus size={18} aria-hidden="true" />
              Yeni ACL grubu
            </button>
          )}
        </div>
        <Feedback
          {...feedback}
          clear={() => setFeedback({ message: "", skipped: [] })}
        />
        <ErrorText>{groups.error || error}</ErrorText>
        {groups.loading && (
          <p className="blacklist-empty" role="status">
            Gruplar yükleniyor…
          </p>
        )}
        {!groups.loading && !groups.error && items.length === 0 && (
          <EmptyState
            title="Henüz ACL grubu yok"
            text="Bir grup oluşturup cihazları ve hedef ACL bilgilerini seçin."
          />
        )}
        {items.length > 0 && (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="ACL grubu tablosu"
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">Grup</th>
                  <th scope="col">Hedef ACL’ler</th>
                  <th scope="col">Cihaz</th>
                  <th scope="col">Etkin IP</th>
                  <th scope="col">Durum</th>
                  {(canSync || canEditGroups) && <th scope="col">İşlemler</th>}
                </tr>
              </thead>
              <tbody>
                {items.map((group) => {
                  const deleting = group.status === "deleting";
                  return (
                    <tr key={group.id}>
                      <td>
                        <strong>{group.name}</strong>
                      </td>
                      <td>
                        <div className="blacklist-acls">
                          {Object.entries(group.profiles).map(
                            ([family, profile]) => (
                              <span className="mono" key={family}>
                                {aclLabel(profile)}
                              </span>
                            ),
                          )}
                        </div>
                      </td>
                      <td>
                        {group.device_ids.length}
                        {group.applied_devices > 0 && (
                          <small>
                            {group.applied_devices} cihazda uygulandı
                          </small>
                        )}
                      </td>
                      <td>{group.active_entries}</td>
                      <td>
                        {deleting ? (
                          <StateBadge map={ENTRY_STATES} value="deleting" />
                        ) : group.pending_devices ? (
                          <span className="badge pending">
                            <i />
                            {group.pending_devices} cihaz bekliyor
                          </span>
                        ) : (
                          <StateBadge
                            map={DEVICE_STATES}
                            value={group.applied_devices ? "synced" : "pending"}
                          />
                        )}
                      </td>
                      {(canSync || canEditGroups) && (
                        <td>
                          <div className="blacklist-row-actions">
                            {canSync && (
                              <button
                                className="secondary"
                                disabled={!!syncing || deleting}
                                onClick={() => sync(group)}
                                aria-label={`${group.name} grubunu cihazlarla eşitle`}
                              >
                                <ArrowsClockwise size={16} aria-hidden="true" />
                                {syncing === group.id
                                  ? "Kuyruğa alınıyor…"
                                  : "Eşitle"}
                              </button>
                            )}
                            {canEditGroups && (
                              <>
                                <button
                                  className="icon-button"
                                  onClick={() => setEditor({ group })}
                                  disabled={deleting}
                                  aria-label={`${group.name} grubunu düzenle`}
                                  title="Düzenle"
                                >
                                  <PencilSimple size={18} aria-hidden="true" />
                                </button>
                                <button
                                  className="icon-button delete-button"
                                  onClick={() => setRemoving(group)}
                                  aria-label={`${group.name} grubunu sil`}
                                  title="Sil"
                                >
                                  <Trash size={18} aria-hidden="true" />
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {editor && (
        <GroupEditor
          group={editor.group}
          close={() => setEditor(undefined)}
          saved={() => {
            setEditor(undefined);
            setFeedback({ message: "ACL grubu kaydedildi.", skipped: [] });
            reload();
          }}
        />
      )}
      {removing && (
        <GroupDeleteDialog
          group={removing}
          close={() => setRemoving(undefined)}
          done={(message, skipped) => {
            setRemoving(undefined);
            setFeedback({ message, skipped });
            reload();
          }}
        />
      )}
    </div>
  );
}

function DevicesPage({
  canWrite,
  canForget,
  refresh,
}: {
  canWrite: boolean;
  canForget: boolean;
  refresh: number;
}) {
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [forget, setForget] = useState<DeviceState>();
  const [detail, setDetail] = useState("");
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState<{
    message: string;
    skipped: Skipped[];
  }>({
    message: "",
    skipped: [],
  });
  const reload = () => setRevision((value) => value + 1);
  const devices = useLiveQuery<{ items: DeviceState[] }>(
    root + "/device-states",
    refresh + revision,
  );
  const items = devices.data?.items ?? [];
  const cancel = useCancel(reload);
  usePolling(
    items.some((device) => busyJob(device.job)),
    reload,
  );
  const visible = items.filter((device) =>
    keyText(
      `${device.name} ${device.management_ip} ${device.model} ${device.groups.join(" ")}`,
    ).includes(keyText(query.trim())),
  );
  const existing = new Set(items.map((device) => device.device_id));
  const chosen = selected.filter((id) => existing.has(id));
  const detailDevice = items.find((device) => device.device_id === detail);

  async function sync(ids: string[]) {
    setBusy(true);
    setError("");
    try {
      const result: ActionResult = await api(
        root + "/device-states/sync",
        "POST",
        {
          device_ids: ids,
        },
      );
      setSelected([]);
      setFeedback({
        message: result.devices
          ? `${result.devices} cihaz eşitleme kuyruğuna alındı.`
          : "Eşitlenecek cihaz yok.",
        skipped: result.skipped ?? [],
      });
      reload();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="blacklist-workspace">
      <section
        className="panel blacklist-panel"
        aria-label="Cihaz ACL durumları"
      >
        <div className="panel-header blacklist-toolbar">
          <div className="blacklist-filters">
            <label className="search-box">
              <MagnifyingGlass size={17} aria-hidden="true" />
              <input
                type="search"
                aria-label="Cihaz ara"
                placeholder="Cihaz, IP veya grup ara…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>
            <span className="blacklist-count">{items.length} cihaz</span>
          </div>
          {canWrite && (
            <button
              className="secondary"
              disabled={
                busy ||
                !items.some(
                  (device) =>
                    device.status === "pending" || device.status === "failed",
                )
              }
              onClick={() =>
                sync(
                  items
                    .filter((device) =>
                      ["pending", "failed"].includes(device.status),
                    )
                    .map((device) => device.device_id),
                )
              }
            >
              <ArrowsClockwise size={18} aria-hidden="true" />
              Bekleyenleri eşitle
            </button>
          )}
        </div>
        <Feedback
          {...feedback}
          clear={() => setFeedback({ message: "", skipped: [] })}
        />
        {canWrite && (
          <SelectionBar
            count={chosen.length}
            noun="cihaz"
            clear={() => setSelected([])}
          >
            <button
              className="primary"
              disabled={busy}
              onClick={() => sync(chosen)}
            >
              <ArrowsClockwise size={16} aria-hidden="true" />
              {busy ? "Kuyruğa alınıyor…" : "Seçilenleri eşitle"}
            </button>
          </SelectionBar>
        )}
        <ErrorText>{devices.error || error || cancel.error}</ErrorText>
        {devices.loading && (
          <p className="blacklist-empty" role="status">
            Cihazlar yükleniyor…
          </p>
        )}
        {!devices.loading && !devices.error && items.length === 0 && (
          <EmptyState
            title="Henüz cihaz yok"
            text="ACL grubuna eklenen cihazlar ve NETRIX ACL’si bulunan cihazlar burada listelenir."
          />
        )}
        {visible.length > 0 && (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Cihaz ACL durumu tablosu"
          >
            <table>
              <thead>
                <tr>
                  {canWrite && (
                    <th scope="col" className="blacklist-check">
                      <SelectAll
                        ids={visible.map((device) => device.device_id)}
                        selected={selected}
                        setSelected={setSelected}
                        label="Görünen cihazların tümünü seç"
                      />
                    </th>
                  )}
                  <th scope="col">Cihaz</th>
                  <th scope="col">İstenen</th>
                  <th scope="col">Cihazda</th>
                  <th scope="col">Durum</th>
                  <th scope="col">İşlemler</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((device) => (
                  <tr key={device.device_id}>
                    {canWrite && (
                      <td className="blacklist-check">
                        <input
                          type="checkbox"
                          aria-label={`${device.name} cihazını seç`}
                          checked={selected.includes(device.device_id)}
                          onChange={() =>
                            setSelected((ids) => toggle(ids, device.device_id))
                          }
                        />
                      </td>
                    )}
                    <td>
                      <strong>{device.name}</strong>
                      <small>
                        <span className="mono">{device.management_ip}</span>
                        {device.model && ` · ${device.model}`}
                      </small>
                      {device.groups.length > 0 && (
                        <small>{device.groups.join(", ")}</small>
                      )}
                    </td>
                    <td>
                      {device.will_remove_acl || !device.desired_acl ? (
                        <span>ACL kaldırılacak</span>
                      ) : (
                        <>
                          <strong className="mono">{device.desired_acl}</strong>
                          <small>{device.desired_count} IP</small>
                        </>
                      )}
                    </td>
                    <td>
                      {device.applied_acl ? (
                        <>
                          <strong className="mono">{device.applied_acl}</strong>
                          <small>
                            {device.applied_count} IP
                            {device.verified_at &&
                              ` · ${date(device.verified_at)}`}
                          </small>
                        </>
                      ) : (
                        <span>NETRIX ACL’si yok</span>
                      )}
                    </td>
                    <td>
                      <StateBadge map={DEVICE_STATES} value={device.status} />
                      {device.issue && <small>{device.issue}</small>}
                    </td>
                    <td>
                      <div className="blacklist-row-actions">
                        {canWrite && (
                          <button
                            className="secondary"
                            disabled={
                              busy || busyJob(device.job) || !!device.issue
                            }
                            onClick={() => sync([device.device_id])}
                            aria-label={`${device.name} cihazını eşitle`}
                          >
                            <ArrowsClockwise size={16} aria-hidden="true" />
                            Eşitle
                          </button>
                        )}
                        {device.job ? (
                          <button
                            className="icon-button"
                            onClick={() => setDetail(device.device_id)}
                            aria-label={`${device.name} son eşitleme işi`}
                            title="Son iş"
                          >
                            <Eye size={18} aria-hidden="true" />
                          </button>
                        ) : (
                          <span className="blacklist-slot" aria-hidden="true" />
                        )}
                        {canForget &&
                          (device.recorded ? (
                            <button
                              className="icon-button delete-button"
                              disabled={busyJob(device.job)}
                              onClick={() => setForget(device)}
                              aria-label={`${device.name} cihaz durumunu unut`}
                              title="Durumu unut"
                            >
                              <Trash size={18} aria-hidden="true" />
                            </button>
                          ) : (
                            <span
                              className="blacklist-slot"
                              aria-hidden="true"
                            />
                          ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {forget && (
        <ForgetDialog
          device={forget}
          close={() => setForget(undefined)}
          done={(message) => {
            setForget(undefined);
            setFeedback({ message, skipped: [] });
            reload();
          }}
        />
      )}
      {detailDevice?.job && (
        <Dialog title="Son eşitleme işi" onClose={() => setDetail("")}>
          <div className="blacklist-preview">
            <p>
              <strong>{detailDevice.name}</strong>
            </p>
            <div className="blacklist-job">
              <JobLine
                job={detailDevice.job}
                canWrite={canWrite}
                pending={!!cancel.pending}
                cancel={cancel.cancel}
              />
            </div>
            {detailDevice.job.added.length > 0 && (
              <p className="blacklist-meta">
                Eklenen:{" "}
                <span className="mono">
                  {detailDevice.job.added.join(", ")}
                </span>
              </p>
            )}
            {detailDevice.job.removed.length > 0 && (
              <p className="blacklist-meta">
                Kaldırılan:{" "}
                <span className="mono">
                  {detailDevice.job.removed.join(", ")}
                </span>
              </p>
            )}
            {detailDevice.job.error && (
              <p className="blacklist-target-issue">{detailDevice.job.error}</p>
            )}
          </div>
        </Dialog>
      )}
    </div>
  );
}

export default function BlacklistWorkspace({
  page,
  canEditGroups,
  canEditEntries,
  refresh,
}: {
  page: BlacklistPage;
  canEditGroups: boolean;
  canEditEntries: boolean;
  refresh: number;
}) {
  if (page === "groups")
    return (
      <GroupsPage
        canEditGroups={canEditGroups}
        canSync={canEditEntries}
        refresh={refresh}
      />
    );
  if (page === "devices")
    return (
      <DevicesPage
        canWrite={canEditEntries}
        canForget={canEditGroups}
        refresh={refresh}
      />
    );
  return <EntriesPage canWrite={canEditEntries} refresh={refresh} />;
}
