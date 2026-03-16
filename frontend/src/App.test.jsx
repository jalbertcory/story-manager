import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import App from "./App";
import { renderWithClient } from "./test-utils";

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    globalThis.IntersectionObserver = class {
      observe() {}
      disconnect() {}
      unobserve() {}
    };
  });

  it("fetches and displays books on mount", async () => {
    const mockBooks = [
      {
        id: 1,
        title: "Book A",
        author: "Author A",
        master_word_count: 100,
        current_word_count: 100,
        source_type: "epub",
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
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books?sort_by=title&sort_order=asc&skip=0&limit=20",
      );
    });

    await waitFor(() => {
      expect(screen.getAllByText("Book A")[0]).toBeInTheDocument();
      expect(screen.getAllByText("Author A")[0]).toBeInTheDocument();
    });
  });

  it("searches by unified query", async () => {
    const mockBooks = [
      { id: 2, title: "Book B", author: "Author B", source_type: "epub" },
    ];
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
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books?sort_by=title&sort_order=asc&skip=0&limit=20",
      );
    });

    fireEvent.change(
      screen.getByPlaceholderText("Search by title, author, or series"),
      { target: { value: "Author B" } },
    );
    fireEvent.click(screen.getByText("Search"));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/search?q=Author%20B&skip=0&limit=20",
      );
    });

    await waitFor(() => {
      expect(screen.getAllByText("Book B")[0]).toBeInTheDocument();
    });
  });

  it("hydrates full series for grouped browse results", async () => {
    const firstPage = [
      {
        id: 1,
        title: "Saga Book 2",
        author: "Author A",
        series: "Saga",
        source_type: "epub",
      },
    ];
    const fullSeries = [
      {
        id: 2,
        title: "Saga Book 1",
        author: "Author A",
        series: "Saga",
        source_type: "epub",
      },
      firstPage[0],
    ];

    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/books?sort_by=title&sort_order=asc&skip=0&limit=20") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(firstPage),
        });
      }
      if (url === "/api/books/search/series/Saga?limit=500") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(fullSeries),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });

    renderWithClient(<App />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/books/search/series/Saga?limit=500");
    });

    await waitFor(() => {
      expect(screen.getByText("Saga")).toBeInTheDocument();
      expect(screen.getByText("2 books")).toBeInTheDocument();
      expect(screen.getAllByText("Saga Book 1")[0]).toBeInTheDocument();
      expect(screen.getAllByText("Saga Book 2")[0]).toBeInTheDocument();
    });
  });
});
