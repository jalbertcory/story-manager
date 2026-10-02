import { afterEach, describe, expect, it } from "vitest";
import {
  applyThemePreference,
  readThemePreference,
  saveThemePreference,
} from "./theme";

describe("theme preference", () => {
  afterEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("follows the system theme until a reader picks one", () => {
    expect(readThemePreference()).toBe("system");
    saveThemePreference("light");
    expect(readThemePreference()).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    saveThemePreference("system");
    expect(readThemePreference()).toBe("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("ignores unknown stored values", () => {
    localStorage.setItem("story-manager.theme.v1", "sepia");
    expect(readThemePreference()).toBe("system");
    applyThemePreference(readThemePreference());
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });
});
