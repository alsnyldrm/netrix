type Row = Record<string, any>;
type Refs = Record<string, Row[]>;

export const roomChoiceLabel = (room: Row) =>
  `${room.floor_number || "—"}/${room.department_name || "—"}/${room.name}`;

export function cabinetChoices(refs: Refs, values: Row) {
  const sites = new Map((refs.sites || []).map((r) => [r.id, r]));
  return (refs.cabinets || [])
    .filter(
      (r) =>
        (!values.site_id || r.site_id === values.site_id) &&
        (!values.sub_site_id || r.sub_site_id === values.sub_site_id) &&
        (!values.institution_id ||
          sites.get(r.site_id)?.institution_id === values.institution_id),
    )
    .map((r) => ({
      value: r.id as string,
      label: `${sites.get(r.site_id)?.name || "—"} / ${roomChoiceLabel(sites.get(r.sub_site_id) || { name: "—" })} / Kabin ${r.name}`,
    }));
}

export function selectedCabinet(refs: Refs, values: Row) {
  const allowed = new Set(
    cabinetChoices(refs, values).map((choice) => choice.value),
  );
  const candidates = (refs.cabinets || []).filter(
    (r) => r.name === values.cabinet && allowed.has(r.id),
  );
  // Legacy notes can be ambiguous; never choose an arbitrary room's cabinet.
  return candidates.length === 1 ? candidates[0].id : "";
}

export function chooseCabinet(refs: Refs, values: Row, id: string) {
  const cabinet = (refs.cabinets || []).find((r) => r.id === id);
  if (!cabinet) return { ...values, cabinet: "" };
  const site = (refs.sites || []).find((r) => r.id === cabinet.site_id);
  return {
    ...values,
    cabinet: cabinet.name,
    institution_id: site?.institution_id || "",
    site_id: cabinet.site_id,
    sub_site_id: cabinet.sub_site_id || "",
    location: "",
  };
}
