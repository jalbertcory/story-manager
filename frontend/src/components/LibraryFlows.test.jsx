import { screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithClient } from "../test-utils";
import UniverseMembership from "./UniverseMembership";
import WebUpdates from "./WebUpdates";
import Utilities from "./Utilities";

const ok = (value) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(value) });
describe("Library workflow actions", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("assigns a series universe and removes standalone membership", async () => {
    globalThis.fetch = vi.fn((url) =>
      ok(url === "/api/library/universes" ? [{ id: 7, name: "Cosmere" }] : {}),
    );
    const { unmount } = renderWithClient(
      <UniverseMembership series="Mistborn" />,
    );
    fireEvent.change(
      screen.getByPlaceholderText("Choose or create a universe"),
      { target: { value: "Cosmere" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save universe" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/library/universe-membership", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Cosmere", series: "Mistborn" }),
      }),
    );
    unmount();
    renderWithClient(<UniverseMembership bookId={3} currentName="Cosmere" />);
    fireEvent.change(
      screen.getByPlaceholderText("Choose or create a universe"),
      { target: { value: "" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save universe" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/library/universe-membership", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: null, book_id: 3 }),
      }),
    );
  });

  it("surfaces failed source checks first, filters changes, and retries the affected book", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url.startsWith("/api/books/catalog?"))
        return ok([
          {
            id: 1,
            title: "A changed novel",
            author: "Writer",
            source_type: "web",
          },
          {
            id: 2,
            title: "Z failed novel",
            author: "Writer",
            source_type: "web",
            refresh_status: "error",
          },
        ]);
      if (url === "/api/library/web-checks")
        return ok([
          {
            book_id: 1,
            entry_type: "updated",
            timestamp: "2026-09-04T12:00:00Z",
            previous_chapter_count: 10,
            new_chapter_count: 12,
          },
        ]);
      return ok([]);
    });
    renderWithClient(<WebUpdates onEdit={vi.fn()} />);
    expect(
      await screen.findByText("1 novel needs attention"),
    ).toBeInTheDocument();
    const bookLinks = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("href")?.startsWith("/books/"));
    expect(bookLinks[0]).toHaveTextContent("Z failed novel");
    expect(screen.getByText(/2 chapters added/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry check" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/books/2/refresh", {
        method: "POST",
      }),
    );
    fireEvent.change(screen.getByLabelText("Filter web updates"), {
      target: { value: "updated" },
    });
    expect(screen.queryByText("Z failed novel")).not.toBeInTheDocument();
    expect(screen.getByText("A changed novel")).toBeInTheDocument();
  });

  it("only offers pending match decisions in the review queue", async () => {
    const pending = {
      id: 1,
      status: "pending",
      remote_title: "Needs review",
      remote_author: "Author",
    };
    globalThis.fetch = vi.fn((url) => {
      if (url.startsWith("/api/metadata/inbox?"))
        return ok([
          {
            id: 1,
            book_id: 1,
            book_title: "Reviewable book",
            book_author: "Author",
            match: pending,
            candidate_matches: [
              pending,
              { ...pending, id: 2, remote_title: "Alternative" },
              {
                ...pending,
                id: 3,
                status: "auto_approved",
                remote_title: "Already handled",
              },
            ],
            proposed_genre_tags: [],
            possible_missing_series_books: [],
          },
        ]);
      if (url === "/api/metadata/jobs/latest") return ok(null);
      return ok([]);
    });
    renderWithClient(<Utilities reviewOnly section="metadata" />);
    expect(
      await screen.findByRole("button", { name: "Approve Match" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Reject Match" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Dismiss" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Suggested match").options).toHaveLength(2);
    expect(
      screen.queryByRole("option", { name: /Already handled/ }),
    ).not.toBeInTheDocument();
  });

  it("loads subsequent metadata pages without exposing library maintenance controls", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url.startsWith("/api/metadata/inbox?")) {
        const offset = Number(
          new URL(url, "http://test").searchParams.get("offset"),
        );
        return ok(
          Array.from({ length: offset ? 1 : 21 }, (_, i) => ({
            id: offset + i,
            book_id: offset + i,
            book_title: `Review book ${offset + i}`,
            book_author: "Author",
            status: "open",
            proposed_genre_tags: [],
            possible_missing_series_books: [],
          })),
        );
      }
      if (url === "/api/metadata/jobs/latest") return ok(null);
      return ok([]);
    });
    renderWithClient(<Utilities reviewOnly section="metadata" />);
    expect(await screen.findByText("Review book 0")).toBeInTheDocument();
    expect(screen.queryByText("Review book 20")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Library tool")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(await screen.findByText("Review book 20")).toBeInTheDocument();
    expect(screen.queryByText("Review book 0")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Next/ })).toBeDisabled();
    expect(screen.getByText(/Page 2/)).toBeInTheDocument();
  });
});
