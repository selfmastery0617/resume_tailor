/** Broad document-font catalog. Browser/PDF rendering uses an installed font
 * when available and a category-safe fallback otherwise. */
export const APPROVED_FONTS = [
  "Template default",
  "Arial",
  "Arial Black",
  "Arial Narrow",
  "Book Antiqua",
  "Calibri",
  "Cambria",
  "Candara",
  "Century Gothic",
  "Comic Sans MS",
  "Consolas",
  "Courier New",
  "Garamond",
  "Georgia",
  "Helvetica",
  "Impact",
  "Lucida Console",
  "Lucida Sans Unicode",
  "Palatino Linotype",
  "Segoe UI",
  "System UI",
  "Tahoma",
  "Times New Roman",
  "Trebuchet MS",
  "Verdana",
  "Alegreya",
  "Bitter",
  "Cabin",
  "Comfortaa",
  "Crimson Text",
  "EB Garamond",
  "Fira Sans",
  "IBM Plex Sans",
  "Inconsolata",
  "Inter",
  "Lato",
  "Lexend",
  "Libre Baskerville",
  "Libre Franklin",
  "Merriweather",
  "Montserrat",
  "Noto Sans",
  "Noto Serif",
  "Open Sans",
  "Oswald",
  "Playfair Display",
  "Poppins",
  "PT Sans",
  "PT Serif",
  "Raleway",
  "Roboto",
  "Roboto Condensed",
  "Roboto Mono",
  "Source Sans 3",
  "Source Serif 4",
  "Ubuntu",
  "Work Sans",
] as const;

const SERIF_FONTS = new Set([
  "Book Antiqua",
  "Cambria",
  "Garamond",
  "Georgia",
  "Palatino Linotype",
  "Times New Roman",
  "Alegreya",
  "Bitter",
  "Crimson Text",
  "EB Garamond",
  "Libre Baskerville",
  "Merriweather",
  "Noto Serif",
  "Playfair Display",
  "PT Serif",
  "Source Serif 4",
]);

const MONO_FONTS = new Set([
  "Consolas",
  "Courier New",
  "Inconsolata",
  "Lucida Console",
  "Roboto Mono",
]);

export function fontStack(fontFamily: string): string {
  if (fontFamily === "Template default") return 'Georgia, "Times New Roman", serif';
  if (fontFamily === "System UI") return 'system-ui, "Segoe UI", Arial, sans-serif';
  const escaped = fontFamily.replaceAll('"', "");
  if (SERIF_FONTS.has(fontFamily)) return `"${escaped}", Georgia, "Times New Roman", serif`;
  if (MONO_FONTS.has(fontFamily)) return `"${escaped}", Consolas, "Courier New", monospace`;
  return `"${escaped}", Arial, "Segoe UI", sans-serif`;
}
