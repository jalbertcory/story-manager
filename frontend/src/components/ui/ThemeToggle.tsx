import { useState } from "react";
import Icon from "./Icon";
import {
  readThemePreference,
  saveThemePreference,
  THEME_PREFERENCES,
  type ThemePreference,
} from "../../lib/theme";

const LABELS: Record<ThemePreference, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};
const ICONS = { system: "monitor", light: "sun", dark: "moon" } as const;

export default function ThemeToggle() {
  const [theme, setTheme] = useState(readThemePreference);
  return (
    <div className="theme-toggle" role="group" aria-label="Color theme">
      {THEME_PREFERENCES.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={theme === option}
          title={`${LABELS[option]} theme`}
          onClick={() => {
            saveThemePreference(option);
            setTheme(option);
          }}
        >
          <Icon name={ICONS[option]} size={15} />
          <span className="visually-hidden">{LABELS[option]} theme</span>
        </button>
      ))}
    </div>
  );
}
