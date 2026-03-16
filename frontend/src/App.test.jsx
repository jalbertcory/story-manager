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
        series: null,
        current_word_count: 100,
        source_type: "epub",
      },
    ];
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/books/catalog?sort_by=title&sort_order=asc") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockBooks),
        });
      }
      if (url === "/api/books/details?ids=1") {
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
        "/api/books/catalog?sort_by=title&sort_order=asc",
      );
    });

    await waitFor(() => {
      expect(screen.getAllByText("Book A")[0]).toBeInTheDocument();
      expect(screen.getAllByText("Author A")[0]).toBeInTheDocument();
    });
  });

  it("searches by unified query", async () => {
    const mockBooks = [
      { id: 2, title: "Book B", author: "Author B", source_type: "epub", series: null },
    ];
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/books/catalog?sort_by=title&sort_order=asc") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url === "/api/books/catalog?q=Author%20B&sort_by=title&sort_order=asc") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockBooks),
        });
      }
      if (url === "/api/books/details?ids=2") {
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
        "/api/books/catalog?sort_by=title&sort_order=asc",
      );
    });

    fireEvent.change(
      screen.getByPlaceholderText("Search by title, author, or series"),
      { target: { value: "Author B" } },
    );
    fireEvent.click(screen.getByText("Search"));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/catalog?q=Author%20B&sort_by=title&sort_order=asc",
      );
    });

    await waitFor(() => {
      expect(screen.getAllByText("Book B")[0]).toBeInTheDocument();
    });
  });

  it("loads the lightweight catalog first and hydrates visible book details", async () => {
    const catalogBooks = [
      {
        id: 1,
        title: "Saga Book 2",
        author: "Author A",
        series: "Saga",
        source_type: "epub",
      },
      {
        id: 2,
        title: "Saga Book 1",
        author: "Author A",
        series: "Saga",
        source_type: "epub",
      },
    ];
    const hydratedBooks = [
      {
        id: 2,
        title: "Saga Book 1",
        author: "Author A",
        series: "Saga",
        source_type: "epub",
        current_word_count: 1000,
      },
      {
        id: 1,
        title: "Saga Book 2",
        author: "Author A",
        series: "Saga",
        source_type: "epub",
        current_word_count: 1200,
      },
    ];

    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/books/catalog?sort_by=title&sort_order=asc") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(catalogBooks),
        });
      }
      if (url === "/api/books/details?ids=1&ids=2") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(hydratedBooks),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });

    renderWithClient(<App />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/books/details?ids=1&ids=2");
    });

    await waitFor(() => {
      expect(screen.getByText("Saga")).toBeInTheDocument();
      expect(screen.getByText("2 books")).toBeInTheDocument();
      expect(screen.getAllByText("Saga Book 1")[0]).toBeInTheDocument();
      expect(screen.getAllByText("Saga Book 2")[0]).toBeInTheDocument();
    });
  });
});
