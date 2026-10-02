export type ThemePreference = "system" | "light" | "dark";

const STORAGE_KEY = "story-manager-theme";

function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

export function readThemePreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isThemePreference(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

// "system" removes the attribute so the prefers-color-scheme media query in
// index.css decides; an explicit choice pins the palette via data-theme.
export function applyThemePreference(theme: ThemePreference) {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
}

export function saveThemePreference(theme: ThemePreference) {
  applyThemePreference(theme);
  try {
    if (theme === "system") window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Storage can be unavailable (private mode); the choice still applies
    // for this page view.
  }
}

const NEXT_THEME: Record<ThemePreference, ThemePreference> = {
  system: "light",
  light: "dark",
  dark: "system",
};

export function nextThemePreference(theme: ThemePreference): ThemePreference {
  return NEXT_THEME[theme];
}
