import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import App from "./App";
import { renderWithClient } from "./test-utils";

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
};
const saga = [
  {
    ...book,
    id: 1,
    title: "Saga Book 2",
    series: "Saga",
    series_index: 2,
    cover_path: "1.jpg",
    effective_series_genre_tags: ["Adventure", "Fantasy"],
    effective_genre_tags: ["Fantasy"],
  },
  {
    ...book,
    id: 2,
    title: "Saga Book 1",
    series: "Saga",
    series_index: 1,
    cover_path: "2.jpg",
    effective_series_genre_tags: ["Adventure", "Fantasy"],
    effective_genre_tags: ["Fantasy"],
  },
];
const group = {
  name: "Saga",
  author: "Author",
  author_count: 1,
  book_count: 2,
  audio_count: 0,
  cover_ids: [2, 1],
};
function mockApi(resolve = () => undefined) {
  globalThis.fetch = vi.fn((url, options) => {
    let data = resolve(url, options);
    if (data === undefined) {
      if (url.startsWith("/api/library/groups?")) data = [group];
      else if (url.startsWith("/api/books/catalog?"))
        data = [...saga].sort((a, b) => a.series_index - b.series_index);
      else if (url === "/api/series") data = ["Saga"];
      else if (url === "/api/books/44") data = book;
      else if (url.startsWith("/api/library/books/"))
        data = { audio_playable: false, universe_id: null };
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
        };
      } else data = [];
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(data) });
  });
}

describe("App workspaces", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
    globalThis.IntersectionObserver = class {
      observe() {}
      disconnect() {}
      unobserve() {}
    };
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
      fetch.mock.calls.some(([url]) => url.startsWith("/api/books/catalog")),
    ).toBe(false);
    fireEvent.click(screen.getByText("Saga"));
    expect(await screen.findByText("Saga Book 1")).toBeInTheDocument();
    const titles = screen
      .getAllByRole("link", { name: /Saga Book [12] cover/ })
      .map((node) => node.querySelector(".book-row-title").textContent);
    expect(titles).toEqual(["Saga Book 1", "Saga Book 2"]);
    expect(screen.getAllByText("Fantasy").length).toBeGreaterThan(0);
    expect(window.location.search).toContain("series=Saga");
    expect(fetch).not.toHaveBeenCalledWith("/api/books/details?ids=1&ids=2");
  });

  it("provides daily workflows and a settings directory without nested tab bars", async () => {
    mockApi();
    renderWithClient(<App />);
    const primary = await screen.findByRole("navigation", {
      name: "Primary navigation",
    });
    expect(
      within(primary)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual([
      "Library",
      "Web updates",
      "Review suggestions",
      "Background activity",
      "Settings",
    ]);
    fireEvent.click(
      within(primary).getByRole("link", { name: "Background activity" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Needs attention" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Activity view")).toHaveValue("attention");
    fireEvent.click(within(primary).getByRole("link", { name: "Settings" }));
    expect(
      await screen.findByRole("heading", { name: "Settings", exact: true }),
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
    expect(
      screen.getByRole("link", { name: "Settings", exact: true }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("opens each maintenance tool from Settings without a second navigation menu", async () => {
    window.history.replaceState(null, "", "/settings");
    mockApi();
    renderWithClient(<App />);
    for (const [linkName, heading, section] of [
      [/Library audit/, "Library Audit", ""],
      [/Series detection/, "Detect Series", "series"],
      [/Audiobook maintenance/, "Audiobooks", "audiobooks"],
      [/Backups/, "Backup & Restore", "backups"],
      [/Recycle bin/, "Recycle Bin", "recycle-bin"],
      [/Storage cleanup/, "Storage Cleanup", "storage"],
      [/Reader access/, "Reader API Keys", "reader-access"],
    ]) {
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
      expect(fetch).toHaveBeenCalledWith(
        "/api/library/groups?group_by=series&q=Author+B&sort_by=title&sort_order=asc&limit=30",
      ),
    );
    const filters = screen.getByRole("button", {
      name: "Filters",
      exact: true,
    });
    expect(filters).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("Library source")).not.toBeVisible();
    fireEvent.click(filters);
    fireEvent.change(screen.getByLabelText("Library source"), {
      target: { value: "web" },
    });
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
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
        ? [{ ...group, name: "Cosmere", universe_id: 7 }]
        : undefined,
    );
    renderWithClient(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Filters", exact: true }),
    );
    fireEvent.change(screen.getByLabelText("Group library by"), {
      target: { value: "universe" },
    });
    fireEvent.click(await screen.findByText("Cosmere"));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
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
    organizer.open = true;
    fireEvent(organizer, new Event("toggle"));
    fireEvent.click(await screen.findByRole("button", { name: "Genres" }));
    fireEvent.change(
      screen.getByPlaceholderText(
        "Fantasy, Science Fiction, Progression Fantasy",
      ),
      { target: { value: "Fantasy, Epic Fantasy" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/series/Saga/genres", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_genre_tags: ["Fantasy", "Epic Fantasy"] }),
      }),
    );
  });

  it("lets standalone books be assigned to a series", async () => {
    window.history.replaceState(null, "", "/?group=none&series=");
    mockApi((url) =>
      url.startsWith("/api/books/catalog?")
        ? [{ ...book, id: 4, title: "Loner", series: null }]
        : undefined,
    );
    renderWithClient(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Assign series" }),
    );
    fireEvent.change(await screen.findByPlaceholderText("Add to a series"), {
      target: { value: "Saga" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save", exact: true }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/books/4", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ series: "Saga" }),
      }),
    );
  });

  it("distinguishes playable audio from an enabled pipeline and returns to the filtered library", async () => {
    window.history.replaceState(null, "", "/?group=none&q=Audio");
    mockApi((url) =>
      url.startsWith("/api/books/catalog?")
        ? [
            book,
            { ...book, id: 45, title: "Playable", audio_playable: true },
            {
              ...book,
              id: 46,
              title: "Imported",
              audiobook_types: ["human_narrated"],
            },
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
      screen.queryByRole("button", { name: "Listen", exact: true }),
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
    fireEvent.click(
      screen.getByRole("button", { name: "Details", exact: true }),
    );
    expect(window.location.pathname).toBe("/books/44/details");
    fireEvent.click(
      screen.getByRole("button", { name: "Audiobooks", exact: true }),
    );
    expect(window.location.pathname).toBe("/books/44/audiobooks");
    expect(screen.getByLabelText("AI production view")).toHaveValue("analysis");
  });
});
