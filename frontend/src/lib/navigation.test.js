import { describe, expect, it } from "vitest";

import { buildBookPath, parseLocation } from "./navigation";

describe("book navigation", () => {
  it("parses the Needs Attention dashboard route", () => {
    expect(parseLocation("/attention", "", "")).toEqual({
      view: "tab",
      tab: "attention",
      libraryView: "series",
    });
  });

  it("parses canonical book sections and audiobook tabs", () => {
    expect(
      parseLocation(
        "/books/12/audiobooks",
        "",
        "?tab=chapter-assembly",
      ),
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
