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

    expect(await screen.findByDisplayValue("https://example.com/story")).toBeInTheDocument();

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

    expect(await screen.findByText("No source URL is currently attached.")).toBeInTheDocument();

    const removeButton = screen.getByRole("button", { name: "Remove Web Marker" });
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
});
