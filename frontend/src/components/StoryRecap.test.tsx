import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import StoryRecap from "./StoryRecap";
import { jsonResponse, mockFetch, renderWithClient } from "../test-utils";

const entry = (kind: string, overrides: object = {}) => ({
  kind,
  recap: null,
  stale: false,
  updated_at: null,
  llm_model: null,
  covered_books: [],
  ...overrides,
});

const recaps = (overrides: object = {}) => ({
  book_id: 7,
  series: "Saga",
  llm_configured: true,
  book: entry("book", { covered_books: [{ id: 7, title: "Second" }] }),
  story_so_far: entry("story_so_far", {
    covered_books: [{ id: 6, title: "First", series_index: 1 }],
  }),
  active_job: null,
  last_error: null,
  ...overrides,
});

describe("StoryRecap", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a written recap, what it covers and when it is out of date", async () => {
    mockFetch(() =>
      Promise.resolve(
        jsonResponse(
          recaps({
            story_so_far: entry("story_so_far", {
              recap: "Ann left home.\n\nShe found the gate.",
              stale: true,
              llm_model: "tiny",
              updated_at: "2026-11-20T00:00:00Z",
              covered_books: [{ id: 6, title: "First", series_index: 1 }],
            }),
          }),
        ),
      ),
    );

    renderWithClient(<StoryRecap bookId={7} />);

    expect(await screen.findByText("She found the gate.")).toBeInTheDocument();
    expect(
      screen.getByText("Covers First. Nothing from this book."),
    ).toBeInTheDocument();
    expect(screen.getByText(/earlier books have changed/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rewrite recap: The story so far" }),
    ).toBeEnabled();
  });

  it("queues a recap", async () => {
    const fetchMock = mockFetch((_url, init) =>
      Promise.resolve(
        init?.method === "POST"
          ? jsonResponse({ id: 3, job_type: "story_recap" }, 202)
          : jsonResponse(recaps()),
      ),
    );

    renderWithClient(<StoryRecap bookId={7} />);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Write recap: The story so far",
      }),
    );

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(([, init]) => init?.method === "POST"),
      ).toBe(true),
    );
    const post = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(post?.[0]).toBe("/api/books/7/recap");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      kind: "story_so_far",
      force: false,
    });
  });

  it("explains when no language model is set up and hides series recaps for a first book", async () => {
    mockFetch(() =>
      Promise.resolve(
        jsonResponse(
          recaps({
            llm_configured: false,
            last_error: "The model timed out.",
            story_so_far: entry("story_so_far"),
          }),
        ),
      ),
    );

    renderWithClient(<StoryRecap bookId={7} />);

    expect(
      await screen.findByText(/written by a language model/),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("The model timed out.");
    expect(screen.queryByText("The story so far")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Write recap: This book" }),
    ).toBeDisabled();
  });
});
