import { describe, expect, it } from "vitest";

import {
  buildBookPath,
  buildTabPath,
  getPrimarySection,
  parseLocation,
  parseNavigationState,
  PRIMARY_NAV,
} from "./navigation";

describe("application navigation", () => {
  it("exposes the daily workflows and secondary destinations", () => {
    expect(
      PRIMARY_NAV.map(({ key, label, path }) => ({ key, label, path })),
    ).toEqual([
      { key: "library", label: "Library", path: "/" },
      { key: "updates", label: "Web updates", path: "/updates" },
      { key: "review", label: "Review suggestions", path: "/review" },
      { key: "activity", label: "Background activity", path: "/activity" },
      { key: "settings", label: "Settings", path: "/settings" },
    ]);
  });

  it("uses Needs Attention as the Activity overview", () => {
    expect(parseLocation("/activity", "", "")).toEqual({
      view: "tab",
      tab: "attention",
      libraryView: "series",
    });
    expect(getPrimarySection("attention")).toBe("activity");
    expect(buildTabPath("attention")).toBe("/activity");
  });

  it("keeps the guided import workflow inside the Library section", () => {
    expect(parseLocation("/import", "", "?type=audiobook")).toEqual({
      view: "tab",
      tab: "import",
      libraryView: "series",
    });
    expect(getPrimarySection("import")).toBe("library");
    expect(buildTabPath("import")).toBe("/import");
  });

  it.each([
    ["/attention", "attention", "/activity"],
    ["/processing", "processing", "/activity/processing"],
    ["/scheduler", "scheduler", "/activity/scheduled-runs"],
    ["/configs", "configs", "/settings/cleaning"],
    ["/audio-settings", "audio-settings", "/settings/audio-ai"],
    ["/utilities", "utilities", "/settings/library-tools"],
    ["/logs", "logs", "/settings/logs"],
  ])("keeps legacy route %s working", (legacyPath, tab, redirectPath) => {
    expect(parseLocation(legacyPath, "", "?section=metadata")).toMatchObject({
      view: "tab",
      tab,
      redirectPath,
    });
  });

  it("parses canonical book sections and audiobook tabs", () => {
    expect(
      parseLocation("/books/12/audiobooks", "", "?tab=chapter-assembly"),
    ).toEqual({
      view: "book",
      bookId: 12,
      bookSection: "audiobooks",
      audiobookTab: "chapter-assembly",
    });
  });

  it("keeps legacy book URLs working as details URLs", () => {
    expect(parseLocation("/books/12", "", "")).toMatchObject({
      view: "book",
      bookId: 12,
      bookSection: "details",
      legacyBookPath: true,
    });
  });

  it("builds stable canonical URLs and rejects unknown tabs", () => {
    expect(buildBookPath(12, "details")).toBe("/books/12/details");
    expect(buildBookPath(12, "audiobooks", "listen-read")).toBe(
      "/books/12/audiobooks?tab=listen-read",
    );
    expect(buildBookPath(12, "audiobooks", "unknown")).toBe(
      "/books/12/audiobooks?tab=sources",
    );
  });
});

describe("browser navigation state", () => {
  it("preserves valid routes and scroll positions", () => {
    expect(
      parseNavigationState({
        returnTo: "/?series=Saga",
        scrollY: 0,
        libraryScrollY: 320,
      }),
    ).toEqual({
      returnTo: "/?series=Saga",
      scrollY: 0,
      libraryScrollY: 320,
    });
  });
  it.each([
    null,
    false,
    "bad",
    { returnTo: 42, scrollY: "20", libraryScrollY: -1 },
    { returnTo: "//example.com", scrollY: Infinity, libraryScrollY: NaN },
  ])("ignores malformed state %j", (state) => {
    expect(parseNavigationState(state)).toEqual({});
  });
});
