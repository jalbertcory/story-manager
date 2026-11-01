import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { components } from "../api/schema";
import type { CatalogBook } from "../types";
import { jsonResponse, renderWithClient } from "../test-utils";
import type { FixtureFetch } from "../test-utils";
import LibraryWorkspace from "./LibraryWorkspace";

type LibraryGroup = components["schemas"]["LibraryGroup"];
type CatalogFacets = components["schemas"]["CatalogFacets"];

const response = (value: unknown) => Promise.resolve(jsonResponse(value));
const stubFetch = (implementation: FixtureFetch) => {
  const fetch = vi.fn<FixtureFetch>(implementation);
  vi.stubGlobal("fetch", fetch);
  return fetch;
};
const facets = (overrides: Partial<CatalogFacets> = {}): CatalogFacets => ({
  audiobook_available: 0,
  audiobook_missing: 0,
  genres: [],
  missing_series: 0,
  refresh_attention: 0,
  refreshing: 0,
  series: 0,
  standalone: 0,
  web: 0,
  ...overrides,
});
const catalogBook = (
  overrides: Partial<CatalogBook> & Pick<CatalogBook, "id" | "title">,
): CatalogBook => ({
  audio_playable: false,
  audiobook_enabled: false,
  audiobook_pipeline_status: null,
  audiobook_types: [],
  author: "Writer",
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
const libraryGroup = (
  overrides: Partial<LibraryGroup> & Pick<LibraryGroup, "name">,
): LibraryGroup => ({
  audio_count: 0,
  author: null,
  author_count: 1,
  book_count: 1,
  cover_ids: [],
  universe_id: null,
  ...overrides,
});
const page = (items: CatalogBook[]) =>
  ({
    items,
    next_cursor: null,
    total_count: items.length,
    facets: facets({ series: 1 }),
  }) satisfies components["schemas"]["BookCatalogPage"];
const missing = catalogBook({
  id: 948,
  title: "Artemis Fowl",
  author: "Eoin Colfer",
  series: "Artemis Fowl",
  source_type: "audiobook",
  has_epub: false,
});
afterEach(() => vi.unstubAllGlobals());

describe("Audio-only library", () => {
  it("keeps the missing EPUB filter when opening a series and returning from a book", async () => {
    const fetch = stubFetch((url) => {
      if (url.startsWith("/api/library/groups"))
        return response({
          items: [
            libraryGroup({
              name: "Artemis Fowl",
              audio_count: 1,
              author: "Eoin Colfer",
            }),
          ],
          next_cursor: null,
          total_count: 1,
          facets: null,
        } satisfies components["schemas"]["LibraryGroupsPage"]);
      if (url.startsWith("/api/books/catalog"))
        return response(page([missing]));
      return response([]);
    });
    const onEdit = vi.fn();
    const onNavigate = vi.fn();
    const renderPage = (search: string) => (
      <LibraryWorkspace
        search={search}
        hash=""
        onEdit={onEdit}
        onNavigate={onNavigate}
      />
    );
    const { rerender } = renderWithClient(
      renderPage("?group=series&source=audiobook"),
    );
    expect(screen.getByLabelText("Library source")).toHaveValue("audiobook");
    const seriesLink = await screen.findByRole("link", {
      name: /Artemis Fowl/,
    });
    expect(seriesLink).toHaveAttribute(
      "href",
      "/?group=series&series=Artemis+Fowl&source=audiobook",
    );
    expect(
      fetch.mock.calls.some(
        ([url]) => url.includes("groups?") && url.includes("source=audiobook"),
      ),
    ).toBe(true);
    rerender(renderPage("?group=series&series=Artemis+Fowl&source=audiobook"));
    await screen.findByText("Audio only");
    expect(
      fetch.mock.calls.some(
        ([url]) =>
          url.includes("catalog?") &&
          url.includes("source=audiobook") &&
          url.includes("series=Artemis%20Fowl"),
      ),
    ).toBe(true);
    expect(screen.queryByText("Organize this series")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("link", { name: /Artemis Fowl Eoin Colfer/ }),
    );
    expect(onEdit).toHaveBeenCalledWith(
      expect.objectContaining({ id: 948 }),
      "/?group=series&series=Artemis+Fowl&source=audiobook",
    );
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute(
      "href",
      "/?group=series&source=audiobook",
    );
  });

  it("offers audio-only filtering without grouping", async () => {
    stubFetch((url) =>
      response(url.startsWith("/api/books/catalog") ? page([missing]) : []),
    );
    const onNavigate = vi.fn();
    renderWithClient(
      <LibraryWorkspace
        search="?group=none"
        hash=""
        onEdit={vi.fn()}
        onNavigate={onNavigate}
      />,
    );
    fireEvent.change(screen.getByLabelText("Library source"), {
      target: { value: "audiobook" },
    });
    expect(onNavigate).toHaveBeenCalledWith("/?group=none&source=audiobook");
    await waitFor(() =>
      expect(screen.getByText("Audio only")).toBeInTheDocument(),
    );
  });
});

it("loads series pages incrementally and fetches the complete list only for organizing", async () => {
  const books = [1, 2, 3].map((id) =>
    catalogBook({ id, title: `Volume ${id}`, series: "Saga" }),
  );
  const fetch = stubFetch((url) => {
    if (url.startsWith("/api/books/catalog")) {
      const params = new URL(url, "http://localhost").searchParams;
      const body: components["schemas"]["BookCatalogPage"] =
        params.get("limit") === "100"
          ? { items: books, next_cursor: null, total_count: 3, facets: null }
          : {
              items: params.has("cursor") ? books.slice(1) : books.slice(0, 1),
              next_cursor: params.has("cursor") ? null : "next",
              total_count: 3,
              facets: null,
            };
      return response(body);
    }
    return response([]);
  });
  renderWithClient(
    <LibraryWorkspace
      search="?series=Saga"
      hash=""
      onNavigate={vi.fn()}
      onEdit={vi.fn()}
    />,
  );
  await screen.findByText("Volume 1");
  expect(screen.queryByText("Volume 2")).not.toBeInTheDocument();
  expect(
    fetch.mock.calls.some(
      ([url]) =>
        url.includes("/api/books/catalog?") && url.includes("limit=100"),
    ),
  ).toBe(false);
  expect(
    fetch.mock.calls.some(([url]) => url.includes("sort_by=series_index")),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Load more books" }));
  await screen.findByText("Volume 3");
  expect(
    screen.queryByRole("button", { name: "Load more books" }),
  ).not.toBeInTheDocument();
  const details = screen.getByText("Organize this series").closest("details");
  expect(details).not.toBeNull();
  details!.open = true;
  fireEvent(details!, new Event("toggle"));
  await screen.findByRole("button", { name: "Rename" });
  expect(
    fetch.mock.calls.some(
      ([url]) =>
        url.includes("/api/books/catalog?") && url.includes("limit=100"),
    ),
  ).toBe(true);
});

it("preserves all filters in group links, saved views, and subsequent filter changes", async () => {
  localStorage.clear();
  const fetch = stubFetch((url) => {
    if (url.startsWith("/api/library/groups"))
      return response({
        items: [libraryGroup({ name: "Saga", author: "Writer" })],
        next_cursor: null,
        total_count: 1,
        facets: facets({ genres: [{ name: "Fantasy", count: 1 }] }),
      } satisfies components["schemas"]["LibraryGroupsPage"]);
    if (url.startsWith("/api/books/catalog")) return response(page([]));
    return response([]);
  });
  const onNavigate = vi.fn();
  const { unmount } = renderWithClient(
    <LibraryWorkspace
      search="?group=series&genre=Fantasy&audiobook=playable&review=refresh-error&sort=updated_at&order=desc&q=story"
      hash=""
      onNavigate={onNavigate}
      onEdit={vi.fn()}
    />,
  );
  const link = await screen.findByRole<HTMLAnchorElement>("link", {
    name: /Saga/,
  });
  const params = new URL(link.href).searchParams;
  for (const [key, value] of Object.entries({
    genre: "Fantasy",
    audiobook: "playable",
    review: "refresh-error",
    sort: "updated_at",
    order: "desc",
    q: "story",
  }))
    expect(params.get(key)).toBe(value);
  expect(fetch.mock.calls[0]?.[0]).toContain("genre=Fantasy");
  fireEvent.change(screen.getByLabelText("Library source"), {
    target: { value: "web" },
  });
  expect(onNavigate.mock.calls[0]?.[0]).toContain("genre=Fantasy");
  fireEvent.change(screen.getByLabelText("View name"), {
    target: { value: "Listen next" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save current view" }));
  unmount();
  renderWithClient(
    <LibraryWorkspace
      search=""
      hash=""
      onNavigate={onNavigate}
      onEdit={vi.fn()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Listen next" }));
  expect(onNavigate.mock.calls.at(-1)?.[0]).toContain("audiobook=playable");
  fireEvent.click(
    screen.getByRole("button", { name: "Delete saved view Listen next" }),
  );
  expect(
    screen.queryByRole("button", { name: "Listen next" }),
  ).not.toBeInTheDocument();
});

it("pages group summaries without discarding earlier groups", async () => {
  stubFetch((url) =>
    response({
      items: [
        libraryGroup({ name: url.includes("cursor=") ? "Second" : "First" }),
      ],
      total_count: 2,
      next_cursor: url.includes("cursor=") ? null : "next",
      facets: null,
    } satisfies components["schemas"]["LibraryGroupsPage"]),
  );
  renderWithClient(
    <LibraryWorkspace
      search=""
      hash=""
      onNavigate={vi.fn()}
      onEdit={vi.fn()}
    />,
  );
  await screen.findByRole("link", { name: /First/ });
  fireEvent.click(screen.getByRole("button", { name: "Load more groups" }));
  await screen.findByRole("link", { name: /Second/ });
  expect(screen.getByRole("link", { name: /First/ })).toBeInTheDocument();
});

it("lists standalone search matches as books beside matching series", async () => {
  const fetch = stubFetch((url) => {
    if (url.startsWith("/api/library/groups"))
      return response({
        items: [
          libraryGroup({ name: "Saga", book_count: 2 }),
          libraryGroup({ name: null }),
        ],
        next_cursor: null,
        total_count: 2,
        facets: facets(),
      } satisfies components["schemas"]["LibraryGroupsPage"]);
    if (url.startsWith("/api/books/catalog"))
      return response(page([catalogBook({ id: 7, title: "Saga Stories" })]));
    return response([]);
  });
  const onEdit = vi.fn();
  renderWithClient(
    <LibraryWorkspace
      search="?group=series&q=saga"
      hash=""
      onNavigate={vi.fn()}
      onEdit={onEdit}
    />,
  );
  expect(
    await screen.findByRole("link", { name: /Saga.*2 books/ }),
  ).toHaveAttribute("href", "/?group=series&series=Saga&q=saga");
  fireEvent.click(await screen.findByRole("link", { name: /Saga Stories/ }));
  expect(onEdit).toHaveBeenCalledWith(
    expect.objectContaining({ id: 7 }),
    "/?group=series&q=saga",
  );
  expect(screen.queryByText("Standalone books")).not.toBeInTheDocument();
  expect(
    screen.getByText(/Showing 1 of 1 series and 1 of 1 standalone book/),
  ).toBeInTheDocument();
  expect(
    fetch.mock.calls.some(
      ([url]) =>
        url.startsWith("/api/books/catalog") &&
        /[?&]series=(&|$)/.test(url) &&
        url.includes("q=saga"),
    ),
  ).toBe(true);
});

it("keeps standalone books grouped when not searching", async () => {
  const fetch = stubFetch(() =>
    response({
      items: [libraryGroup({ name: null, book_count: 3, author_count: 2 })],
      next_cursor: null,
      total_count: 1,
      facets: facets(),
    } satisfies components["schemas"]["LibraryGroupsPage"]),
  );
  renderWithClient(
    <LibraryWorkspace
      search=""
      hash=""
      onNavigate={vi.fn()}
      onEdit={vi.fn()}
    />,
  );
  expect(
    await screen.findByRole("link", { name: /Standalone books/ }),
  ).toBeInTheDocument();
  expect(
    fetch.mock.calls.some(([url]) => url.startsWith("/api/books/catalog")),
  ).toBe(false);
});
