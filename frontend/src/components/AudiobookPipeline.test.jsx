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

  it("queues a manual chapter preview and exposes playable text and audio", async () => {
    const chapter = {
      id: 9,
      chapter_number: 1,
      sentence_count: 2,
      processed_sentence_count: 2,
      audio_generated_count: 0,
      low_confidence_count: 0,
      summary: "The opening scene.",
      preview_status: null,
      preview_error: null,
      audio_file_path: "audiobooks/11/chapter_1.mp3",
      smil_file_path: "audiobooks/11/chapter_1.smil",
      needs_reassembly: false,
    };
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/11/audiobook/status") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              pipeline_status: "paused",
              next_phase: "audio_gen",
              pause_requested: false,
              sentence_counts: { pending_audio: 2 },
            }),
        });
      }
      if (url === "/api/books/11/audiobook/characters") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([{ id: 4, name: "Avery" }]),
        });
      }
      if (url === "/api/books/11/audiobook/chapters") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([chapter]),
        });
      }
      if (
        url === "/api/books/11/audiobook/chapters/9/preview-audio" &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ queued: true }),
        });
      }
      if (
        url ===
        "/api/books/11/audiobook/sentences?page=1&limit=1000&chapter_id=9"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 1,
                  original_text: "Avery opened the door.",
                  character_id: 4,
                },
                {
                  id: 2,
                  original_text: "The hall was quiet.",
                  character_id: null,
                },
              ],
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    const { container } = renderWithClient(
      <AudiobookPipeline book={{ id: 11, series: "The Saga" }} />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Chapter Assembly" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Rebuild Preview" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/books/11/audiobook/chapters/9/preview-audio",
        { method: "POST" },
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Listen & Read" }));
    expect(
      await screen.findByText("Avery opened the door."),
    ).toBeInTheDocument();
    expect(screen.getByText("The hall was quiet.")).toBeInTheDocument();
    expect(container.querySelector("audio")).toHaveAttribute(
      "src",
      "/api/books/11/audiobook/chapters/9/audio",
    );
  });
});
