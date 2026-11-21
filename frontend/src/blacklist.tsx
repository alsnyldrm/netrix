import {
  Eye,
  Info,
  MagnifyingGlass,
  PencilSimple,
  Plus,
} from "@phosphor-icons/react";
import { type FormEvent, useMemo, useState } from "react";
import { api, useLiveQuery } from "./data";
import { Dialog, date } from "./main";
import "./blacklist.css";

type Profile = { type: string; name: string | null; number: number | null };
type Group = {
  id: string;
  name: string;
  device_ids: string[];
  profiles: Record<string, Profile>;
};
type Entry = {
  id: string;
  address: string;
  description: string;
  group_ids: string[];
  updated_at: string;
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

const root = "/blacklist";
const keyText = (value: string) => value.toLocaleLowerCase("tr-TR");
const toggle = (ids: string[], id: string) =>
  ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id];
const aclLabel = (profile: Profile) =>
  [profile.name, profile.number === null ? null : `#${profile.number}`]
    .filter(Boolean)
    .join(" · ");

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div className="info-note blacklist-notice">
      <Info size={18} aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}

function FormActions({
  busy,
  disabled,
  close,
  label,
}: {
  busy: boolean;
  disabled: boolean;
  close: () => void;
  label: string;
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
      <button type="submit" className="primary" disabled={busy || disabled}>
        {busy ? "Kaydediliyor…" : label}
      </button>
    </div>
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
          address: values.get("address"),
          description: values.get("description"),
          group_ids: groupIds,
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
      title={entry ? "IP taslağını düzenle" : "Yeni IP taslağı"}
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
            autoComplete="off"
            spellCheck={false}
            placeholder="Örn. 192.0.2.10"
            className="mono"
          />
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
        <fieldset className="blacklist-fieldset">
          <legend>Hedef ACL grupları</legend>
          <div className="blacklist-checklist">
            {groups.map((group) => (
              <label key={group.id}>
                <input
                  type="checkbox"
                  checked={groupIds.includes(group.id)}
                  onChange={() => setGroupIds((ids) => toggle(ids, group.id))}
                />
                <span>{group.name}</span>
                <small>{group.device_ids.length} cihaz</small>
              </label>
            ))}
          </div>
        </fieldset>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <FormActions
          busy={busy}
          disabled={!groups.length}
          close={close}
          label="Taslağı kaydet"
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
          {inventory.error && (
            <p className="error" role="alert">
              {inventory.error}
            </p>
          )}
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
                      Bu ailenin SSH üzerinden ACL yazma desteği doğrulama
                      bekliyor.
                    </p>
                  )}
                </fieldset>
              );
            })}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
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

