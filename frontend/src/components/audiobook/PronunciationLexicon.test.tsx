import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PronunciationLexicon from "./PronunciationLexicon";
import { jsonResponse, mockFetch, renderWithClient } from "../../test-utils";

const rule = (overrides: object = {}) => ({
  id: 1,
  scope: "series",
  book_id: null,
  series_name: "Saga",
  term: "Cian",
  spoken: "KEE-an",
  case_sensitive: false,
  active: true,
  sentence_count: 12,
  ...overrides,
});

describe("PronunciationLexicon", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("lists rules and marks overridden ones", async () => {
    mockFetch(() =>
      Promise.resolve(
        jsonResponse({
          series_name: "Saga",
          rules: [
            rule({ active: false }),
            rule({ id: 2, scope: "book", book_id: 7, spoken: "KY-an" }),
          ],
        }),
      ),
    );

    renderWithClient(
      <PronunciationLexicon bookId={7} pipelineActive={false} />,
    );

    expect(await screen.findByText("KY-an")).toBeInTheDocument();
    expect(screen.getByText("Series: Saga")).toBeInTheDocument();
    expect(screen.getByText(/overridden by a closer rule/)).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Every book in Saga" }),
    ).toBeInTheDocument();
  });

  it("adds a pronunciation and reports re-narrated sentences", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (init?.method === "POST")
        return Promise.resolve(
          jsonResponse(
            { rule: rule(), sentences_reset: 3, books_affected: 2 },
            201,
          ),
        );
      return Promise.resolve(jsonResponse({ series_name: "Saga", rules: [] }));
    });

    renderWithClient(
      <PronunciationLexicon bookId={7} pipelineActive={false} />,
    );

    await screen.findByText("No pronunciations yet.");
    fireEvent.change(screen.getByLabelText("Written in the book"), {
      target: { value: "Cian" },
    });
    fireEvent.change(screen.getByLabelText("Say it as"), {
      target: { value: "KEE-an" },
    });
    fireEvent.change(screen.getByLabelText("Applies to"), {
      target: { value: "series" },
    });
    fireEvent.click(screen.getByLabelText(/Narrate already-recorded/));
    fireEvent.click(screen.getByRole("button", { name: "Add pronunciation" }));

    expect(
      await screen.findByText(/3 recorded sentences across 2 books/),
    ).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(post?.[0]).toBe("/api/books/7/audiobook/pronunciations");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      term: "Cian",
      spoken: "KEE-an",
      scope: "series",
      case_sensitive: false,
      regenerate: true,
    });
  });

  it("never asks to redo recorded sentences while narration runs", async () => {
    const fetchMock = mockFetch((url, init) => {
      if (init?.method === "DELETE")
        return Promise.resolve(
          jsonResponse({ rule: null, sentences_reset: 0, books_affected: 0 }),
        );
      return Promise.resolve(
        jsonResponse({ series_name: null, rules: [rule({ scope: "global" })] }),
      );
    });

    renderWithClient(<PronunciationLexicon bookId={7} pipelineActive />);

    fireEvent.click(await screen.findByRole("button", { name: "Remove Cian" }));
    expect(screen.getByLabelText(/Narrate already-recorded/)).toBeDisabled();

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url, init]) =>
            init?.method === "DELETE" &&
            url === "/api/audiobook/pronunciations/1?regenerate=false",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("Removed “Cian”.")).toBeInTheDocument();
  });
});
