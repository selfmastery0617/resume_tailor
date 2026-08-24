import { useEffect, useState } from "react";

export type ThemeChoice = "system" | "light" | "dark";

const STORAGE_KEY = "jobtailor-theme";

/** Dark-grey is the intended default; "system" is opt-in. */
const DEFAULT_CHOICE: ThemeChoice = "dark";

function readStoredTheme(): ThemeChoice {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark" || stored === "system") return stored;
  return DEFAULT_CHOICE;
}

/** Applies the choice to <html>. "system" removes the attribute so the
 *  prefers-color-scheme media query takes over again. */
export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

/** Read and apply the saved theme before first paint (called from main.tsx). */
export function initTheme(): void {
  applyTheme(readStoredTheme());
}

/** The theme actually in effect right now — resolves "system" against the OS
 *  and tracks changes. Needed by components that can't use CSS variables,
 *  such as the AG Grid theme object. */
export function useResolvedTheme(): "light" | "dark" {
  const resolve = (): "light" | "dark" => {
    const attr = document.documentElement.getAttribute("data-theme");
    if (attr === "dark" || attr === "light") return attr;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  };

  const [resolved, setResolved] = useState<"light" | "dark">(resolve);

  useEffect(() => {
    const update = () => setResolved(resolve());

    // The attribute changes when the user toggles…
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    // …and the OS preference can change while "system" is selected.
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);

    return () => {
      observer.disconnect();
      media.removeEventListener("change", update);
    };
  }, []);

  return resolved;
}

const ORDER: ThemeChoice[] = ["dark", "light", "system"];
const LABEL: Record<ThemeChoice, string> = {
  dark: "Dark",
  light: "Light",
  system: "System",
};
const ICON: Record<ThemeChoice, string> = {
  dark: "🌙",
  light: "☀️",
  system: "🖥️",
};

export function ThemeToggle() {
  const [choice, setChoice] = useState<ThemeChoice>(readStoredTheme);

  useEffect(() => {
    applyTheme(choice);
    localStorage.setItem(STORAGE_KEY, choice);
  }, [choice]);

  const next = () => setChoice((prev) => ORDER[(ORDER.indexOf(prev) + 1) % ORDER.length]);

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={next}
      // Label carries the state, so it isn't communicated by colour alone.
      aria-label={`Theme: ${choice}. Click to change.`}
      title="Switch between dark, light and system"
    >
      <span aria-hidden="true">{ICON[choice]}</span>
      <span>{LABEL[choice]}</span>
    </button>
  );
}
