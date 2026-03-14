import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import AddBook from "./AddBook.jsx";
import { renderWithClient } from "../test-utils.jsx";

describe("AddBook", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("summarizes mixed import results and shows skipped duplicates separately", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          filename: "batch.zip:books/Book One.epub",
          status: "success",
          book: { title: "Book One" },
        },
        {
          filename: "batch.zip:books/Book Two.epub",
          status: "skipped",
          error: "A book with title 'Book Two' by 'Author' already exists (id=7)",
        },
        {
          filename: "batch.zip:books/Broken.epub",
          status: "error",
          error: "Failed to parse EPUB file",
        },
      ],
    });

    const { container } = renderWithClient(<AddBook />);
    const input = container.querySelector("#file-upload");
    const submit = screen.getByRole("button", { name: "Add Book" });
    const zipFile = new File(["zip"], "batch.zip", { type: "application/zip" });

    fireEvent.change(input, { target: { files: [zipFile] } });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(screen.getByText("Imported 1 of 3 books. 1 skipped. 1 failed.")).toBeInTheDocument();
    });

    expect(screen.getByText("Added: 1 book.")).toBeInTheDocument();
    expect(screen.getByText("Skipped: 1 book.")).toBeInTheDocument();
    expect(screen.getByText("Failed: 1 book.")).toBeInTheDocument();
    expect(screen.getByText((text) => text.includes('"Book Two" by Author is already in your library.'))).toBeInTheDocument();
    expect(screen.getByText(/Broken\.epub/)).toBeInTheDocument();
  });
});
