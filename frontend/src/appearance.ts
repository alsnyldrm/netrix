export const darkPaletteId = "dark";
export const colorPalettes = [
  { id: "cobalt", name: "Lumelle", hue: 343, saturation: 100 },
  { id: "teal", name: "Atlantik", hue: 174, saturation: 76 },
  { id: "violet", name: "Ametist", hue: 270, saturation: 72 },
  { id: "amber", name: "Sarı kehribar", hue: 45, saturation: 94 },
  { id: "forest", name: "Orman", hue: 143, saturation: 66 },
  { id: "slate", name: "Grafit", hue: 215, saturation: 18 },
  { id: "rose", name: "Yakut", hue: 342, saturation: 76 },
  { id: "cyan", name: "Buzul", hue: 193, saturation: 88 },
  { id: "orange", name: "Bakır", hue: 25, saturation: 88 },
  { id: "indigo", name: "Gece irisi", hue: 244, saturation: 70 },
  {
    id: darkPaletteId,
    name: "Karanlık",
    tones: ["#ededed", "#bdbdbd", "#747474", "#212121", "#101010"],
  },
] as const;
