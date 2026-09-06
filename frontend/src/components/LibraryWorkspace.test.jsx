import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderWithClient } from "../test-utils";
import LibraryWorkspace from "./LibraryWorkspace";

const response = (value) =>
  Promise.resolve({ ok: true, json: async () => value });
const page = (items) => ({items, next_cursor: null, total_count: items.length, facets: {series: 1, standalone: 0, web: 0, genres: []}});
const missing = {
  id: 948,
  title: "Artemis Fowl",
  author: "Eoin Colfer",
  series: "Artemis Fowl",
  source_type: "audiobook",
  has_epub: false,
};
afterEach(() => vi.unstubAllGlobals());

describe("Audio-only library", () => {
  it("keeps the missing EPUB filter when opening a series and returning from a book", async () => {
    const fetch = vi.fn((url) => {
      if (url.startsWith("/api/library/groups"))
        return response([
          {
            name: "Artemis Fowl",
            book_count: 1,
            audio_count: 1,
            author_count: 1,
            author: "Eoin Colfer",
            cover_ids: [],
          },
        ]);
      if (url.startsWith("/api/books/catalog")) return response(page([missing]));
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);
    const onEdit = vi.fn();
    const onNavigate = vi.fn();
    const renderPage = (search) => (
      <LibraryWorkspace
        search={search}
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
    vi.stubGlobal(
      "fetch",
      vi.fn((url) =>
        response(url.startsWith("/api/books/catalog") ? page([missing]) : []),
      ),
    );
    const onNavigate = vi.fn();
    renderWithClient(
      <LibraryWorkspace
        search="?group=none"
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
  const books = [1, 2, 3].map((id) => ({
    id,
    title: `Volume ${id}`,
    author: "Writer",
    series: "Saga",
    source_type: "epub",
  }));
  const fetch = vi.fn((url) => {
    if (url.startsWith("/api/books/catalog")) {
      const params = new URL(url, "http://localhost").searchParams;
      return response(
        params.get("limit") === "100"
          ? { items: books, next_cursor: null, total_count: 3 }
          : {
              items: params.has("cursor") ? books.slice(1) : books.slice(0, 1),
              next_cursor: params.has("cursor") ? null : "next",
              total_count: 3,
            },
      );
    }
    return response([]);
  });
  vi.stubGlobal("fetch", fetch);
  renderWithClient(
    <LibraryWorkspace
      search="?series=Saga"
      onNavigate={vi.fn()}
      onEdit={vi.fn()}
    />,
  );
  await screen.findByText("Volume 1");
  expect(screen.queryByText("Volume 2")).not.toBeInTheDocument();
  expect(fetch.mock.calls.some(([url]) => url.includes("limit=100"))).toBe(
    false,
  );
  expect(
    fetch.mock.calls.some(([url]) => url.includes("sort_by=series_index")),
  ).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Load more books" }));
  await screen.findByText("Volume 3");
  expect(
    screen.queryByRole("button", { name: "Load more books" }),
  ).not.toBeInTheDocument();
  const details = screen.getByText("Organize this series").closest("details");
  details.open = true;
  fireEvent(details, new Event("toggle"));
  await screen.findByRole("button", { name: "Rename" });
  expect(fetch.mock.calls.some(([url]) => url.includes("limit=100"))).toBe(
    true,
  );
});

it("preserves all filters in group links, saved views, and subsequent filter changes", async () => {
  localStorage.clear();
  const fetch = vi.fn(() =>
    response({
      items: [
        {
          name: "Saga",
          author: "Writer",
          author_count: 1,
          book_count: 1,
          cover_ids: [],
        },
      ],
      next_cursor: null,
      total_count: 1,
      facets: { genres: [{ name: "Fantasy", count: 1 }] },
    }),
  );
  vi.stubGlobal("fetch", fetch);
  const onNavigate = vi.fn();
  const { unmount } = renderWithClient(
    <LibraryWorkspace
      search="?group=series&genre=Fantasy&audiobook=playable&review=refresh-error&sort=updated_at&order=desc&q=story"
      onNavigate={onNavigate}
      onEdit={vi.fn()}
    />,
  );
  const link = await screen.findByRole("link", { name: /Saga/ });
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
  expect(fetch.mock.calls[0][0]).toContain("genre=Fantasy");
  fireEvent.change(screen.getByLabelText("Library source"), {
    target: { value: "web" },
  });
  expect(onNavigate.mock.calls[0][0]).toContain("genre=Fantasy");
  fireEvent.change(screen.getByLabelText("View name"), {
    target: { value: "Listen next" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save current view" }));
  unmount();
  renderWithClient(
    <LibraryWorkspace search="" onNavigate={onNavigate} onEdit={vi.fn()} />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Listen next" }));
  expect(onNavigate.mock.calls.at(-1)[0]).toContain("audiobook=playable");
  fireEvent.click(
    screen.getByRole("button", { name: "Delete saved view Listen next" }),
  );
  expect(
    screen.queryByRole("button", { name: "Listen next" }),
  ).not.toBeInTheDocument();
});

it("pages group summaries without discarding earlier groups", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url) =>
      response({
        items: [
          {
            name: url.includes("cursor=") ? "Second" : "First",
            book_count: 1,
            author_count: 1,
            cover_ids: [],
          },
        ],
        total_count: 2,
        next_cursor: url.includes("cursor=") ? null : "next",
      }),
    ),
  );
  renderWithClient(
    <LibraryWorkspace search="" onNavigate={vi.fn()} onEdit={vi.fn()} />,
  );
  await screen.findByRole("link", { name: /First/ });
  fireEvent.click(screen.getByRole("button", { name: "Load more groups" }));
  await screen.findByRole("link", { name: /Second/ });
  expect(screen.getByRole("link", { name: /First/ })).toBeInTheDocument();
});
