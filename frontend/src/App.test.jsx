import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import App from "./App";
import { renderWithClient } from "./test-utils";

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches and displays books on mount", async () => {
    const mockBooks = [
      {
        id: 1,
        title: "Book A",
        author: "Author A",
        master_word_count: 100,
        current_word_count: 100,
      },
    ];
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockBooks),
      }),
    );

    renderWithClient(<App />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/books");
    });

    await waitFor(() => {
      expect(screen.getByText("Book A")).toBeInTheDocument();
      expect(screen.getByText("Author A")).toBeInTheDocument();
    });
  });

  it("searches by author", async () => {
    const mockBooks = [{ id: 2, title: "Book B", author: "Author B" }];
    globalThis.fetch = vi.fn((url) => {
      if (url.includes("Author%20B")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockBooks),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });

    renderWithClient(<App />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/books");
    });

    fireEvent.change(screen.getByPlaceholderText("Search by author"), {
      target: { value: "Author B" },
    });
    fireEvent.click(screen.getByText("Search"));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/search/author/Author%20B",
      );
    });

    await waitFor(() => {
      expect(screen.getByText("Book B")).toBeInTheDocument();
    });
  });
});
