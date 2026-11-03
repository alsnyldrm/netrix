export type Preferences = {
  palette: string;
  design: string;
  timezone: string;
  locale: string;
  hour12: boolean;
  features: string[];
};
export const defaultPreferences: Preferences = {
  palette: "cobalt",
  design: "atlas",
  timezone: "Europe/Istanbul",
  locale: "tr-TR",
  hour12: false,
  features: ["saved_commands", "session_dock"],
};
let active = defaultPreferences;
export function applyPreferences(value: Preferences) {
  value = { ...defaultPreferences, ...value };
  active = value;
  const root = document.documentElement;
  root.dataset.palette = value.palette;
  root.dataset.design = value.design;
  root.dataset.compact = String(value.features.includes("compact_tables"));
  root.dataset.reduceMotion = String(value.features.includes("reduced_motion"));
  window.dispatchEvent(
    new CustomEvent("netrix:preferences", { detail: value }),
  );
}
export function currentPreferences() {
  return active;
}
export function formatDate(value: any, full = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(active.locale, {
    timeZone: active.timezone,
    day: "2-digit",
    month: "short",
    ...(full
      ? { year: "numeric", weekday: "long" }
      : { hour: "2-digit", minute: "2-digit", hour12: active.hour12 }),
  }).format(date);
}
