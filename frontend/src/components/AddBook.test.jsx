import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AddBook from "./AddBook.jsx";
import { renderWithClient } from "../test-utils.jsx";

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
              detail: "Metadata will be collected when the durable web import runs.",
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
    expect(screen.getByRole("link", { name: "View Activity" })).toHaveAttribute(
      "href",
      "/activity/processing",
    );
    expect(JSON.parse(globalThis.fetch.mock.calls[1][1].body)).toEqual({
      url: "https://example.com/new",
    });
  });

  it("requires an explicit library-book match for audiobook imports", async () => {
    globalThis.fetch
      .mockResolvedValueOnce(
        jsonResponse([
          { id: 42, title: "Matched Book", author: "Narrated Author" },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse({ id: 8, name: "Human edition" }));

    const { container } = renderWithClient(<AddBook />);
    fireEvent.click(screen.getByRole("button", { name: /Audiobook/ }));
    await screen.findByRole("option", { name: /Matched Book/ });
    fireEvent.change(screen.getByLabelText("Attach narration to"), {
      target: { value: "42" },
    });
    fireEvent.change(
      container.querySelector('input[accept^=".zip"]'),
      {
        target: {
          files: [new File(["audio"], "narration.m4b", { type: "audio/mp4" })],
        },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Inspect selection" }));

    expect(await screen.findByText("Matched Book")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import 1 ready" }));

    expect(await screen.findByText("Queued")).toBeInTheDocument();
    await waitFor(() => {
      expect(globalThis.fetch.mock.calls[1][0]).toBe(
        "/api/books/42/audiobook/imports",
      );
    });
  });
});
