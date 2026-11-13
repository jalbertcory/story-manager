import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import type { Mock } from "vitest";
import App from "./App";
import type { components } from "./api/schema";
import type { Book, CatalogBook } from "./types";
import { jsonResponse, mockFetch, renderWithClient } from "./test-utils";
import type { FixtureFetch } from "./test-utils";

type LibraryGroup = components["schemas"]["LibraryGroup"];

const book = {
  id: 44,
  title: "Routed Audio",
  author: "Author",
  source_type: "epub",
  immutable_path: "source.epub",
  current_path: "current.epub",
  removed_chapters: [],
  content_selectors: [],
  content_version: 1,
  audiobook_enabled: true,
  audiobook_pipeline_status: null,
  audiobook_tts_provider: null,
  content_updated_at: "2026-01-01T00:00:00Z",
  cover_path: null,
  created_at: "2026-01-01T00:00:00Z",
  current_word_count: null,
  deleted_at: null,
  download_status: null,
  genre_tags: null,
  master_word_count: null,
  metadata_details: null,
  metadata_remote_ids: null,
  metadata_sync_source: null,
  metadata_synced_at: null,
  notes: null,
  purge_after: null,
  refresh_status: null,
  series: null,
  series_index: null,
  source_tags: null,
  source_url: null,
  updated_at: null,
  user_genre_tags: null,
} satisfies Book;
const catalogBook = (overrides: Partial<CatalogBook> = {}): CatalogBook => ({
  id: book.id,
  title: book.title,
  author: book.author,
  source_type: book.source_type,
  audiobook_enabled: book.audiobook_enabled,
  audio_playable: false,
  audiobook_pipeline_status: null,
  audiobook_types: [],
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
  source_url: null,
  universe_id: null,
  universe_name: null,
  updated_at: null,
  user_genre_tags: null,
  ...overrides,
});
const saga = [
  catalogBook({
    id: 1,
    title: "Saga Book 2",
    series: "Saga",
    series_index: 2,
    cover_path: "1.jpg",
    effective_series_genre_tags: ["Adventure", "Fantasy"],
    effective_genre_tags: ["Fantasy"],
  }),
  catalogBook({
    id: 2,
    title: "Saga Book 1",
    series: "Saga",
    series_index: 1,
    cover_path: "2.jpg",
    effective_series_genre_tags: ["Adventure", "Fantasy"],
    effective_genre_tags: ["Fantasy"],
  }),
];
const group = {
  name: "Saga",
  author: "Author",
  author_count: 1,
  book_count: 2,
  audio_count: 0,
  cover_ids: [2, 1],
  universe_id: null,
} satisfies LibraryGroup;
const facets = {
  series: 1,
  standalone: 0,
  web: 0,
  genres: [],
  audiobook_available: 0,
  audiobook_missing: 0,
  missing_series: 0,
  refresh_attention: 0,
  refreshing: 0,
} satisfies components["schemas"]["CatalogFacets"];
const passwordAuth = (authenticated: boolean) =>
  ({
    mode: "password",
    authenticated,
  }) satisfies components["schemas"]["AdminAuthStatus"];

let fetchMock: Mock<FixtureFetch>;
let apiFetch: FixtureFetch;

function expectRequest(expected: string) {
  const target = new URL(expected, "http://localhost");
  expect(
    fetchMock.mock.calls.some(([url]) => {
      const actual = new URL(url, "http://localhost");
      return (
        actual.pathname === target.pathname &&
        [...target.searchParams].every(
          ([key, value]) => actual.searchParams.get(key) === value,
        )
      );
    }),
  ).toBe(true);
}
function mockApi(
  resolve: (...args: Parameters<FixtureFetch>) => unknown = () => undefined,
) {
  apiFetch = (url, options) => {
    let data = resolve(url, options);
    if (data === undefined) {
      if (url === "/api/auth/status")
        data = {
          mode: "disabled",
          authenticated: true,
        } satisfies components["schemas"]["AdminAuthStatus"];
      else if (url.startsWith("/api/library/groups?")) data = [group];
      else if (url.startsWith("/api/books/catalog?"))
        data = [...saga].sort(
          (a, b) => (a.series_index ?? 0) - (b.series_index ?? 0),
        );
      else if (url === "/api/series") data = ["Saga"];
      else if (url === "/api/books/44") data = book;
      else if (url.startsWith("/api/library/books/"))
        data = {
          id: book.id,
          audio_playable: false,
          has_epub: true,
          universe_id: null,
          universe_name: null,
        } satisfies components["schemas"]["LibraryBookInfo"];
      else if (url === "/api/dashboard/attention?limit=5") {
        const category = { count: 0, items: [] };
        data = {
          total_count: 0,
          failed_jobs: category,
          failed_refreshes: category,
          stale_audiobooks: category,
          metadata_proposals: category,
          broken_files: category,
          missing_covers: category,
        } satisfies components["schemas"]["AttentionDashboard"];
      } else data = [];
    }
    if (
      Array.isArray(data) &&
      (url.startsWith("/api/books/catalog?") ||
        url.startsWith("/api/library/groups?"))
    ) {
      data = {
        items: data,
        next_cursor: null,
        total_count: data.length,
        facets,
      };
    }
    return Promise.resolve(jsonResponse(data));
  };
  fetchMock = mockFetch(apiFetch);
}

