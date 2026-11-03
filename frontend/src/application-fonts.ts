import "./application-fonts.css";

export const applicationFonts = [
  { id: "ibm-plex-sans", name: "IBM Plex Sans", family: "IBM Plex Sans" },
  { id: "inter", name: "Inter", family: "Inter Variable" },
  {
    id: "source-sans-3",
    name: "Source Sans 3",
    family: "Source Sans 3 Variable",
  },
  { id: "roboto", name: "Roboto", family: "Roboto Variable" },
  { id: "open-sans", name: "Open Sans", family: "Open Sans Variable" },
  { id: "noto-sans", name: "Noto Sans", family: "Noto Sans Variable" },
  { id: "fira-sans", name: "Fira Sans", family: "Fira Sans" },
  { id: "work-sans", name: "Work Sans", family: "Work Sans Variable" },
  { id: "public-sans", name: "Public Sans", family: "Public Sans Variable" },
  { id: "manrope", name: "Manrope", family: "Manrope Variable" },
  { id: "dm-sans", name: "DM Sans", family: "DM Sans Variable" },
  {
    id: "plus-jakarta-sans",
    name: "Plus Jakarta Sans",
    family: "Plus Jakarta Sans Variable",
  },
  {
    id: "libre-franklin",
    name: "Libre Franklin",
    family: "Libre Franklin Variable",
  },
  { id: "nunito-sans", name: "Nunito Sans", family: "Nunito Sans Variable" },
  { id: "lexend", name: "Lexend", family: "Lexend Variable" },
] as const;

export type ApplicationFont = "theme" | (typeof applicationFonts)[number]["id"];

export function applyApplicationFont(id: ApplicationFont) {
  const font = applicationFonts.find((font) => font.id === id);
  const root = document.documentElement;
  root.dataset.uiFont = font ? font.id : "theme";
  if (font) {
    root.style.setProperty(
      "--font-sans",
      `"${font.family}", system-ui, sans-serif`,
    );
  } else {
    root.style.removeProperty("--font-sans");
  }
}
