import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import BookSettings from "./BookSettings";
import { renderWithClient } from "../test-utils";

describe("BookSettings", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the source URL and can remove the web marker", async () => {
    const onBack = vi.fn();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/7/chapters") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url === "/api/books/7/matched-config") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url === "/api/series") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url === "/api/books/7/detach-source" && options?.method === "POST") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 7,
              title: "Imported Story",
              author: "Author",
              series: null,
              series_index: null,
              source_type: "epub",
              source_url: null,
              immutable_path: "library/original.epub",
              current_path: "library/current.epub",
              removed_chapters: [],
              content_selectors: [],
              created_at: "2026-03-17T00:00:00Z",
              content_updated_at: "2026-03-17T00:00:00Z",
              content_version: 1,
              updated_at: null,
              cover_path: null,
              notes: null,
              master_word_count: null,
              current_word_count: null,
              download_status: null,
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(
      <BookSettings
        book={{
          id: 7,
          title: "Imported Story",
          author: "Author",
          series: null,
          series_index: null,
          source_type: "web",
          source_url: "https://example.com/story",
          immutable_path: "library/original.epub",
          current_path: "library/current.epub",
          removed_chapters: [],
          content_selectors: [],
          created_at: "2026-03-17T00:00:00Z",
          content_updated_at: "2026-03-17T00:00:00Z",
          content_version: 1,
        }}
        onBack={onBack}
      />,
    );

    expect(
      await screen.findByText("https://example.com/story"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove Web Marker" }));

    expect(confirmSpy).toHaveBeenCalledWith(
      'Remove the web marker from "Imported Story"? This will keep the EPUB files but stop treating it as a web novel.',
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/books/7/detach-source", {
        method: "POST",
      });
    });
    await waitFor(() => {
      expect(onBack).toHaveBeenCalled();
    });
  });

  it("allows removing the web marker when a web book has epub files but no source URL", async () => {
    const onBack = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/8/chapters") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url === "/api/books/8/matched-config") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url === "/api/series") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url === "/api/books/8/detach-source" && options?.method === "POST") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 8,
              title: "Imported Story",
              author: "Author",
              series: null,
              series_index: null,
              source_type: "epub",
              source_url: null,
              immutable_path: "library/original.epub",
              current_path: "library/current.epub",
              removed_chapters: [],
              content_selectors: [],
              created_at: "2026-03-17T00:00:00Z",
              content_updated_at: "2026-03-17T00:00:00Z",
              content_version: 1,
              updated_at: null,
              cover_path: null,
              notes: null,
              master_word_count: null,
              current_word_count: null,
              download_status: null,
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(
      <BookSettings
        book={{
          id: 8,
          title: "Imported Story",
          author: "Author",
          series: null,
          series_index: null,
          source_type: "web",
          source_url: null,
          immutable_path: "library/original.epub",
          current_path: "library/current.epub",
          removed_chapters: [],
          content_selectors: [],
          created_at: "2026-03-17T00:00:00Z",
          content_updated_at: "2026-03-17T00:00:00Z",
          content_version: 1,
        }}
        onBack={onBack}
      />,
    );

    expect(
      await screen.findByText("No source URL is currently attached."),
    ).toBeInTheDocument();

    const removeButton = screen.getByRole("button", {
      name: "Remove Web Marker",
    });
    expect(removeButton).toBeEnabled();
    fireEvent.click(removeButton);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/books/8/detach-source", {
        method: "POST",
      });
    });
    await waitFor(() => {
      expect(onBack).toHaveBeenCalled();
    });
  });

  it("shows synced genre tags in metadata", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (
        url === "/api/books/9/chapters" ||
        url === "/api/books/9/matched-config" ||
        url === "/api/series"
      ) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });

    renderWithClient(
      <BookSettings
        book={{
          id: 9,
          title: "Tagged Book",
          author: "Author",
          series: "Saga",
          series_index: 1,
          genre_tags: ["Fantasy", "Adventure"],
          source_tags: ["Character Growth", "Female Protagonist"],
          user_genre_tags: ["Cozy"],
          metadata_sync_source: "open_library",
          metadata_synced_at: "2026-03-28T10:00:00Z",
          source_type: "epub",
          source_url: null,
          immutable_path: "library/original.epub",
          current_path: "library/current.epub",
          removed_chapters: [],
          content_selectors: [],
          created_at: "2026-03-17T00:00:00Z",
          content_updated_at: "2026-03-17T00:00:00Z",
          content_version: 1,
        }}
        onBack={() => {}}
      />,
    );

    expect(await screen.findByText("Fantasy")).toBeInTheDocument();
    expect(screen.getByText("Adventure")).toBeInTheDocument();
    expect(screen.getByText("Character Growth")).toBeInTheDocument();
    expect(screen.getByText("Female Protagonist")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Cozy")).toBeInTheDocument();
    expect(screen.getByText(/Synced from open_library on/)).toBeInTheDocument();
  });

  it("shows chapter update history for web books", async () => {
    const fetchMock = vi.fn((url) => {
      if (
        url === "/api/books/11/chapters" ||
        url === "/api/books/11/matched-config" ||
        url === "/api/series"
      ) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url === "/api/books/11/update-history") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              book_id: 11,
              history: [
                {
                  id: 0,
                  timestamp: "2025-12-25T00:00:00Z",
                  entry_type: "added",
                  previous_chapter_count: null,
                  new_chapter_count: 100,
                  chapters_added: 100,
                  words_added: 100000,
                  average_words_per_chapter: 1000,
                  included_in_stats: false,
                  is_initial_sync: true,
                },
                {
                  id: 1,
                  timestamp: "2025-12-28T00:00:00Z",
                  entry_type: "updated",
                  previous_chapter_count: 100,
                  new_chapter_count: 115,
                  chapters_added: 15,
                  words_added: 50000,
                  average_words_per_chapter: 3333.33,
                  included_in_stats: false,
                  is_initial_sync: false,
                  is_catch_up_sync: true,
                },
                {
                  id: 2,
                  timestamp: "2026-01-01T00:00:00Z",
                  entry_type: "updated",
                  previous_chapter_count: 10,
                  new_chapter_count: 12,
                  chapters_added: 2,
                  words_added: 4000,
                  average_words_per_chapter: 2000,
                  included_in_stats: true,
                  is_initial_sync: false,
                  is_catch_up_sync: false,
                },
                {
                  id: 3,
                  timestamp: "2026-01-08T00:00:00Z",
                  entry_type: "updated",
                  previous_chapter_count: 12,
                  new_chapter_count: 15,
                  chapters_added: 3,
                  words_added: 8000,
                  average_words_per_chapter: 2666.67,
                  included_in_stats: true,
                  is_initial_sync: false,
                  is_catch_up_sync: false,
                },
              ],
              summary: {
                total_update_events: 2,
                total_chapters_added: 5,
                total_words_added: 12000,
                average_words_per_week: 6000,
                average_words_per_month: 26000,
                average_days_between_updates: 7,
                predicted_next_update_at: "2026-01-15T00:00:00Z",
                last_update_at: "2026-01-08T00:00:00Z",
              },
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(
      <BookSettings
        book={{
          id: 11,
          title: "Growing Story",
          author: "Author",
          series: null,
          series_index: null,
          source_type: "web",
          source_url: "https://example.com/growing",
          immutable_path: "library/original.epub",
          current_path: "library/current.epub",
          removed_chapters: [],
          content_selectors: [],
          created_at: "2026-03-17T00:00:00Z",
          content_updated_at: "2026-03-17T00:00:00Z",
          content_version: 3,
        }}
        onBack={() => {}}
      />,
    );

    expect(await screen.findByText("Words / Week")).toBeInTheDocument();
    expect(screen.getByText("Update History")).toBeInTheDocument();
    expect(screen.getByText("6,000")).toBeInTheDocument();
    expect(screen.getByText(/\+3 ch/)).toBeInTheDocument();
    expect(screen.getByText(/8,000 words/)).toBeInTheDocument();
    expect(screen.getByText(/Initial sync/)).toBeInTheDocument();
    expect(screen.getByText(/Catch-up sync/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/books/11/update-history");
  });

  it("saves manual metadata identifiers", async () => {
    const fetchMock = vi.fn((url, options) => {
      if (
        url === "/api/books/10/chapters" ||
        url === "/api/books/10/matched-config"
      ) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url === "/api/series") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(["Saga"]),
        });
      }
      if (url === "/api/books/10" && options?.method === "PUT") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              id: 10,
              title: "Identifier Book",
              author: "Author",
              series: "Saga",
              series_index: 1,
              source_type: "epub",
              source_url: null,
              immutable_path: "library/original.epub",
              current_path: "library/current.epub",
              metadata_remote_ids: {
                isbn_13: "9780316339158",
                open_library_work_key: "/works/OL500W",
                goodreads_id: "12345",
              },
              user_genre_tags: ["Fantasy", "Romance"],
              removed_chapters: [],
              content_selectors: [],
              created_at: "2026-03-17T00:00:00Z",
              content_updated_at: "2026-03-17T00:00:00Z",
              content_version: 1,
              updated_at: null,
              cover_path: null,
              notes: null,
              master_word_count: null,
              current_word_count: null,
              download_status: null,
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(
      <BookSettings
        book={{
          id: 10,
          title: "Identifier Book",
          author: "Author",
          series: "Saga",
          series_index: 1,
          source_type: "epub",
          source_url: null,
          immutable_path: "library/original.epub",
          current_path: "library/current.epub",
          metadata_remote_ids: null,
          user_genre_tags: ["Fantasy"],
          removed_chapters: [],
          content_selectors: [],
          created_at: "2026-03-17T00:00:00Z",
          content_updated_at: "2026-03-17T00:00:00Z",
          content_version: 1,
        }}
        onBack={() => {}}
      />,
    );

    // Expand the collapsed Identifiers section
    fireEvent.click(screen.getByText("Identifiers"));

    fireEvent.change(screen.getByPlaceholderText("Manual ISBN-13"), {
      target: { value: "9780316339158" },
    });
    fireEvent.change(screen.getByPlaceholderText("zyTCAlFPjgYC"), {
      target: { value: "google-volume-1" },
    });
    fireEvent.change(screen.getByPlaceholderText("/works/OL123W"), {
      target: { value: "/works/OL500W" },
    });
    fireEvent.change(screen.getByPlaceholderText("Fantasy, Romance, LitRPG"), {
      target: { value: "Fantasy, Romance" },
    });
    fireEvent.change(screen.getByLabelText("Other Identifiers (JSON)"), {
      target: { value: '{\n  "goodreads_id": "12345"\n}' },
    });

    fireEvent.click(screen.getByRole("button", { name: "Save Metadata" }));

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(
        ([url, options]) =>
          url === "/api/books/10" && options?.method === "PUT",
      );
      expect(saveCall).toBeTruthy();
      expect(saveCall[1].headers).toEqual({
        "Content-Type": "application/json",
      });
      expect(JSON.parse(saveCall[1].body)).toEqual({
        title: "Identifier Book",
        author: "Author",
        series: "Saga",
        series_index: 1,
        user_genre_tags: ["Fantasy", "Romance"],
        metadata_remote_ids: {
          isbn_13: "9780316339158",
          google_books_volume_id: "google-volume-1",
          open_library_work_key: "/works/OL500W",
          goodreads_id: "12345",
        },
        removed_chapters: [],
        content_selectors: [],
        notes: null,
      });
    });
  });
});
