import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import App from "./App";

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches and displays books on mount", async () => {
    const mockBooks = [{ id: 1, title: "Book A", author: "Author A" }];
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockBooks),
      }),
    );

    render(<App />);

    expect(globalThis.fetch).toHaveBeenCalledWith("/api/books");
    await waitFor(() => {
      expect(screen.getByText("Book A")).toBeInTheDocument();
    });
  });

  it("searches by author", async () => {
    const mockBooks = [{ id: 2, title: "Book B", author: "Author B" }];
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockBooks),
      }),
    );

    render(<App />);
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/books");
    });

    globalThis.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(mockBooks),
    });

    fireEvent.change(screen.getByPlaceholderText("Search by author"), {
      target: { value: "Author B" },
    });
    fireEvent.click(screen.getByText("Search"));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenLastCalledWith(
        "/api/books/search/author/Author%20B",
      );
    });
  });
});
