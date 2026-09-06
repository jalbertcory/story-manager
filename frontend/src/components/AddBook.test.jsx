import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AddBook from "./AddBook.jsx";
import { renderWithClient } from "../test-utils.jsx";

function catalogResponse(items) {
  return jsonResponse({ items, next_cursor: null, total_count: items.length,
    facets: { series: 0, standalone: items.length, web: 0, genres: [] } });
}

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

describe("AddBook", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    window.history.replaceState({}, "", "/");
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("requires preflight and duplicate review before importing book files", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              key: "file:0:0",
              name: "batch.zip:Book One.epub",
              status: "ready",
              title: "Book One",
              author: "Author",
              cleaning_configs: ["Royal Road"],
            },
            {
              key: "file:0:1",
              name: "batch.zip:Book Two.epub",
              status: "duplicate",
              title: "Book Two",
              author: "Author",
              detail: "Already in the library as book 7.",
            },
            {
              key: "file:0:2",
              name: "batch.zip:Broken.epub",
              status: "error",
              detail: "Could not read EPUB metadata.",
            },
          ],
          ready_count: 1,
          duplicate_count: 1,
          unsupported_count: 0,
          error_count: 1,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse([
          {
            filename: "batch.zip:Book One.epub",
            status: "success",
            book: { title: "Book One" },
          },
          {
            filename: "batch.zip:Book Two.epub",
            status: "skipped",
            error: "Already in the library",
          },
          {
            filename: "batch.zip:Broken.epub",
            status: "error",
            error: "Failed to parse EPUB file",
          },
        ]),
      );

    const { container } = renderWithClient(<AddBook />);
    const zipFile = new File(["zip"], "batch.zip", {
      type: "application/zip",
    });
    fireEvent.change(container.querySelector("#file-upload"), {
      target: { files: [zipFile] },
    });

    fireEvent.click(screen.getByRole("button", { name: "Inspect selection" }));

    expect(
      await screen.findByRole("heading", { name: "Review before importing" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Cleaning: Royal Road")).toBeInTheDocument();
    const importButton = screen.getByRole("button", { name: "Import 1 ready" });
    expect(importButton).toBeDisabled();

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "I reviewed the duplicates and want to skip them.",
      }),
    );
    expect(importButton).toBeEnabled();
    fireEvent.click(importButton);

    expect(
      await screen.findByRole("heading", { name: "Import results" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(globalThis.fetch.mock.calls[0][0]).toBe("/api/imports/preview");
    expect(globalThis.fetch.mock.calls[1][0]).toBe("/api/books/upload_epubs");
  });

  it("reports durable web work as queued and duplicate URLs as skipped", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(
        jsonResponse({
          items: [
            {
              key: "url:0",
              status: "ready",
              source_url: "https://example.com/new",
              detail:
                "Metadata will be collected when the durable web import runs.",
            },
            {
              key: "url:1",
              status: "duplicate",
              source_url: "https://example.com/existing",
              detail: "This source is already attached to Existing Story.",
            },
          ],
          ready_count: 1,
          duplicate_count: 1,
          unsupported_count: 0,
          error_count: 0,
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ title: "New Story" }, 201));

    renderWithClient(<AddBook />);
    fireEvent.click(screen.getByRole("button", { name: /Web novels/ }));
    fireEvent.change(screen.getByLabelText("Web novel URL"), {
      target: { value: "https://example.com/new" },
    });
    fireEvent.click(screen.getByRole("button", { name: "+ Add another URL" }));
    fireEvent.change(screen.getByLabelText("Web novel URL 2"), {
      target: { value: "https://example.com/existing" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Inspect selection" }));

    await screen.findByRole("heading", { name: "Review before importing" });
    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "I reviewed the duplicates and want to skip them.",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Import 1 ready" }));

    expect(await screen.findByText("Queued")).toBeInTheDocument();
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View progress" })).toHaveAttribute(
      "href",
      "/activity/processing",
    );
    expect(JSON.parse(globalThis.fetch.mock.calls[1][1].body)).toEqual({
      url: "https://example.com/new",
    });
  });

  it("imports directly into a selected library book", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(
        catalogResponse([
          { id: 42, title: "Matched Book", author: "Narrated Author" },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse({ id: 8, name: "Human edition" }));

    const { container } = renderWithClient(<AddBook />);
    fireEvent.click(screen.getByRole("button", { name: /Audiobook/ }));
    expect(
      screen.getByRole("heading", {
        name: "Import an audiobook",
      }),
    ).toBeInTheDocument();
    const bookSearch = await screen.findByRole("combobox", {
      name: "Attach narration to",
    });
    fireEvent.focus(bookSearch);
    fireEvent.change(bookSearch, { target: { value: "Matched" } });
    fireEvent.click(
      await screen.findByRole("option", { name: /Matched Book/ }),
    );
    fireEvent.change(container.querySelector('input[accept^=".zip"]'), {
      target: {
        files: [new File(["audio"], "narration.m4b", { type: "audio/mp4" })],
      },
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Import audiobook" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Import audiobook" }));

    expect(
      screen.queryByText("Review before importing"),
    ).not.toBeInTheDocument();

    expect(await screen.findByText("Queued")).toBeInTheDocument();
    await waitFor(() => {
      expect(globalThis.fetch.mock.calls[1][0]).toBe(
        "/api/books/42/audiobook/imports",
      );
    });
  });

  it("suggests a strong library match from the audiobook filename", async () => {
    globalThis.fetch.mockResolvedValueOnce(
      catalogResponse([
        {
          id: 42,
          title: "Dungeon Crawler Carl: A LitRPG/Gamelit Adventure",
          author: "Matt Dinniman",
        },
        {
          id: 43,
          title: "Carl's Doomsday Scenario: Dungeon Crawler Carl Book 2",
          author: "Matt Dinniman",
        },
      ]),
    );

    const { container } = renderWithClient(<AddBook />);
    fireEvent.click(screen.getByRole("button", { name: /Audiobook/ }));
    const bookSearch = await screen.findByRole("combobox", {
      name: "Attach narration to",
    });
    fireEvent.focus(bookSearch);
    await screen.findByRole("option", {
      name: /Dungeon Crawler Carl: A LitRPG\/Gamelit Adventure/,
    });
    fireEvent.change(bookSearch, {
      target: { value: "Dungeon Crawler Carl" },
    });
    expect(screen.getAllByRole("option")[0]).toHaveTextContent(
      "Dungeon Crawler Carl: A LitRPG/Gamelit Adventure",
    );
    fireEvent.change(container.querySelector('input[accept^=".zip"]'), {
      target: {
        files: [
          new File(["audio"], "Dungeon Crawler Carl [B08V8B2CGV].m4b", {
            type: "audio/mp4",
          }),
        ],
      },
    });

    await waitFor(() => {
      expect(
        screen.getByRole("combobox", { name: "Attach narration to" }),
      ).toHaveValue(
        "Dungeon Crawler Carl: A LitRPG/Gamelit Adventure — Matt Dinniman",
      );
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Matched from the filename",
    );
    expect(
      screen.getByRole("button", { name: "Import audiobook" }),
    ).toBeEnabled();
  });

  it("rechecks the library match when different audio files are chosen", async () => {
    globalThis.fetch.mockResolvedValue(
      catalogResponse([{ id: 42, title: "First Book", author: "Author" }]),
    );
    window.history.replaceState({}, "", "/import?type=audiobook");
    renderWithClient(<AddBook />);
    const picker = screen.getByLabelText("Audiobook files or ZIP");
    fireEvent.change(picker, {
      target: { files: [new File(["audio"], "First Book.m4b")] },
    });
    await waitFor(() =>
      expect(screen.getByRole("combobox")).toHaveValue("First Book — Author"),
    );
    fireEvent.change(picker, {
      target: { files: [new File(["audio"], "Another Story.m4b")] },
    });
    await waitFor(() =>
      expect(screen.getByLabelText("Book title")).toHaveValue("Another Story"),
    );
    expect(screen.getByRole("combobox")).toHaveValue("");
    expect(
      screen.getByText(/This will be imported as an audio-only book/),
    ).toBeInTheDocument();
  });

  it("defaults ambiguous filename matches to audio only without choosing a library book", async () => {
    globalThis.fetch.mockResolvedValueOnce(
      jsonResponse([
        { id: 42, title: "Shared Title", author: "First Author" },
        { id: 43, title: "Shared Title", author: "Second Author" },
      ]),
    );

    const { container } = renderWithClient(<AddBook />);
    fireEvent.click(screen.getByRole("button", { name: /Audiobook/ }));
    const bookSearch = await screen.findByRole("combobox", {
      name: "Attach narration to",
    });
    fireEvent.change(container.querySelector('input[accept^=".zip"]'), {
      target: {
        files: [new File(["audio"], "Shared Title.m4b")],
      },
    });

    await waitFor(() => {
      expect(screen.getByText("Shared Title.m4b")).toBeInTheDocument();
    });
    expect(bookSearch).toHaveValue("");
    expect(
      screen.queryByText(/Matched from the filename/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Import audiobook" }),
    ).toBeEnabled();
  });
  it("imports an audiobook without choosing an EPUB", async () => {
    window.history.replaceState({}, "", "/import?type=audiobook");
    globalThis.fetch = vi.fn(async (url, options) => {
      if (url === "/api/audiobooks/upload") {
        expect(options.body.get("title")).toBe("Audio Title");
        expect(options.body.get("author")).toBe("Narrator");
        expect(options.body.get("auto_align")).toBe("false");
        return jsonResponse({
          id: 3,
          book_id: 9,
          name: "Audio Title",
          status: "queued",
        });
      }
      return jsonResponse([]);
    });
    renderWithClient(<AddBook />);
    expect(
      screen.queryByLabelText("Create a new audio-only book"),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Book title"), {
      target: { value: "Audio Title" },
    });
    fireEvent.change(screen.getByLabelText("Author (optional)"), {
      target: { value: "Narrator" },
    });
    fireEvent.change(screen.getByLabelText("Audiobook files or ZIP"), {
      target: {
        files: [new File(["audio"], "book.m4b", { type: "audio/mp4" })],
      },
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Import audiobook" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Import audiobook" }));
    expect(
      screen.queryByText("Review before importing"),
    ).not.toBeInTheDocument();
    await waitFor(() =>
      expect(
        globalThis.fetch.mock.calls.some(
          ([url]) => url === "/api/audiobooks/upload",
        ),
      ).toBe(true),
    );
  });
});