function EntryPreview({ id, close }: { id: string; close: () => void }) {
  const { data, loading, error } = useLiveQuery<Preview>(
    `${root}/entries/${id}/preview`,
  );
  const groups = new Map(data?.groups.map((group) => [group.id, group.name]));
  return (
    <Dialog title="Hedef önizlemesi" onClose={close} wide>
      <div className="blacklist-preview">
        {loading && <p role="status">Hedefler yükleniyor…</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {data && (
          <>
            <dl className="blacklist-preview-summary">
              <div>
                <dt>IP adresi</dt>
                <dd className="mono">{data.address}</dd>
              </div>
              <div>
                <dt>Kural</dt>
                <dd>Engelle (deny)</dd>
              </div>
              <div>
                <dt>Hedef cihaz</dt>
                <dd>
                  {new Set(data.targets.map((target) => target.device_id)).size}
                </dd>
              </div>
            </dl>
            {data.targets.length === 0 && (
              <p className="blacklist-empty">
                Bu taslakta hedef cihaz bulunmuyor.
              </p>
            )}
            {data.targets.length > 0 && (
              <ul
                className="blacklist-targets"
                tabIndex={0}
                aria-label="Hedef cihazlar"
              >
                {data.targets.map((target) => (
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
                      <small>
                        {target.group_ids
                          .map((groupId) => groups.get(groupId))
                          .join(", ")}
                      </small>
                    </div>
                    {target.issue && (
                      <p className="blacklist-target-issue">{target.issue}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <Notice>
              Bu önizleme kayıtlı envanterden hazırlanır. Cihazlara gönderim
              henüz etkin değil.
            </Notice>
          </>
        )}
      </div>
    </Dialog>
  );
}

export default function BlacklistWorkspace({
  groupsPage,
  canEditGroups,
  canEditEntries,
  refresh,
}: {
  groupsPage: boolean;
  canEditGroups: boolean;
  canEditEntries: boolean;
  refresh: number;
}) {
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<{ group?: Group; entry?: Entry }>();
  const [preview, setPreview] = useState("");
  const [status, setStatus] = useState("");
  const groups = useLiveQuery<{ items: Group[] }>(
    root + "/groups",
    refresh + revision,
  );
  const entries = useLiveQuery<{ items: Entry[] }>(
    groupsPage ? null : root + "/entries",
    refresh + revision,
  );
  const groupNames = new Map(
    groups.data?.items.map((group) => [group.id, group.name]),
  );
  const query = groupsPage ? groups : entries;
  const error = groups.error || query.error;
  const loading = groups.loading || query.loading;
  const saved = () => {
    setEditor(undefined);
    setRevision((value) => value + 1);
    setStatus(groupsPage ? "ACL grubu kaydedildi." : "IP taslağı kaydedildi.");
  };

  return (
    <div className="blacklist-workspace">
      <section
        className="panel blacklist-panel"
        aria-label={
          groupsPage ? "Kayıtlı ACL grupları" : "Kayıtlı IP taslakları"
        }
      >
        <div className="panel-header blacklist-toolbar">
          <span>
            {query.data?.items.length ?? 0} {groupsPage ? "grup" : "IP taslağı"}
          </span>
          {groupsPage
            ? canEditGroups && (
                <button className="primary" onClick={() => setEditor({})}>
                  <Plus size={18} aria-hidden="true" />
                  Yeni ACL grubu
                </button>
              )
            : canEditEntries &&
              (groupNames.size > 0 ? (
                <button className="primary" onClick={() => setEditor({})}>
                  <Plus size={18} aria-hidden="true" />
                  Yeni IP taslağı
                </button>
              ) : (
                !loading &&
                !error && (
                  <a className="secondary" href="#blacklist-groups">
                    ACL gruplarını aç
                  </a>
                )
              ))}
        </div>
        <span role="status" className="sr-only">
          {status}
        </span>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {loading && (
          <p className="blacklist-empty" role="status">
            Kayıtlar yükleniyor…
          </p>
        )}
        {!loading && !error && query.data?.items.length === 0 && (
          <div className="blacklist-empty">
            <strong>
              {groupsPage ? "Henüz ACL grubu yok" : "Henüz IP taslağı yok"}
            </strong>
            <p>
              {groupsPage
                ? "Bir grup oluşturup cihazları ve hedef ACL bilgilerini seçin."
                : groupNames.size
                  ? "Bir IP adresi girip uygulanacağı grupları seçin."
                  : "IP taslağı hazırlamak için önce bir ACL grubu oluşturun."}
            </p>
          </div>
        )}
        {groupsPage
          ? !!groups.data?.items.length && (
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
                      {canEditGroups && <th scope="col">İşlem</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {groups.data.items.map((group) => (
                      <tr key={group.id}>
                        <td>
                          <strong>{group.name}</strong>
                        </td>
                        <td>
                          <div className="blacklist-acls">
                            {Object.values(group.profiles).map(
                              (profile, index) => (
                                <span
                                  className="mono"
                                  key={Object.keys(group.profiles)[index]}
                                >
                                  {aclLabel(profile)}
                                </span>
                              ),
                            )}
                          </div>
                        </td>
                        <td>{group.device_ids.length}</td>
                        {canEditGroups && (
                          <td>
                            <button
                              className="secondary"
                              onClick={() => setEditor({ group })}
                              aria-label={`${group.name} grubunu düzenle`}
                            >
                              <PencilSimple size={16} aria-hidden="true" />
                              Düzenle
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          : !!entries.data?.items.length && (
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="IP taslağı tablosu"
              >
                <table>
                  <thead>
                    <tr>
                      <th scope="col">IP adresi</th>
                      <th scope="col">ACL grupları</th>
                      <th scope="col">Durum</th>
                      <th scope="col">Son düzenleme</th>
                      <th scope="col">İşlemler</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.data.items.map((entry) => (
                      <tr key={entry.id}>
                        <td>
                          <strong className="mono">{entry.address}</strong>
                          {entry.description && (
                            <small>{entry.description}</small>
                          )}
                        </td>
                        <td>
                          {entry.group_ids
                            .map((id) => groupNames.get(id))
                            .filter(Boolean)
                            .join(", ") || "—"}
                        </td>
                        <td>
                          <span className="blacklist-draft">Taslak</span>
                        </td>
                        <td>{date(entry.updated_at)}</td>
                        <td>
                          <div className="blacklist-row-actions">
                            <button
                              className="secondary"
                              onClick={() => setPreview(entry.id)}
                              aria-label={`${entry.address} hedeflerini önizle`}
                            >
                              <Eye size={16} aria-hidden="true" />
                              Önizle
                            </button>
                            {canEditEntries && (
                              <button
                                className="secondary"
                                onClick={() => setEditor({ entry })}
                                aria-label={`${entry.address} taslağını düzenle`}
                              >
                                <PencilSimple size={16} aria-hidden="true" />
                                Düzenle
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
      </section>
      {editor &&
        (groupsPage ? (
          <GroupEditor
            group={editor.group}
            close={() => setEditor(undefined)}
            saved={saved}
          />
        ) : (
          <EntryEditor
            entry={editor.entry}
            groups={groups.data?.items ?? []}
            close={() => setEditor(undefined)}
            saved={saved}
          />
        ))}
      {preview && <EntryPreview id={preview} close={() => setPreview("")} />}
    </div>
  );
}
