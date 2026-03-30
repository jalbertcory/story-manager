import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import Utilities from "./Utilities";
import { renderWithClient } from "../test-utils";

describe("Utilities", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("confirm", vi.fn(() => true));
    vi.stubGlobal("alert", vi.fn());
  });

  it("renders all utility sections", () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    expect(screen.getByRole("heading", { name: "Clean All Books" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Remove All Books" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Detect Series" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sync Online Metadata" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Storage Cleanup" })).toBeInTheDocument();
  });

  it("queues metadata sync and lets you approve a pending match", async () => {
    globalThis.fetch = vi.fn((url, options) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 4,
              trigger: "manual",
              status: "running",
              total_books: 10,
              processed_books: 2,
              matched_books: 1,
              proposed_books: 1,
              applied_books: 0,
              error: null,
              created_at: "2026-03-29T00:00:00Z",
              started_at: "2026-03-29T00:00:01Z",
              completed_at: null,
            }),
        });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve([
              {
                id: 11,
                book_id: 1,
                book_title: "Dragon One",
                book_author: "Author A",
                book_series: "Dragon Saga",
                match: {
                  id: 7,
                  book_id: 1,
                  status: "pending",
                  source: "open_library",
                  match_confidence: 0.93,
                  remote_title: "Dragon One",
                  remote_author: "Author A",
                  remote_url: "https://openlibrary.org/works/OL1W",
                  remote_ids: {},
                  last_checked_at: "2026-03-29T00:00:02Z",
                  approved_at: null,
                  rejected_at: null,
                },
                proposed_genre_tags: ["Fantasy"],
                possible_missing_series_books: ["Dragon Two"],
                note: null,
                status: "open",
                created_at: "2026-03-29T00:00:02Z",
                reviewed_at: null,
              },
            ]),
        });
      }
      if (url === "/api/metadata/jobs" && options?.method === "POST") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 5,
              trigger: "manual",
              status: "queued",
              total_books: 10,
              processed_books: 0,
              matched_books: 0,
              proposed_books: 0,
              applied_books: 0,
              error: null,
              created_at: "2026-03-29T00:00:00Z",
              started_at: null,
              completed_at: null,
            }),
        });
      }
      if (url === "/api/metadata/matches/7/approve" && options?.method === "POST") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 7,
              book_id: 1,
              status: "approved",
              source: "open_library",
            }),
        });
      }

      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 0 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText(/2\/10 processed, 1 matched, 1 proposed, 0 applied/)).toBeInTheDocument();
    });

    expect(screen.getByText("Proposed genres: Fantasy")).toBeInTheDocument();
    expect(screen.getByText("Possible missing in series: Dragon Two")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Queue Library Metadata Sync" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/metadata/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ book_ids: null, trigger: "manual" }),
      });
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve Match" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/metadata/matches/7/approve", {
        method: "POST",
      });
    });
  });

  it("calls reprocess-all and shows Done on success", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 3 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Clean All Books" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/reprocess-all",
        expect.objectContaining({ method: "POST" }),
      );
    });

    await waitFor(() => {
      expect(screen.getByText("Done.")).toBeInTheDocument();
    });
  });

  it("calls detect-series and shows results", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes("detect-series")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ updated: 2, series_detected: ["Dragon Saga", "Iron Path"] }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 0 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Detect Series in Library" }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/Updated 2 books: Dragon Saga, Iron Path/),
      ).toBeInTheDocument();
    });
  });

  it("shows 'No new series found' when detect-series finds nothing", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes("detect-series")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ updated: 0, series_detected: [] }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 0 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Detect Series in Library" }),
    );

    await waitFor(() => {
      expect(screen.getByText("No new series found.")).toBeInTheDocument();
    });
  });

  it("shows orphaned files after scanning", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes("storage/cleanup")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              dry_run: true,
              files: [{ path: "library/orphan.epub", size_bytes: 1024 }],
              total_bytes: 1024,
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 0 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(
      screen.getByRole("button", { name: "Scan for Orphaned Files" }),
    );

    await waitFor(() => {
      expect(screen.getByText("library/orphan.epub")).toBeInTheDocument();
    });
  });

  it("shows a detailed warning before removing all books", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes("/api/books/remove-all?dry_run=true")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              dry_run: true,
              book_count: 2,
              file_count: 5,
              total_bytes: 2048,
              log_count: 3,
              books: [
                {
                  id: 1,
                  title: "Alpha",
                  author: "Author One",
                  files: [{ path: "library/Author One/Alpha.epub", size_bytes: 1024 }],
                  log_entries: 2,
                },
                {
                  id: 2,
                  title: "Beta",
                  author: "Author Two",
                  files: [{ path: "library/Author Two/Beta.epub", size_bytes: 1024 }],
                  log_entries: 1,
                },
              ],
              paths: [
                "library/Author One/Alpha.epub",
                "library/Author Two/Beta.epub",
              ],
            }),
        });
      }

      if (url.includes("/api/books/remove-all?dry_run=false")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              dry_run: false,
              book_count: 2,
              file_count: 5,
              total_bytes: 2048,
              log_count: 3,
              books: [],
              paths: [],
            }),
        });
      }

      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 0 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Remove All Books" }));

    await waitFor(() => {
      expect(globalThis.confirm).toHaveBeenCalledWith(
        expect.stringContaining("This will permanently remove 2 books from the library."),
      );
    });

    expect(globalThis.confirm).toHaveBeenCalledWith(
      expect.stringContaining("Alpha by Author One"),
    );

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/remove-all?dry_run=false",
        expect.objectContaining({ method: "POST" }),
      );
    });

    expect(screen.getByText("Library cleared.")).toBeInTheDocument();
  });

  it("alerts instead of deleting when the library is already empty", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes("/api/books/remove-all?dry_run=true")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              dry_run: true,
              book_count: 0,
              file_count: 0,
              total_bytes: 0,
              log_count: 0,
              books: [],
              paths: [],
            }),
        });
      }

      return Promise.resolve({ ok: true, json: () => Promise.resolve({ reprocessed: 0 }) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Remove All Books" }));

    await waitFor(() => {
      expect(globalThis.alert).toHaveBeenCalledWith("No books are currently stored in the library.");
    });

    expect(globalThis.confirm).not.toHaveBeenCalled();
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      "/api/books/remove-all?dry_run=false",
      expect.anything(),
    );
  });
});
