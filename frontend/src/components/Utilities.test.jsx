import {
  act,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import Utilities from "./Utilities";
import { renderWithClient } from "../test-utils";

function openUtility(section) {
  act(() => {
    window.history.pushState(
      null,
      "",
      `/settings/library-tools?section=${section}`,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
}

describe("Utilities", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal(
      "confirm",
      vi.fn(() => true),
    );
    vi.stubGlobal("alert", vi.fn());
    window.history.replaceState(null, "", "/settings/library-tools");
  });

  it("opens tools directly from their URLs and follows browser navigation", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url.startsWith("/api/metadata/inbox?")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    expect(screen.queryByLabelText("Library tool")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Library Audit" }),
    ).toBeInTheDocument();

    openUtility("series");
    expect(
      screen.getByRole("heading", { name: "Detect Series" }),
    ).toBeInTheDocument();

    expect(
      screen.queryByRole("heading", { name: "Sync Online Metadata" }),
    ).not.toBeInTheDocument();
    openUtility("metadata");
    expect(
      screen.getByRole("heading", { name: "Sync Online Metadata" }),
    ).toBeInTheDocument();

    openUtility("storage");
    expect(
      screen.getByRole("heading", { name: "Storage Cleanup" }),
    ).toBeInTheDocument();

    openUtility("reader-access");
    expect(
      screen.getByRole("heading", { name: "Reader API Keys" }),
    ).toBeInTheDocument();
    expect(window.location.search).toBe("?section=reader-access");

    window.history.replaceState(
      null,
      "",
      "/settings/library-tools?section=metadata",
    );
    act(() => window.dispatchEvent(new PopStateEvent("popstate")));
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "Sync Online Metadata" }),
      ).toBeInTheDocument();
    });
  });

  it("previews and queues versioned human audiobook rebuilds", async () => {
    window.history.replaceState(
      null,
      "",
      "/settings/library-tools?section=audiobooks",
    );
    globalThis.fetch = vi.fn((url, options) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url.startsWith("/api/metadata/inbox?")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url === "/api/audiobook/imports/rebuild-preview") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              current_pipeline_version: 1,
              total_count: 4,
              rebuild_count: 2,
              realign_count: 1,
              up_to_date_count: 1,
              unavailable_count: 1,
            }),
        });
      }
      if (
        url === "/api/audiobook/imports/rebuild-all?force=false" &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              queued_count: 2,
              skipped_count: 2,
              pipeline_version: 1,
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    expect(
      await screen.findByRole("heading", { name: "Rebuild Human Audiobooks" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/2 of 4 editions need updating/),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Rebuild outdated human audiobooks" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByText(
        /Original audio and manual chapter corrections are preserved/,
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Queue rebuilds" }),
    );

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/api/audiobook/imports/rebuild-all?force=false",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(
      await screen.findByText("2 human audiobook rebuilds queued; 2 skipped."),
    ).toBeInTheDocument();
  });

  it("creates, downloads, verifies, and deliberately deletes backups", async () => {
    const filename =
      "story-manager-20260809T120000Z-abcd1234.story-manager.zip";
    const backup = {
      filename,
      created_at: "2026-08-09T12:00:00Z",
      size_bytes: 2048,
      library_file_count: 2,
      library_size_bytes: 1024,
      valid_manifest: true,
      verified_at_creation: true,
      error: null,
      download_url: `/api/backups/${filename}/download`,
    };
    globalThis.fetch = vi.fn((url, options) => {
      if (url === "/api/metadata/jobs/latest")
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      if (url.startsWith("/api/metadata/inbox?"))
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (String(url).startsWith("/api/processing/jobs?")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url === "/api/backups" && options?.method === "GET") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ retention_count: 10, backups: [backup] }),
        });
      }
      if (url === `/api/backups/${filename}` && options?.method === "DELETE") {
        return Promise.resolve({
          ok: true,
          status: 204,
          json: () => Promise.resolve(null),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: "queued" }),
      });
    });

    renderWithClient(<Utilities onBack={() => {}} />);
    openUtility("backups");

    expect(
      await screen.findByText("✓ Checksums verified when created"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href",
      backup.download_url,
    );

    fireEvent.click(screen.getByRole("button", { name: "Create backup" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/backups", expect.objectContaining({ method: "POST" })),
    );

    fireEvent.click(screen.getByRole("button", { name: "Verify now" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(`/api/backups/${filename}/verify`, expect.objectContaining({
        method: "POST",
      })),
    );

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/cannot be undone/i)).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Delete backup" }),
    );
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(`/api/backups/${filename}`, expect.objectContaining({
        method: "DELETE",
      }));
    });
  });

  it("runs library audit and shows results", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url.startsWith("/api/metadata/inbox?")) {
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
      if (url.startsWith("/api/metadata/inbox?")) {
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
    expect(
      screen.getByText("https://example.com/story/failed"),
    ).toBeInTheDocument();
  });

  it("shows healthy message when audit finds no issues", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url.startsWith("/api/metadata/inbox?")) {
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
      expect(
        screen.getByText(
          "All books have valid file paths. Library is healthy.",
        ),
      ).toBeInTheDocument();
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
      if (url.startsWith("/api/metadata/inbox?")) {
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
                book_series_index: 7,
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
                candidate_matches: [
                  {
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
                  {
                    id: 8,
                    book_id: 1,
                    status: "pending",
                    source: "open_library",
                    match_confidence: 0.91,
                    remote_title: "Dragon Eight",
                    remote_author: "Author A",
                    remote_url: "https://openlibrary.org/works/OL8W",
                    remote_ids: {},
                    remote_metadata: {
                      series: "Dragon Saga",
                      series_index: 8,
                    },
                    match_issues: [
                      "Series position conflict: local book is #7, candidate is #8.",
                    ],
                    last_checked_at: "2026-03-29T00:00:02Z",
                    approved_at: null,
                    rejected_at: null,
                  },
                ],
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
      if (
        url === "/api/metadata/matches/7/approve" &&
        options?.method === "POST"
      ) {
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
      if (
        url === "/api/metadata/matches/8/approve" &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 8,
              book_id: 1,
              status: "approved",
              source: "open_library",
            }),
        });
      }

      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ reprocessed: 0 }),
      });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    openUtility("metadata");

    await waitFor(() => {
      expect(
        screen.getByText(/2\/10 processed, 1 matched, 1 proposed, 0 applied/),
      ).toBeInTheDocument();
    });

    expect(screen.getByText("Proposed genres: Fantasy")).toBeInTheDocument();
    expect(
      screen.getByText("Possible missing in series: Dragon Two"),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Suggested match"), {
      target: { value: "8" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Verify this match");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Series position conflict: local book is #7, candidate is #8.",
    );
    expect(
      screen.getByText(
        /Local series: Dragon Saga #7 · Candidate series: Dragon Saga #8/,
      ),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Queue Library Metadata Sync" }),
    );

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/metadata/jobs", expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "content-type": "application/json" }),
        body: JSON.stringify({ book_ids: null, trigger: "manual" }),
      }));
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve Match" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/metadata/matches/8/approve",
        expect.objectContaining({
          method: "POST",
        }),
      );
    });
  });

  it("calls detect-series and shows results", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url.startsWith("/api/metadata/inbox?")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes("detect-series")) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              updated: 2,
              series_detected: ["Dragon Saga", "Iron Path"],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ reprocessed: 0 }),
      });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    openUtility("series");

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
      if (url.startsWith("/api/metadata/inbox?")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url.includes("detect-series")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ updated: 0, series_detected: [] }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ reprocessed: 0 }),
      });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    openUtility("series");

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
      if (url.startsWith("/api/metadata/inbox?")) {
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
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ reprocessed: 0 }),
      });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    openUtility("storage");

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
      if (url.startsWith("/api/metadata/inbox?")) {
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
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ reprocessed: 0 }),
      });
    });

    renderWithClient(<Utilities onBack={() => {}} />);

    openUtility("storage");

    fireEvent.click(
      screen.getByRole("button", { name: "Scan for Orphaned Files" }),
    );

    await waitFor(() => {
      expect(screen.getByText("Download failed")).toBeInTheDocument();
    });

    expect(screen.getAllByText(/^failed web import$/i)[0]).toBeInTheDocument();
    expect(
      screen.getByText("https://example.com/story/failed-cleanup"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete 1 item" }),
    ).toBeInTheDocument();
  });

  it("restores books and confirms permanent recycle-bin deletion", async () => {
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/metadata/jobs/latest") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url.startsWith("/api/metadata/inbox?")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url === "/api/recycle-bin") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              retention_days: 30,
              books: [
                {
                  id: 41,
                  title: "Recoverable Story",
                  author: "Author",
                  purge_after: "2026-09-08T00:00:00Z",
                  recovery_files_available: true,
                },
              ],
            }),
        });
      }
      if (url === "/api/recycle-bin/41" && options?.method === "DELETE") {
        return Promise.resolve({ ok: true, status: 204 });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(<Utilities onBack={() => {}} />);
    openUtility("recycle-bin");

    expect(await screen.findByText("Recoverable Story")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Permanently delete" }));
    const dialog = screen.getByRole("dialog", { name: /Permanently delete/ });
    expect(dialog).toBeInTheDocument();
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Permanently delete" }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/recycle-bin/41", expect.objectContaining({
        method: "DELETE",
      }));
    });
  });
});
