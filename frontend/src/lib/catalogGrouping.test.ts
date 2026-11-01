import { describe, expect, it } from "vitest";

import type { CatalogBook } from "../types";
import { buildCatalogGroups } from "./catalogGrouping";

const catalogBook = (
  overrides: Partial<CatalogBook> & Pick<CatalogBook, "id" | "title">,
): CatalogBook => ({
  audio_playable: false,
  audiobook_enabled: false,
  audiobook_pipeline_status: null,
  audiobook_types: [],
  author: "Author",
  cover_path: null,
  current_word_count: null,
  download_status: null,
  effective_genre_tags: null,
  effective_series_genre_tags: null,
  genre_tags: null,
  has_epub: true,
  refresh_status: null,
  series: null,
  series_index: null,
  series_user_genre_tags: null,
  source_type: "epub",
  source_url: null,
  universe_id: null,
  universe_name: null,
  updated_at: null,
  user_genre_tags: null,
  ...overrides,
});

describe("buildCatalogGroups", () => {
  it("keeps audiobook-enabled series and standalone books first", () => {
    const books = [
      catalogBook({
        id: 1,
        title: "Alpha Text",
        author: "Author",
        series: "Alpha Series",
        source_type: "epub",
        audiobook_enabled: false,
      }),
      catalogBook({
        id: 2,
        title: "Zeta Audio",
        author: "Author",
        series: "Zeta Series",
        source_type: "epub",
        audiobook_enabled: true,
      }),
      catalogBook({
        id: 3,
        title: "Alpha Standalone",
        author: "Author",
        series: null,
        source_type: "epub",
        audiobook_enabled: false,
      }),
      catalogBook({
        id: 4,
        title: "Zeta Standalone",
        author: "Author",
        series: null,
        source_type: "epub",
        audiobook_enabled: true,
      }),
    ];

    const grouped = buildCatalogGroups(books, "audiobook_enabled", "desc");

    expect(grouped.sortedSeries).toEqual(["Zeta Series", "Alpha Series"]);
    expect(grouped.standaloneBooks.map((book) => book.id)).toEqual([4, 3]);
  });
});
