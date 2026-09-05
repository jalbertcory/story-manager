import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AudiobookPipeline from "./AudiobookPipeline";
import { renderWithClient } from "../test-utils";

vi.mock("../hooks/useLifecycleDefinitions", () => ({
  default: () => ({
    data: {
      audiobook_pipeline: {
        states: [
          { value: null, label: "Not started" },
          { value: "ingesting", label: "Ingesting" },
          { value: "roster_gen", label: "Roster" },
          { value: "diarizing", label: "Diarizing" },
          { value: "audio_gen", label: "TTS" },
          { value: "assembling", label: "Assembly" },
          { value: "complete", label: "Complete" },
          { value: "error", label: "Error" },
        ],
        active_states: [
          "ingesting",
          "roster_gen",
          "diarizing",
          "audio_gen",
          "assembling",
        ],
        failure_states: ["error"],
        groups: {
          progress_steps: [
            "ingesting",
            "roster_gen",
            "diarizing",
            "audio_gen",
            "assembling",
            "complete",
          ],
          batchable: ["diarizing", "audio_gen", "assembling"],
          concurrent_analysis: ["diarizing"],
          ready: ["complete"],
          paused: ["paused"],
        },
      },
      imported_audiobook: {
        active_states: ["stale", "queued", "importing", "aligning"],
      },
      chapter_preview: {
        states: [
          { value: null, label: "Not generated" },
          { value: "queued", label: "Queued" },
          { value: "generating", label: "Generating" },
          { value: "ready", label: "Ready" },
          { value: "error", label: "Error" },
        ],
        active_states: ["queued", "generating"],
        failure_states: ["error"],
      },
      sentence: {
        states: [
          { value: "pending_diarization", label: "Pending diarization" },
          { value: "ready_for_audio", label: "Ready for audio" },
          { value: "audio_queued", label: "Audio queued" },
          { value: "audio_generating", label: "Generating audio" },
          { value: "audio_generated", label: "Audio generated" },
          { value: "error", label: "Error" },
        ],
        failure_states: ["error"],
        groups: {
          audio_in_progress: ["audio_queued", "audio_generating"],
          audio_ready: ["ready_for_audio"],
          audio_waiting: ["audio_queued"],
          audio_working: ["audio_generating"],
          audio_playable: ["audio_generated"],
        },
      },
    },
  }),
}));

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
      await screen.findAllByText("EPUB contains no narratable text."),
    ).toHaveLength(2);
    fireEvent.click(
      screen.getByRole("button", { name: "Run Next Stage: Ingesting" }),
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/books/11/audiobook/step", {
        method: "POST",
      });
    });
  });

  it("clearly separates AI audio regeneration from an AI analysis rebuild", async () => {
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/11/audiobook/status") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              pipeline_status: "complete",
              next_phase: "complete",
              pause_requested: false,
              sentence_counts: { audio_generated: 2 },
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
          json: () => Promise.resolve([{ id: 9, sentence_count: 2 }]),
        });
      }
      if (
        (url === "/api/books/11/audiobook/audio/rebuild" ||
          url === "/api/books/11/audiobook/rebuild") &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ queued: true }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(
      <AudiobookPipeline book={{ id: 11, audiobook_enabled: true }} />,
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Regenerate audio only",
      }),
    );
    expect(
      screen.getByText(
        /Character voices, speaker assignments, and imported audiobooks will be kept/,
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Yes, regenerate audio" }),
    );
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/books/11/audiobook/audio/rebuild",
        { method: "POST" },
      );
    });

    fireEvent.change(screen.getByLabelText("AI production view"), {
      target: { value: "progress" },
    });
    fireEvent.click(
      await screen.findByRole("button", { name: "Rebuild AI Audiobook" }),
    );
    expect(
      screen.getByText(
        /Imported human audiobooks and alignments will be preserved/,
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Yes, queue rebuild" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/books/11/audiobook/rebuild",
        { method: "POST" },
      );
    });
  });

  it("shows import times and identifies the reader app default edition", async () => {
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/11/audiobook/imports") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve([
              {
                id: 10,
                name: "Newest narration",
                source_type: "upload",
                status: "ready",
                duration_ms: 3_600_000,
                created_at: "2026-07-02T15:30:00Z",
                is_reader_default: true,
                tracks: [
                  {
                    id: 100,
                    title: "Chapter 1",
                    matched_chapter_id: null,
                    cue_count: 0,
                  },
                ],
              },
              {
                id: 9,
                name: "Older narration",
                source_type: "upload",
                status: "ready",
                duration_ms: 3_600_000,
                created_at: "2026-07-01T15:30:00Z",
                is_reader_default: false,
                tracks: [
                  {
                    id: 90,
                    title: "Chapter 1",
                    matched_chapter_id: null,
                    cue_count: 0,
                  },
                ],
              },
            ]),
        });
      }
      if (url === "/api/books/11/audiobook/status") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ pipeline_status: "complete" }),
        });
      }
      if (
        url === "/api/books/11/audiobook/characters" ||
        url === "/api/books/11/audiobook/chapters"
      ) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (
        url === "/api/imported-audiobooks/10/rematch" &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "stale" }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(
      <AudiobookPipeline book={{ id: 11, audiobook_enabled: true }} />,
    );

    const newestHeading = await screen.findByRole("heading", {
      name: "Newest narration",
    });
    const newestCard = newestHeading.closest("section");
    const olderCard = screen
      .getByRole("heading", { name: "Older narration" })
      .closest("section");
    expect(
      within(newestCard).getByText("Reader app default"),
    ).toBeInTheDocument();
    expect(
      within(olderCard).queryByText("Reader app default"),
    ).not.toBeInTheDocument();
    expect(within(newestCard).getByText(/^Imported /)).toHaveAttribute(
      "datetime",
      "2026-07-02T15:30:00Z",
    );
    expect(within(olderCard).getByText(/^Imported /)).toHaveAttribute(
      "datetime",
      "2026-07-01T15:30:00Z",
    );

    fireEvent.click(
      within(newestCard).getByRole("button", {
        name: "Rematch Newest narration to book text",
      }),
    );
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/imported-audiobooks/10/rematch",
        { method: "POST" },
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Listen & Read" }));
    expect(
      await screen.findByRole("option", { name: "Newest narration" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/imported audio is intact, but it has no synchronized/),
    ).toBeInTheDocument();
  });

  it("routes human audiobook imports through the guided workflow with book context", async () => {
    const fetchMock = vi.fn((url) => {
      if (
        url === "/api/books/11/audiobook/status" ||
        url === "/api/books/11/audiobook/characters" ||
        url === "/api/books/11/audiobook/chapters" ||
        url === "/api/books/11/audiobook/imports"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve(
              url.endsWith("/status") ? { pipeline_status: "complete" } : [],
            ),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(
      <AudiobookPipeline book={{ id: 11, audiobook_enabled: true }} />,
    );

    expect(
      await screen.findByRole("link", {
        name: "Import audio files",
      }),
    ).toHaveAttribute("href", "/import?type=audiobook&book_id=11");
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
              sentence_counts: {
                pending_diarization: 60,
                ready_for_audio: 40,
              },
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
    expect(screen.getByText("Speaker analysis")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("AI production view"), {
      target: { value: "analysis" },
    });
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
      title: "Opening Night",
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

    fireEvent.change(await screen.findByLabelText("AI production view"), {
      target: { value: "chapter-assembly" },
    });
    expect(screen.getByText("Opening Night")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Rebuild Preview" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/books/11/audiobook/chapters/9/preview-audio",
        { method: "POST" },
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Listen & Read" }));
    expect(
      (await screen.findAllByText("Opening Night")).length,
    ).toBeGreaterThan(0);
    expect(
      await screen.findByText("Avery opened the door."),
    ).toBeInTheDocument();
    expect(screen.getByText("The hall was quiet.")).toBeInTheDocument();
    expect(container.querySelector("audio")).toHaveAttribute(
      "src",
      "/api/books/11/audiobook/chapters/9/audio",
    );
  });

  it("queues one ready sentence from the Script Editor and shows its state", async () => {
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/11/audiobook/status") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              pipeline_status: "paused",
              next_phase: "audio_gen",
              pause_requested: false,
              sentence_counts: { ready_for_audio: 1 },
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
          json: () =>
            Promise.resolve([
              {
                id: 9,
                chapter_number: 1,
                sentence_count: 1,
                processed_sentence_count: 1,
              },
            ]),
        });
      }
      if (
        url === "/api/books/11/audiobook/sentences?page=1&limit=50" ||
        url === "/api/books/11/audiobook/sentences?page=1&limit=50&chapter_id=9"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              items: [
                {
                  id: 31,
                  chapter_id: 9,
                  character_id: 4,
                  sequence_order: 0,
                  original_text: "Avery opened the door.",
                  tagged_text: "Avery opened the door.",
                  speaker_confidence: 0.96,
                  speaker_reason: "Explicit attribution",
                  status: "ready_for_audio",
                },
              ],
              total: 1,
            }),
        });
      }
      if (
        url === "/api/books/11/audiobook/sentences/31/generate-audio" &&
        options?.method === "POST"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              status: "audio_queued",
              queued: true,
              sentence_id: 31,
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(<AudiobookPipeline book={{ id: 11 }} />);

    fireEvent.change(await screen.findByLabelText("AI production view"), {
      target: { value: "script-editor" },
    });
    expect(await screen.findByText("Ready for audio")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generate audio" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/books/11/audiobook/sentences/31/generate-audio",
        { method: "POST" },
      );
    });
  });

  it("requires confirmation before changing the TTS engine for a series", async () => {
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/books/11/audiobook/status") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              pipeline_status: "paused",
              next_phase: "audio_gen",
              sentence_counts: { ready_for_audio: 1 },
              tts_provider: "qwen3",
              tts_provider_locked: true,
              available_tts_providers: ["qwen3", "omnivoice"],
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
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      if (
        url === "/api/books/11/audiobook/tts-provider" &&
        options?.method === "PUT"
      ) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({ provider: "omnivoice", scope: "series" }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
    globalThis.fetch = fetchMock;

    renderWithClient(
      <AudiobookPipeline book={{ id: 11, series: "The Saga" }} />,
    );

    fireEvent.change(await screen.findByLabelText("AI production view"), {
      target: { value: "characters" },
    });
    fireEvent.change(screen.getByLabelText("Series TTS engine"), {
      target: { value: "omnivoice" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change engine" }));
    expect(
      screen.getByText(/clears incompatible voices and generated audio/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Yes, change engine" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/books/11/audiobook/tts-provider",
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider: "omnivoice" }),
        },
      );
    });
  });
});
