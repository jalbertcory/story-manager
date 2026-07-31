import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import App from "./App";
import { renderWithClient } from "./test-utils";

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
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
      if (url === "/api/series") {
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

    renderWithClient(<App />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/catalog?sort_by=title&sort_order=asc",
      );
    });

    fireEvent.click(await screen.findByRole("tab", { name: /standalone/i }));

    await waitFor(() => {
      expect(screen.getAllByText("Book A")[0]).toBeInTheDocument();
      expect(screen.getAllByText("Author A")[0]).toBeInTheDocument();
    });
  });

  it("searches by unified query", async () => {
    const mockBooks = [
      {
        id: 2,
        title: "Book B",
        author: "Author B",
        source_type: "epub",
        series: null,
      },
    ];

    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/books/catalog?sort_by=title&sort_order=asc") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (
        url === "/api/books/catalog?q=Author%20B&sort_by=title&sort_order=asc"
      ) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockBooks),
        });
      }
      if (url === "/api/series") {
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

    renderWithClient(<App />);

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/catalog?sort_by=title&sort_order=asc",
      );
    });

    fireEvent.change(
      screen.getByPlaceholderText("Search by title, author, series, or tag"),
      { target: { value: "Author B" } },
    );
    await new Promise((resolve) => window.setTimeout(resolve, 350));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/catalog?q=Author%20B&sort_by=title&sort_order=asc",
      );
    });

    fireEvent.click(await screen.findByRole("tab", { name: /standalone/i }));

    await waitFor(() => {
      expect(screen.getAllByText("Book B")[0]).toBeInTheDocument();
    });
  });

  it("renders series covers directly from the catalog without detail hydration", async () => {
    const catalogBooks = [
      {
        id: 1,
        title: "Saga Book 2",
        author: "Author A",
        series: "Saga",
        effective_genre_tags: ["Adventure", "Fantasy"],
        effective_series_genre_tags: ["Adventure", "Fantasy"],
        source_type: "epub",
        current_word_count: 1200,
        cover_path: "library/covers/1.jpg",
      },
      {
        id: 2,
        title: "Saga Book 1",
        author: "Author A",
        series: "Saga",
        effective_genre_tags: ["Fantasy"],
        effective_series_genre_tags: ["Adventure", "Fantasy"],
        source_type: "epub",
        current_word_count: 1000,
        cover_path: "library/covers/2.jpg",
      },
    ];

    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/books/catalog?sort_by=title&sort_order=asc") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(catalogBooks),
        });
      }
      if (url === "/api/series") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(["Saga"]),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });

    renderWithClient(<App />);

    await waitFor(() => {
      expect(screen.getByText("Saga")).toBeInTheDocument();
      expect(screen.getByText("2")).toBeInTheDocument();
      expect(screen.getByText("Fantasy")).toBeInTheDocument();
    });

    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      "/api/books/details?ids=1&ids=2",
    );
    expect(screen.getByAltText("Saga cover")).toHaveAttribute(
      "src",
      "/api/covers/2",
    );

    expect(screen.queryByText("Saga Book 1")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Saga"));

    await waitFor(() => {
      expect(screen.getAllByText("Saga Book 1")[0]).toBeInTheDocument();
      expect(screen.getAllByText("Saga Book 2")[0]).toBeInTheDocument();
      expect(screen.getAllByText("Adventure")[0]).toBeInTheDocument();
    });
  });

  it("lets you edit series-level genres from the library view", async () => {
    const mockBooks = [
      {
        id: 11,
        title: "Saga Book 1",
        author: "Author A",
        series: "Saga",
        effective_genre_tags: ["Fantasy"],
        effective_series_genre_tags: ["Fantasy"],
        series_user_genre_tags: ["Fantasy"],
        current_word_count: 1000,
        source_type: "epub",
      },
    ];

    globalThis.fetch = vi.fn((url, options) => {
      if (url === "/api/books/catalog?sort_by=title&sort_order=asc") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockBooks),
        });
      }
      if (url === "/api/series") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(["Saga"]),
        });
      }
      if (url === "/api/series/Saga/genres" && options?.method === "PUT") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              series_name: "Saga",
              user_genre_tags: ["Epic Fantasy", "Fantasy"],
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });

    renderWithClient(<App />);

    await waitFor(() => {
      expect(screen.getByText("Saga")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Saga"));
    fireEvent.click(screen.getByRole("button", { name: /genres/i }));

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText(
          "Fantasy, Science Fiction, Progression Fantasy",
        ),
      ).toBeInTheDocument();
    });

    fireEvent.change(
      screen.getByPlaceholderText(
        "Fantasy, Science Fiction, Progression Fantasy",
      ),
      {
        target: { value: "Fantasy, Epic Fantasy" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/series/Saga/genres", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_genre_tags: ["Fantasy", "Epic Fantasy"] }),
      });
    });
  });

  it("shows series genres from backend effective_series_genre_tags", async () => {
    const catalogBooks = [
      {
        id: 21,
        title: "Mixed Book 1",
        author: "Author A",
        series: "Mixed Saga",
        effective_genre_tags: ["Fantasy"],
        effective_series_genre_tags: [
          "Adventure",
          "Fantasy",
          "Progression Fantasy",
        ],
        current_word_count: 1000,
        source_type: "epub",
      },
      {
        id: 22,
        title: "Mixed Book 2",
        author: "Author A",
        series: "Mixed Saga",
        effective_genre_tags: ["Adventure"],
        effective_series_genre_tags: [
          "Adventure",
          "Fantasy",
          "Progression Fantasy",
        ],
        current_word_count: 1000,
        source_type: "epub",
      },
      {
        id: 23,
        title: "Mixed Book 3",
        author: "Author A",
        series: "Mixed Saga",
        effective_genre_tags: ["Progression Fantasy"],
        effective_series_genre_tags: [
          "Adventure",
          "Fantasy",
          "Progression Fantasy",
        ],
        current_word_count: 1000,
        source_type: "epub",
      },
    ];

    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/books/catalog?sort_by=title&sort_order=asc") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(catalogBooks),
        });
      }
      if (url === "/api/series") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(["Mixed Saga"]),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });

    renderWithClient(<App />);

    await waitFor(() => {
      expect(screen.getByText("Mixed Saga")).toBeInTheDocument();
      expect(screen.getByText("Fantasy")).toBeInTheDocument();
      expect(screen.getByText("Adventure")).toBeInTheDocument();
      expect(screen.getByText("Progression Fantasy")).toBeInTheDocument();
    });
  });

  it("lets you tag a standalone book with a series from the library view", async () => {
    const mockBooks = [
      {
        id: 4,
        title: "Loner",
        author: "Author Solo",
        current_word_count: 1200,
        source_type: "epub",
        series: null,
      },
    ];

    globalThis.fetch = vi.fn((url, options) => {
      if (url === "/api/books/catalog?sort_by=title&sort_order=asc") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockBooks),
        });
      }
      if (url === "/api/series") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(["Saga", "Chronicles"]),
        });
      }
      if (url === "/api/books/4" && options?.method === "PUT") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              ...mockBooks[0],
              series: "Saga",
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });

    renderWithClient(<App />);

    fireEvent.click(await screen.findByRole("tab", { name: /standalone/i }));

    await waitFor(() => {
      expect(screen.getByText("Loner")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /assign series/i }));

    await waitFor(() => {
      expect(
        screen.getByPlaceholderText("Add to a series"),
      ).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText("Add to a series"), {
      target: { value: "Saga" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/books/4", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ series: "Saga" }),
      });
    });
  });

  it("shows and filters AI-generated and human audiobook badges", async () => {
    const mockBooks = [
      {
        id: 31,
        title: "Audio Ready",
        author: "Narrator A",
        current_word_count: 1200,
        source_type: "epub",
        series: null,
        audiobook_enabled: true,
        audiobook_pipeline_status: "paused",
      },
      {
        id: 32,
        title: "Human Audio",
        author: "Narrator B",
        current_word_count: 1000,
        source_type: "epub",
        series: null,
        audiobook_enabled: false,
        audiobook_types: ["human_narrated"],
      },
      {
        id: 33,
        title: "Text Only",
        author: "Author B",
        current_word_count: 900,
        source_type: "epub",
        series: null,
        audiobook_enabled: false,
      },
    ];

    globalThis.fetch = vi.fn((url) => {
      if (
        url === "/api/books/catalog?sort_by=title&sort_order=asc" ||
        url === "/api/books/catalog?sort_by=audiobook_enabled&sort_order=desc"
      ) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockBooks),
        });
      }
      if (url === "/api/series") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<App />);
    fireEvent.click(await screen.findByRole("tab", { name: /standalone/i }));

    expect(await screen.findByTitle("Audiobook: paused")).toBeInTheDocument();
    expect(
      screen.getByTitle("Human-narrated audiobook"),
    ).toBeInTheDocument();
    expect(screen.getByText("Showing 3 of 3 books")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Audiobook"), {
      target: { value: "enabled" },
    });
    expect(screen.getByText("Showing 2 of 3 books")).toBeInTheDocument();
    expect(screen.getByText("Audio Ready")).toBeInTheDocument();
    expect(screen.getByText("Human Audio")).toBeInTheDocument();
    expect(screen.queryByText("Text Only")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Sort library by"), {
      target: { value: "audiobook_enabled" },
    });
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "/api/books/catalog?sort_by=audiobook_enabled&sort_order=desc",
      );
    });
  });

  it("keeps the book section and audiobook tab in the URL", async () => {
    window.history.replaceState(
      null,
      "",
      "/books/44/audiobooks?tab=characters",
    );
    const book = {
      id: 44,
      title: "Routed Audio",
      author: "Author",
      source_type: "epub",
      immutable_path: "library/source.epub",
      current_path: "library/current.epub",
      removed_chapters: [],
      content_selectors: [],
      content_version: 1,
      audiobook_enabled: true,
    };
    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/books/44") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(book) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<App />);

    const characters = await screen.findByRole("button", {
      name: "Characters",
    });
    expect(characters).toHaveClass("sub-tab--active");
    expect(window.location.pathname).toBe("/books/44/audiobooks");
    expect(window.location.search).toBe("?tab=characters");

    fireEvent.click(screen.getByRole("button", { name: "Analysis" }));
    expect(window.location.search).toBe("?tab=analysis");

    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(window.location.pathname).toBe("/books/44/details");
    expect(window.location.search).toBe("");

    fireEvent.click(screen.getByRole("button", { name: "Audiobook Pipeline" }));
    expect(window.location.pathname).toBe("/books/44/audiobooks");
    expect(window.location.search).toBe("?tab=analysis");

    fireEvent.click(screen.getByRole("button", { name: /back/i }));
    expect(window.location.pathname).toBe("/");
    expect(window.location.hash).toBe("#series");
    expect(await screen.findByText("No books found.")).toBeInTheDocument();
  });
});