describe("App workspaces", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("shows sign-out failures and lets the user retry", async () => {
    mockApi((url) =>
      url === "/api/auth/status" ? passwordAuth(true) : undefined,
    );
    renderWithClient(<App />);
    const button = await screen.findByRole("button", { name: "Sign out" });
    await screen.findByAltText("Saga cover");
    const originalFetch = apiFetch;
    fetchMock.mockImplementation((url, options) =>
      url === "/api/auth/logout"
        ? Promise.reject(new Error("Sign out unavailable"))
        : originalFetch(url, options),
    );
    fireEvent.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sign out unavailable",
    );
    expect(button).toBeEnabled();
    fetchMock.mockImplementation((url, options) =>
      url === "/api/auth/logout"
        ? Promise.resolve(jsonResponse(passwordAuth(false)))
        : originalFetch(url, options),
    );
    fireEvent.click(button);
    expect(
      await screen.findByRole("heading", { name: "Admin Login" }),
    ).toBeInTheDocument();
  });

  function rejectLibraryGroups(detail: string) {
    const originalFetch = apiFetch;
    fetchMock.mockImplementation((url, options) =>
      url.startsWith("/api/library/groups?")
        ? Promise.resolve(jsonResponse({ detail }, 401))
        : originalFetch(url, options),
    );
  }

  it("asks to sign in again when the admin session expires", async () => {
    mockApi((url) =>
      url === "/api/auth/status" ? passwordAuth(true) : undefined,
    );
    rejectLibraryGroups("Admin authentication required");
    renderWithClient(<App />);
    expect(
      await screen.findByRole("heading", { name: "Admin Login" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Your session expired",
    );
  });

  it("never shows sign-in for a 401 when app auth is disabled", async () => {
    mockApi();
    rejectLibraryGroups("Proxy says no");
    renderWithClient(<App />);
    expect(await screen.findByText(/Proxy says no/)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Admin Login" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Primary navigation" }),
    ).toBeInTheDocument();
  });

  it("reports an unreachable server instead of assuming no sign-in", async () => {
    mockApi();
    const originalFetch = apiFetch;
    fetchMock.mockImplementationOnce(() =>
      Promise.reject(new TypeError("Failed to fetch")),
    );
    renderWithClient(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Failed to fetch",
    );
    fetchMock.mockImplementation(originalFetch);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByAltText("Saga cover")).toBeInTheDocument();
  });

  it("keeps unsaved book edits when browser Back is refused", async () => {
    mockApi();
    renderWithClient(<App />);
    await screen.findByAltText("Saga cover");
    window.history.pushState(null, "", "/books/44/details");
    window.dispatchEvent(new PopStateEvent("popstate"));
    const title = await screen.findByLabelText("Title");
    fireEvent.change(title, { target: { value: "Edited title" } });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    window.history.replaceState(null, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(window.location.pathname).toBe("/books/44/details");
    expect(screen.getByLabelText("Title")).toHaveValue("Edited title");
    confirm.mockReturnValue(true);
    window.history.replaceState(null, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(await screen.findByAltText("Saga cover")).toBeInTheDocument();
  });

  it("starts with cover groups and pages series books in server order", async () => {
    mockApi();
    renderWithClient(<App />);
    expect(await screen.findByAltText("Saga cover")).toHaveAttribute(
      "src",
      "/api/covers/2",
    );
    expect(screen.queryByText("Saga Book 1")).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some(([url]) =>
        url.startsWith("/api/books/catalog"),
      ),
    ).toBe(false);
    fireEvent.click(screen.getByText("Saga"));
    expect(await screen.findByText("Saga Book 1")).toBeInTheDocument();
    const titles = screen
      .getAllByRole("link", { name: /Saga Book [12] cover/ })
      .map((node) => node.querySelector(".book-row-title")?.textContent);
    expect(titles).toEqual(["Saga Book 1", "Saga Book 2"]);
    expect(screen.getAllByText("Fantasy").length).toBeGreaterThan(0);
    expect(window.location.search).toContain("series=Saga");
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/books/details?ids=1&ids=2",
    );
  });

  it("provides daily workflows and a settings directory without nested tab bars", async () => {
    mockApi();
    renderWithClient(<App />);
    const primary = await screen.findByRole("navigation", {
      name: "Primary navigation",
    });
    const links = within(primary).getAllByRole("link");
    expect(
      [
        "Library",
        "Web updates",
        "Metadata review",
        "Background activity",
        "Settings",
      ].map((name) =>
        links.indexOf(within(primary).getByRole("link", { name })),
      ),
    ).toEqual([0, 1, 2, 3, 4]);
    fireEvent.click(
      within(primary).getByRole("link", { name: "Background activity" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Needs attention" }),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("navigation", { name: "Activity view" }),
      ).getByRole("link", { name: "Needs attention" }),
    ).toHaveAttribute("aria-current", "page");
    fireEvent.click(within(primary).getByRole("link", { name: "Settings" }));
    expect(
      await screen.findByRole("heading", { name: "Settings" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Cleaning rules/ }),
    ).toHaveAttribute("href", "/settings/cleaning");
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  it("keeps legacy deep links and browser history working", async () => {
    window.history.replaceState(null, "", "/processing?status=error");
    mockApi();
    renderWithClient(<App />);
    expect(
      await screen.findByRole("heading", { name: "Processing jobs" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/activity/processing");
    expect(window.location.search).toBe("?status=error");
    window.history.replaceState(null, "", "/settings/logs");
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(
      await screen.findByRole("heading", { name: "Application Logs" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("shows a not-found page for unknown addresses", async () => {
    window.history.replaceState(null, "", "/no-such-page");
    mockApi();
    renderWithClient(<App />);
    expect(
      await screen.findByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Go to the library" }));
    expect(window.location.pathname).toBe("/");
    expect(await screen.findByAltText("Saga cover")).toBeInTheDocument();
  });

  it("opens each maintenance tool from Settings without a second navigation menu", async () => {
    window.history.replaceState(null, "", "/settings");
    mockApi();
    renderWithClient(<App />);
    const tools: [RegExp, string, string][] = [
      [/Library audit/, "Library audit", ""],
      [/Series detection/, "Series detection", "series"],
      [/Audiobook maintenance/, "Audiobook maintenance", "audiobooks"],
      [/Backups/, "Backups", "backups"],
      [/Recycle bin/, "Recycle bin", "recycle-bin"],
      [/Storage cleanup/, "Storage cleanup", "storage"],
      [/Reader access/, "Reader access", "reader-access"],
    ];
    for (const [linkName, heading, section] of tools) {
      fireEvent.click(await screen.findByRole("link", { name: linkName }));
      expect(
        await screen.findByRole("heading", { name: heading, level: 2 }),
      ).toBeInTheDocument();
      expect(screen.getAllByRole("heading", { name: heading })).toHaveLength(1);
      expect(window.location.search).toBe(section ? `?section=${section}` : "");
      expect(screen.queryByLabelText("Library tool")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("link", { name: "← Settings" }));
    }
  });

  it("searches groups on the server and combines source filtering", async () => {
    mockApi();
    renderWithClient(<App />);
    fireEvent.change(await screen.findByLabelText("Search library"), {
      target: { value: "Author B" },
    });
    await waitFor(() =>
      expectRequest(
        "/api/library/groups?group_by=series&q=Author+B&sort_by=title&sort_order=asc&limit=30",
      ),
    );
    const filters = screen.getByRole("button", { name: "Filters" });
    expect(filters).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("Library source")).not.toBeVisible();
    fireEvent.click(filters);
    fireEvent.change(screen.getByLabelText("Library source"), {
      target: { value: "web" },
    });
    await waitFor(() =>
      expectRequest(
        "/api/library/groups?group_by=series&q=Author+B&sort_by=title&sort_order=asc&limit=30&source=web",
      ),
    );
    const activeFilters = screen.getByRole("button", { name: "Filters (1)" });
    expect(activeFilters).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(activeFilters);
    expect(screen.getByLabelText("Library source")).not.toBeVisible();
    expect(screen.getByLabelText("Library source")).toHaveValue("web");
  });

  it("navigates universe to series without changing reading order", async () => {
    mockApi((url) =>
      url.startsWith("/api/library/groups?group_by=universe")
        ? [{ ...group, name: "Cosmere", universe_id: 7 } satisfies LibraryGroup]
        : undefined,
    );
    renderWithClient(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Filters" }));
    fireEvent.change(screen.getByLabelText("Group library by"), {
      target: { value: "universe" },
    });
    fireEvent.click(await screen.findByText("Cosmere"));
    await waitFor(() =>
      expectRequest(
        "/api/library/groups?group_by=series&q=&sort_by=title&sort_order=asc&limit=30&universe=7",
      ),
    );
    fireEvent.click(await screen.findByText("Saga"));
    expect(await screen.findByText("Saga Book 1")).toBeInTheDocument();
    expect(window.location.search).toContain("universe=7");
    expect(
      screen.getByRole("navigation", { name: "Library location" }),
    ).toHaveTextContent("Cosmere");
  });

  it("keeps series genre editing available", async () => {
    window.history.replaceState(null, "", "/?series=Saga");
    mockApi();
    renderWithClient(<App />);
    const organizer = (await screen.findByText("Organize this series")).closest(
      "details",
    );
    expect(organizer).not.toBeNull();
    organizer!.open = true;
    fireEvent(organizer!, new Event("toggle"));
    fireEvent.click(await screen.findByRole("button", { name: "Genres" }));
    fireEvent.change(
      screen.getByPlaceholderText(
        "Fantasy, Science Fiction, Progression Fantasy",
      ),
      { target: { value: "Fantasy, Epic Fantasy" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/series/Saga/genres",
        expect.objectContaining({
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            user_genre_tags: ["Fantasy", "Epic Fantasy"],
          }),
        }),
      ),
    );
  });

  it("lets standalone books be assigned to a series", async () => {
    window.history.replaceState(null, "", "/?group=none&series=");
    mockApi((url) =>
      url.startsWith("/api/books/catalog?")
        ? [catalogBook({ id: 4, title: "Loner", series: null })]
        : undefined,
    );
    renderWithClient(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Assign series" }),
    );
    fireEvent.change(await screen.findByPlaceholderText("Add to a series"), {
      target: { value: "Saga" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/books/4",
        expect.objectContaining({
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ series: "Saga" }),
        }),
      ),
    );
  });

  it("distinguishes playable audio from an enabled pipeline and returns to the filtered library", async () => {
    window.history.replaceState(null, "", "/?group=none&q=Audio");
    mockApi((url) =>
      url.startsWith("/api/books/catalog?")
        ? [
            catalogBook(),
            catalogBook({ id: 45, title: "Playable", audio_playable: true }),
            catalogBook({
              id: 46,
              title: "Imported",
              audiobook_types: ["human_narrated"],
            }),
          ]
        : undefined,
    );
    renderWithClient(<App />);
    expect(await screen.findByText("Routed Audio")).toBeInTheDocument();
    expect(screen.getAllByText("Audiobook")).toHaveLength(1);
    expect(screen.getByText("Audio imported")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Routed Audio"));
    expect(
      await screen.findByRole("button", { name: "Edit details" }),
    ).toBeInTheDocument();
    expect(window.location.pathname).toBe("/books/44/overview");
    expect(
      screen.queryByRole("button", { name: "Listen" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Back to library/ }));
    expect(window.location.search).toBe("?group=none&q=Audio");
  });

  it("keeps audiobook production views in the URL", async () => {
    window.history.replaceState(
      null,
      "",
      "/books/44/audiobooks?tab=characters",
    );
    mockApi();
    renderWithClient(<App />);
    expect(await screen.findByLabelText("AI production view")).toHaveValue(
      "characters",
    );
    fireEvent.change(screen.getByLabelText("AI production view"), {
      target: { value: "analysis" },
    });
    expect(window.location.search).toBe("?tab=analysis");
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(window.location.pathname).toBe("/books/44/details");
    fireEvent.click(screen.getByRole("button", { name: "Audiobooks" }));
    expect(window.location.pathname).toBe("/books/44/audiobooks");
    expect(screen.getByLabelText("AI production view")).toHaveValue("analysis");
  });
});
