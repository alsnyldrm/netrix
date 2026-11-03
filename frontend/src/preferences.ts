import { applyApplicationFont } from "./application-fonts";
import type { ApplicationFont } from "./application-fonts";

export type TerminalAppearance = {
  font: "ubuntu" | "plex" | "system";
  font_size: number;
  font_weight: 400 | 700;
  background: string;
  commands_width: number;
  commands_collapsed: boolean;
};
export const defaultTerminalAppearance: TerminalAppearance = {
  font: "ubuntu",
  font_size: 15,
  font_weight: 400,
  background: "#300a24",
  commands_width: 300,
  commands_collapsed: false,
};
export type Preferences = {
  ui_font: ApplicationFont;
  palette: string;
  design: string;
  timezone: string;
  locale: string;
  hour12: boolean;
  features: string[];
  terminal: TerminalAppearance;
};
export const defaultPreferences: Preferences = {
  ui_font: "theme",
  palette: "cobalt",
  design: "atlas",
  timezone: "Europe/Istanbul",
  locale: "tr-TR",
  hour12: false,
  features: ["saved_commands", "session_dock"],
  terminal: defaultTerminalAppearance,
};
let active = defaultPreferences;
export function applyPreferences(value: Preferences) {
  value = { ...defaultPreferences, ...value };
  value.terminal = { ...defaultTerminalAppearance, ...value.terminal };
  active = value;
  const root = document.documentElement;
  applyApplicationFont(value.ui_font);
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
