import React, { useEffect, useState } from "react";
import { api, useLiveQuery } from "./data";

type Row = Record<string, any>;
export type PlanStep = {
  group_id: string | null;
  image_id: string;
  device_ids?: string[];
};

export function UpdateState({ row }: { row: Row }) {
  const labels: Row = {
    current: "Güncel",
    outdated: "Güncel değil",
    unknown: "Sürüm karşılaştırılamıyor",
    no_image: "Uyumlu imaj yok",
  };
  return (
    <span className={`fw-state fw-update-${row.update_status}`}>
      {labels[row.update_status] || "Sürüm bekleniyor"}
    </span>
  );
}

function GroupDevices({
  group,
  q,
  refresh,
}: {
  group: Row;
  q: string;
  refresh: number;
}) {
  const [offset, setOffset] = useState(0);
  const query = new URLSearchParams({
    update_status: "outdated",
    q,
    offset: String(offset),
    limit: "50",
    ...(group.group_id
      ? { group_id: group.group_id }
      : { assignment: "available" }),
  });
  const result = useLiveQuery<Row>(`/firmware/devices?${query}`, refresh);
  return (
    <div className="fw-update-members">
      {result.loading && <p role="status">Cihazlar okunuyor…</p>}
      {result.error && (
        <p className="error" role="alert">
          {result.error}
        </p>
      )}
      <ul>
        {result.data?.items.map((device: Row) => (
          <li key={device.id}>
            <div>
              <b>{device.name}</b>
              <small>
                {device.management_ip} · {device.model}
              </small>
            </div>
            <div>
              <span className="mono">{device.software_version}</span>
              <small>Depodaki sürüm: {device.latest_version}</small>
            </div>
          </li>
        ))}
      </ul>
      {result.data?.total > 50 && (
        <div className="fw-row-actions">
          <span>
            {offset + 1}–{Math.min(offset + 50, result.data?.total || 0)} /{" "}
            {result.data?.total || 0} cihaz
          </span>
          <button
            className="secondary"
            disabled={!offset}
            onClick={() => setOffset(offset - 50)}
          >
            Önceki cihazlar
          </button>
          <button
            className="secondary"
            disabled={offset + 50 >= (result.data?.total || 0)}
            onClick={() => setOffset(offset + 50)}
          >
            Sonraki cihazlar
          </button>
        </div>
      )}
    </div>
  );
}

export default function OutdatedGroups({
  q,
  refresh,
  admin,
  onPlan,
}: {
  q: string;
  refresh: number;
  admin: boolean;
  onPlan: (steps: PlanStep[]) => void;
}) {
  const [expanded, setExpanded] = useState<string[]>([]);
  const [offset, setOffset] = useState(0),
    [selected, setSelected] = useState<string[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const result = useLiveQuery<Row>(
    `/firmware/outdated-groups?q=${encodeURIComponent(q)}&offset=${offset}`,
    refresh,
  );
  useEffect(() => {
    setOffset(0);
    setSelected([]);
  }, [q]);
  const groups: Row[] = result.data?.items || [];
  const toggle = (id: string) =>
    setSelected((old) =>
      old.includes(id) ? old.filter((value) => value !== id) : [...old, id],
    );
  return (
    <div className="fw-outdated-groups">
      <div className="fw-selection-actions">
        <p role="status">
          {selected.length} grup seçildi · {result.data?.total ?? "—"} grupta
          güncelleme gerekiyor
        </p>
        {admin && (
          <button
            className="primary"
            disabled={!selected.length || busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                const prepared = await api("/firmware/plans/prepare", "POST", {
                  group_ids: selected.filter((id) => id !== "ungrouped"),
                  include_ungrouped: selected.includes("ungrouped"),
                });
                onPlan(prepared.steps);
              } catch (e: any) {
                setError(e.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Hazırlanıyor…" : "Seçili grupları planla"}
          </button>
        )}
      </div>
      {(error || result.error) && (
        <p role="alert" className="error">
          {error || result.error}
        </p>
      )}
      {result.loading && <p role="status">Gruplar okunuyor…</p>}
      {!result.loading && !groups.length && (
        <p className="fw-empty">Güncelleme gereken cihaz bulunmuyor.</p>
      )}
      {groups.map((group) => (
        <section
          className="fw-update-group"
          key={group.id}
          aria-label={group.name}
        >
          <div className="fw-update-group-heading">
            {admin && (
              <label className="fw-check">
                <input
                  type="checkbox"
                  aria-label={`${group.name} grubunu seç`}
                  checked={selected.includes(group.id)}
                  onChange={() => toggle(group.id)}
                />
                <span>
                  <b>{group.name}</b>
                  <small>
                    {group.device_count} cihaz · Hedef:{" "}
                    {group.versions.join(", ")}
                  </small>
                </span>
              </label>
            )}
            {!admin && (
              <div>
                <b>{group.name}</b>
                <small>
                  {group.device_count} cihaz · Hedef:{" "}
                  {group.versions.join(", ")}
                </small>
              </div>
            )}
          </div>
          <details
            onToggle={(e) => {
              const open = e.currentTarget.open;
              setExpanded((ids) =>
                open
                  ? [...new Set([...ids, group.id])]
                  : ids.filter((id) => id !== group.id),
              );
            }}
          >
            <summary>Cihazları göster</summary>
            {expanded.includes(group.id) && (
              <GroupDevices group={group} q={q} refresh={refresh} />
            )}
          </details>
        </section>
      ))}
      {result.data?.total > 30 && (
        <div className="fw-row-actions">
          <span>
            {offset + 1}–{Math.min(offset + 30, result.data?.total || 0)} /{" "}
            {result.data?.total || 0} grup
          </span>
          <button
            className="secondary"
            disabled={!offset}
            onClick={() => setOffset(offset - 30)}
          >
            Önceki gruplar
          </button>
          <button
            className="secondary"
            disabled={offset + 30 >= (result.data?.total || 0)}
            onClick={() => setOffset(offset + 30)}
          >
            Sonraki gruplar
          </button>
        </div>
      )}
    </div>
  );
}
