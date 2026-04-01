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

    expect(screen.getByRole("heading", { name: "Library Audit" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Detect Series" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sync Online Metadata" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Storage Cleanup" })).toBeInTheDocument();
  });

  it("runs library audit and shows results", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url === "/api/library/validate") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              total_books: 3,
              issues_count: 1,
              issues: [
                {
                  book_id: 1,
                  title: "Broken Book",
                  author: "Author A",
                  issue: "immutable_file_not_found",
                  path: "library/Author A/immutable_Broken Book.epub",
                },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Run Library Audit" }));

    await waitFor(() => {
      expect(screen.getByText("Broken Book")).toBeInTheDocument();
    });

    expect(screen.getByText(/3 books checked/)).toBeInTheDocument();
    expect(screen.getByText(/1 issue/)).toBeInTheDocument();
  });

  it("shows failed web imports distinctly in the audit", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url === "/api/library/validate") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              total_books: 1,
              issues_count: 1,
              issues: [
                {
                  book_id: 7,
                  title: "Download failed",
                  author: "Pending",
                  issue: "failed_web_import",
                  source_url: "https://example.com/story/failed",
                },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Run Library Audit" }));

    await waitFor(() => {
      expect(screen.getByText("Download failed")).toBeInTheDocument();
    });

    expect(screen.getAllByText(/^failed web import$/i)[0]).toBeInTheDocument();
    expect(screen.getByText("https://example.com/story/failed")).toBeInTheDocument();
  });

  it("shows healthy message when audit finds no issues", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url === "/api/metadata/inbox") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url === "/api/library/validate") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              total_books: 5,
              issues_count: 0,
              issues: [],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "Run Library Audit" }));

    await waitFor(() => {
      expect(screen.getByText("All books have valid file paths. Library is healthy.")).toBeInTheDocument();
    });
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

  it("shows failed imports in storage cleanup results", async () => {
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
              files: [],
              books: [
                {
                  book_id: 9,
                  title: "Download failed",
                  author: "Pending",
                  source_url: "https://example.com/story/failed-cleanup",
                  issue: "failed_web_import",
                },
              ],
              total_bytes: 0,
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
      expect(screen.getByText("Download failed")).toBeInTheDocument();
    });

    expect(screen.getAllByText(/^failed web import$/i)[0]).toBeInTheDocument();
    expect(screen.getByText("https://example.com/story/failed-cleanup")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete 1 item" })).toBeInTheDocument();
  });
});
