import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AudiobookPipeline from "./AudiobookPipeline";
import { renderWithClient } from "../test-utils";

describe("AudiobookPipeline", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the actionable error and can run only the next stage", async () => {
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/11/audiobook/status") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              pipeline_status: "error",
              next_phase: "ingesting",
              pause_requested: false,
              stop_after_phase: null,
              last_error: "EPUB contains no narratable text.",
              sentence_counts: {},
            }),
        });
      }
      if (
        url === "/api/books/11/audiobook/characters" ||
        url === "/api/books/11/audiobook/chapters"
      ) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (
        url === "/api/books/11/audiobook/step" &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: "ingesting",
              queued: true,
              stop_after_phase: "ingesting",
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(<AudiobookPipeline book={{ id: 11 }} />);

    expect(
      await screen.findByText("EPUB contains no narratable text."),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Run Next Stage: Ingesting" }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/books/11/audiobook/step", {
        method: "POST",
      });
    });
  });

  it("shows model progress and can run exactly one diarization batch", async () => {
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/11/audiobook/status") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              pipeline_status: "paused",
              next_phase: "diarizing",
              pause_requested: false,
              stop_after_phase: null,
              last_error: null,
              sentence_counts: { pending_diarization: 100 },
              review_counts: {
                low_confidence: 2,
                unassigned: 100,
              },
              progress_current: 40,
              progress_total: 100,
              progress_percent: 40,
              progress_detail: "Chapter 2: attributed 40 of 100 sentences",
              llm_requests: 1,
              llm_provider: "ollama",
              llm_model: "qwen3.5:27b",
              summary: "A test story summary.",
            }),
        });
      }
      if (url === "/api/books/11/audiobook/characters") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (url === "/api/books/11/audiobook/chapters") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve([
              {
                id: 9,
                chapter_number: 2,
                sentence_count: 100,
                processed_sentence_count: 40,
                low_confidence_count: 2,
                summary: "The story begins.",
              },
            ]),
        });
      }
      if (
        url === "/api/books/11/audiobook/run-batch" &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: "diarizing",
              queued: true,
              batch_limit: 1,
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(<AudiobookPipeline book={{ id: 11 }} />);

    expect(await screen.findByText("ollama / qwen3.5:27b")).toBeInTheDocument();
    expect(screen.getAllByText("A test story summary.")).toHaveLength(2);
    expect(screen.getByText("The story begins.")).toBeInTheDocument();
    expect(
      screen.getByText("2 low confidence · 100 unassigned"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run One Batch" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/books/11/audiobook/run-batch",
        { method: "POST" },
      );
    });
  });
});
