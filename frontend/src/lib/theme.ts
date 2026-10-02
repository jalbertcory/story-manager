export type ThemePreference = "system" | "light" | "dark";

const STORAGE_KEY = "story-manager.theme.v1";
export const THEME_PREFERENCES: readonly ThemePreference[] = [
  "system",
  "light",
  "dark",
];

export function readThemePreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return THEME_PREFERENCES.find((theme) => theme === stored) ?? "system";
  } catch {
    return "system";
  }
}

// "system" removes the attribute so the prefers-color-scheme rules apply.
export function applyThemePreference(theme: ThemePreference) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}

export function saveThemePreference(theme: ThemePreference) {
  applyThemePreference(theme);
  try {
    if (theme === "system") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // The choice still applies for this visit when storage is unavailable.
  }
}
