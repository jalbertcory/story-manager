import { screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { components } from "../api/schema";
import type { CatalogBook } from "../types";
import { jsonResponse, mockFetch, renderWithClient } from "../test-utils";
import UniverseMembership from "./UniverseMembership";
import WebUpdates from "./WebUpdates";
import Utilities from "./Utilities";

type MetadataMatch = components["schemas"]["MetadataMatch"];
type MetadataProposal = components["schemas"]["MetadataProposalSummary"];

const ok = (value: unknown) => Promise.resolve(jsonResponse(value));

const catalogBook = (
  overrides: Partial<CatalogBook> & Pick<CatalogBook, "id" | "title">,
): CatalogBook => ({
  audio_playable: false,
  audiobook_enabled: false,
  audiobook_pipeline_status: null,
  audiobook_types: [],
  author: "Writer",
  cover_path: null,
  current_word_count: null,
  download_status: null,
  effective_genre_tags: null,
  effective_series_genre_tags: null,
  genre_tags: null,
  has_epub: true,
  refresh_status: null,
  series: null,
  series_index: null,
  series_user_genre_tags: null,
  source_type: "web",
  source_url: null,
  universe_id: null,
  universe_name: null,
  updated_at: null,
  user_genre_tags: null,
  ...overrides,
});

const metadataMatch = (
  overrides: Partial<MetadataMatch> & Pick<MetadataMatch, "id">,
): MetadataMatch => ({
  approved_at: null,
  book_id: 1,
  last_checked_at: null,
  match_confidence: null,
  match_issues: null,
  note: null,
  possible_missing_series_books: null,
  proposed_genre_tags: null,
  rejected_at: null,
  remote_author: null,
  remote_ids: null,
  remote_metadata: null,
  remote_title: null,
  remote_url: null,
  source: null,
  status: "pending",
  ...overrides,
});

const proposal = (
  overrides: Partial<MetadataProposal> &
    Pick<MetadataProposal, "id" | "book_id" | "book_title">,
): MetadataProposal => ({
  book_author: "Author",
  book_series: null,
  book_series_index: null,
  candidate_matches: [],
  created_at: "2026-09-04T12:00:00Z",
  match: null,
  note: null,
  possible_missing_series_books: [],
  proposed_genre_tags: [],
  reviewed_at: null,
  status: "open",
  ...overrides,
});

describe("Library workflow actions", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("assigns a series universe and removes standalone membership", async () => {
    mockFetch((url) =>
      ok(
        url === "/api/library/universes"
          ? [
              {
                id: 7,
                name: "Cosmere",
              } satisfies components["schemas"]["UniverseSummary"],
            ]
          : {},
      ),
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
      expect(fetch).toHaveBeenCalledWith(
        "/api/library/universe-membership",
        expect.objectContaining({
          method: "PUT",
          headers: expect.objectContaining({
            "content-type": "application/json",
          }),
          body: JSON.stringify({ name: "Cosmere", series: "Mistborn" }),
        }),
      ),
    );
    unmount();
    renderWithClient(<UniverseMembership bookId={3} currentName="Cosmere" />);
    fireEvent.change(
      screen.getByPlaceholderText("Choose or create a universe"),
      { target: { value: "" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save universe" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/library/universe-membership",
        expect.objectContaining({
          method: "PUT",
          headers: expect.objectContaining({
            "content-type": "application/json",
          }),
          body: JSON.stringify({ name: null, book_id: 3 }),
        }),
      ),
    );
  });

  it("surfaces failed source checks first, filters changes, and retries the affected book", async () => {
    mockFetch((url) => {
      if (url.startsWith("/api/books/catalog?"))
        return ok({
          items: [
            catalogBook({ id: 1, title: "A changed novel" }),
            catalogBook({
              id: 2,
              title: "Z failed novel",
              refresh_status: "error",
            }),
          ],
          next_cursor: null,
          total_count: 2,
          facets: null,
        } satisfies components["schemas"]["BookCatalogPage"]);
      if (url === "/api/library/web-checks")
        return ok([
          {
            id: 1,
            book_id: 1,
            book_title: "A changed novel",
            entry_type: "updated",
            timestamp: "2026-09-04T12:00:00Z",
            previous_chapter_count: 10,
            new_chapter_count: 12,
            words_added: null,
          },
        ] satisfies components["schemas"]["BookLogWithTitle"][]);
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
      expect(fetch).toHaveBeenCalledWith(
        "/api/books/2/refresh",
        expect.objectContaining({
          method: "POST",
        }),
      ),
    );
    fireEvent.change(screen.getByLabelText("Filter web updates"), {
      target: { value: "updated" },
    });
    expect(screen.queryByText("Z failed novel")).not.toBeInTheDocument();
    expect(screen.getByText("A changed novel")).toBeInTheDocument();
  });

  it("only offers pending match decisions in the review queue", async () => {
    const pending = metadataMatch({
      id: 1,
      status: "pending",
      remote_title: "Needs review",
      remote_author: "Author",
    });
    mockFetch((url) => {
      if (url.startsWith("/api/metadata/inbox?"))
        return ok([
          proposal({
            id: 1,
            book_id: 1,
            book_title: "Reviewable book",
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
          }),
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
    expect(
      screen.getByLabelText<HTMLSelectElement>("Suggested match").options,
    ).toHaveLength(2);
    expect(
      screen.queryByRole("option", { name: /Already handled/ }),
    ).not.toBeInTheDocument();
  });

  it("loads subsequent metadata pages without exposing library maintenance controls", async () => {
    mockFetch((url) => {
      if (url.startsWith("/api/metadata/inbox?")) {
        const offset = Number(
          new URL(url, "http://test").searchParams.get("offset"),
        );
        return ok(
          Array.from({ length: offset ? 1 : 21 }, (_, i) =>
            proposal({
              id: offset + i,
              book_id: offset + i,
              book_title: `Review book ${offset + i}`,
            }),
          ),
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
