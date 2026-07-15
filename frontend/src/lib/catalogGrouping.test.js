import { describe, expect, it } from "vitest";

import { buildCatalogGroups } from "./catalogGrouping";

describe("buildCatalogGroups", () => {
  it("keeps audiobook-enabled series and standalone books first", () => {
    const books = [
      {
        id: 1,
        title: "Alpha Text",
        author: "Author",
        series: "Alpha Series",
        source_type: "epub",
        audiobook_enabled: false,
      },
      {
        id: 2,
        title: "Zeta Audio",
        author: "Author",
        series: "Zeta Series",
        source_type: "epub",
        audiobook_enabled: true,
      },
      {
        id: 3,
        title: "Alpha Standalone",
        author: "Author",
        series: null,
        source_type: "epub",
        audiobook_enabled: false,
      },
      {
        id: 4,
        title: "Zeta Standalone",
        author: "Author",
        series: null,
        source_type: "epub",
        audiobook_enabled: true,
      },
    ];

    const grouped = buildCatalogGroups(books, "audiobook_enabled", "desc");

    expect(grouped.sortedSeries).toEqual(["Zeta Series", "Alpha Series"]);
    expect(grouped.standaloneBooks.map((book) => book.id)).toEqual([4, 3]);
  });
});
