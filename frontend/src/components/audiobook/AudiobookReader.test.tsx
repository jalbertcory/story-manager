import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockFetch, renderWithClient } from "../../test-utils";
import AudiobookReader from "./AudiobookReader";
import AudiobookSources from "./AudiobookSources";
import type { Chapter, Character, ImportedEdition } from "./types";

type Track = ImportedEdition["tracks"][number];

const chapterFixture = (overrides: Partial<Chapter> = {}): Chapter => ({
  id: 9,
  book_id: 11,
  chapter_number: 1,
  title: "Chapter 1",
  content_file_name: null,
  audio_file_path: null,
  smil_file_path: null,
  needs_reassembly: false,
  sentence_count: 0,
  processed_sentence_count: 0,
  audio_generated_count: 0,
  low_confidence_count: 0,
  preview_status: null,
  preview_error: null,
  summary: null,
  summary_updated_at: null,
  ...overrides,
});

const characterFixture = (overrides: Partial<Character> = {}): Character => ({
  id: 10,
  book_id: 11,
  name: "Narrator",
  aliases: null,
  description: null,
  evidence: null,
  is_narrator: false,
  sentence_count: 0,
  average_confidence: null,
  series_character_id: null,
  shared_series_name: null,
  tts_seed: null,
  tts_voice_id: null,
  tts_voice_provider: null,
  voice_prompt: null,
  ...overrides,
});

const trackFixture = (id: number, overrides: Partial<Track> = {}): Track => ({
  id,
  title: `Chapter ${id}`,
  sequence_order: id - 1,
  audio_url: `${id}.mp3`,
  cues_url: `/api/imported-audiobooks/7/tracks/${id}/cues`,
  smil_url: null,
  media_type: "audio/mpeg",
  duration_ms: 1000,
  source_start_ms: 0,
  source_end_ms: 1000,
  cue_count: 0,
  alignment_score: null,
  match_method: null,
  matched_chapter_id: null,
  matched_chapter_title: null,
  ...overrides,
});

const editionFixture = (
  overrides: Partial<ImportedEdition> = {},
): ImportedEdition => ({
  id: 7,
  book_id: 11,
  name: "Narration",
  source_type: "upload",
  status: "ready",
  error: null,
  created_at: "2026-07-01T15:30:00Z",
  duration_ms: 2000,
  audio_size_bytes: 0,
  source_size_bytes: null,
  source_manifest_sha256: null,
  original_filenames: [],
  asin: null,
  is_reader_default: true,
  alignment_method: null,
  alignment_error: null,
  matching_error: null,
  progress_current: 0,
  progress_total: 0,
  progress_detail: null,
  pipeline_version: 1,
  derived_format_version: 1,
  derived_revision: 1,
  needs_rebuild: false,
  needs_upgrade: false,
  state: "ready_estimated",
  state_label: "Human audio",
  state_detail: null,
  next_action: null,
  next_action_label: null,
  tracks: [],
  ...overrides,
});

describe("AudiobookReader", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("never skips an unmatched track between synchronized tracks", () => {
    mockFetch(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve([]) }),
    );
    const { container } = renderWithClient(
      <AudiobookReader
        bookId={11}
        imports={[
          editionFixture({
            tracks: [
              trackFixture(3, { cue_count: 10 }),
              trackFixture(1, { cue_count: 10 }),
              trackFixture(2),
            ],
          }),
        ]}
      />,
    );
    expect(screen.getByLabelText("Chapter", { exact: true })).toHaveValue("1");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByLabelText("Chapter", { exact: true })).toHaveValue("2");
    expect(container.querySelector("audio")).toHaveAttribute("src", "2.mp3");
    expect(screen.getByRole("status")).toHaveTextContent(
      "no narration is skipped",
    );
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByLabelText("Chapter", { exact: true })).toHaveValue("3");
  });

  it("blocks an unsafe edition even when its old status says ready", () => {
    const { container } = renderWithClient(
      <AudiobookReader
        bookId={11}
        imports={[
          editionFixture({
            matching_error:
              "Chapter matching needs review. 84 numbered chapters have no audio match.",
            tracks: [trackFixture(1, { cue_count: 200 })],
          }),
        ]}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Chapter matching needs review",
    );
    expect(container.querySelector("audio")).toBeNull();
  });

  it("leads a blocked edition with its match review", () => {
    const error = "Chapter matching needs review. Too few tracks match.";
    renderWithClient(
      <AudiobookSources
        bookId={11}
        imports={[
          editionFixture({
            status: "error",
            matching_error: error,
            error,
            alignment_error: error,
            is_reader_default: false,
            state: "needs_review",
            state_label: "Needs match review",
            state_detail: error,
            next_action: "review_matches",
            next_action_label: "Review matches",
            tracks: [trackFixture(1)],
          }),
        ]}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(error);
    expect(screen.getAllByText(error)).toHaveLength(1);
    expect(screen.getByText("Needs match review")).toHaveClass(
      "audio-state--danger",
    );
    expect(
      screen.getByRole("button", { name: "Rematch Narration to book text" }),
    ).toHaveClass("btn-primary");
    // Track matching opens with the problem; alignment waits for valid matches.
    expect(
      screen.getByText("Track matching and more options").closest("details"),
    ).toHaveAttribute("open");
    expect(
      screen.getByRole("combobox", { name: "Book chapter for Chapter 1" }),
    ).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Whisper/ })).toBeNull();
    expect(screen.queryByText("Reader app default")).not.toBeInTheDocument();
  });

  it("offers Retry import when an import failed after writing tracks", async () => {
    const fetchMock = mockFetch(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    );
    // The live match check also fails for a partial import; that used to hide
    // the retry button.
    renderWithClient(
      <AudiobookSources
        bookId={11}
        imports={[
          editionFixture({
            status: "error",
            error: "ffmpeg exited with status 1",
            matching_error:
              "Chapter matching needs review. No complete audio-to-text match is available.",
            is_reader_default: false,
            state: "import_failed",
            state_label: "Import failed",
            state_detail: "ffmpeg exited with status 1",
            next_action: "retry_import",
            next_action_label: "Retry import",
            tracks: [trackFixture(1)],
          }),
        ]}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "ffmpeg exited with status 1",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry import" }));
    expect(
      await screen.findByText(/Human audiobook import retry queued/),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/imported-audiobooks/7/retry",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it.each([
    ["outdated", "Rebuild", "rebuild"],
    ["whisper_failed", "Retry Whisper", "align"],
    ["ready_estimated", "Improve with Whisper", "align"],
  ] as const)(
    "queues the %s edition's next action",
    async (state, label, endpoint) => {
      const fetchMock = mockFetch(() =>
        Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
      );
      const nextAction =
        state === "outdated"
          ? "rebuild"
          : state === "whisper_failed"
            ? "retry_whisper"
            : "improve_with_whisper";
      renderWithClient(
        <AudiobookSources
          bookId={11}
          imports={[
            editionFixture({
              state,
              state_label: "Label",
              state_detail: "Detail",
              next_action: nextAction,
              next_action_label: label,
              alignment_method: "estimated",
              tracks: [trackFixture(1, { matched_chapter_id: 9 })],
            }),
          ]}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: label }));
      await screen.findByText(/queued/);
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/imported-audiobooks/7/${endpoint}`,
        expect.objectContaining({ method: "POST" }),
      );
      // The primary action is not repeated under more options.
      expect(
        screen.getAllByRole("button", { name: /Whisper|^Rebuild$/ }),
      ).toHaveLength(1);
    },
  );

  it("points to transcription settings instead of a Whisper button", () => {
    renderWithClient(
      <AudiobookSources
        bookId={11}
        imports={[
          editionFixture({
            alignment_method: "estimated",
            state_detail: "Sentence timing is estimated from text length.",
            next_action: "set_up_transcription",
            next_action_label: "Set up transcription",
            tracks: [trackFixture(1, { matched_chapter_id: 9 })],
          }),
        ]}
      />,
    );
    expect(
      screen.getByRole("link", { name: "Set up transcription" }),
    ).toHaveAttribute("href", "/settings/audio-ai");
    expect(screen.queryByRole("button", { name: /Whisper/ })).toBeNull();
    expect(screen.getByText("Reader app default")).toBeInTheDocument();
    expect(screen.getByText("Human audio")).toHaveClass("audio-state--neutral");
  });

  it.each(["imported", "generated"] as const)(
    "keeps the %s chapter picker and navigation in sync",
    async (kind) => {
      mockFetch(() =>
        Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve(kind === "imported" ? [] : { items: [], total: 0 }),
        }),
      );
      const chapters = [1, 2].map((id) =>
        chapterFixture({
          id,
          chapter_number: id,
          title: `Chapter ${id}`,
          audio_file_path: `${id}.mp3`,
        }),
      );
      const imports = [
        editionFixture({
          tracks: [1, 2].map((id) => trackFixture(id, { cue_count: 200 })),
        }),
      ];
      renderWithClient(
        <AudiobookReader
          bookId={11}
          aiEnabled={kind === "generated"}
          chapters={kind === "generated" ? chapters : []}
          imports={kind === "imported" ? imports : []}
        />,
      );
      const picker = screen.getByLabelText("Chapter", { exact: true });
      expect(picker).toHaveValue("1");
      fireEvent.change(picker, { target: { value: "2" } });
      expect(
        screen.getByRole("heading", { name: "Chapter 2" }),
      ).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Chapter 2" })).toHaveAttribute(
        "aria-current",
        "true",
      );
      fireEvent.click(screen.getByRole("button", { name: "Previous" }));
      expect(picker).toHaveValue("1");
      expect(
        screen.queryByText(/synchronized passages/),
      ).not.toBeInTheDocument();
    },
  );

  it("groups synchronized sentences into their original book paragraphs", async () => {
    mockFetch(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            items: [
              {
                id: 1,
                original_text: "First sentence.",
                character_id: 10,
                audio_duration_ms: 1000,
                reading_block_index: 4,
                reading_block_type: "paragraph",
              },
              {
                id: 2,
                original_text: "Still the first paragraph.",
                character_id: 10,
                audio_duration_ms: 1000,
                reading_block_index: 4,
                reading_block_type: "paragraph",
              },
              {
                id: 3,
                original_text: "A new paragraph.",
                character_id: 10,
                audio_duration_ms: 1000,
                reading_block_index: 5,
                reading_block_type: "paragraph",
              },
            ],
            total: 3,
          }),
      }),
    );

    const { container } = renderWithClient(
      <AudiobookReader
        bookId={11}
        aiEnabled
        chapters={[
          chapterFixture({ audio_file_path: "chapter.mp3", sentence_count: 3 }),
        ]}
        characters={[characterFixture()]}
      />,
    );

    await screen.findByText("First sentence.");
    const paragraphs = container.querySelectorAll(
      ".audiobook-reader-block--paragraph",
    );
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]).toHaveTextContent(
      "First sentence. Still the first paragraph.",
    );
    expect(paragraphs[1]).toHaveTextContent("A new paragraph.");
  });
  it("loads every page of sentences for long chapters", async () => {
    const sentence = (id: number) => ({
      id,
      original_text: `Sentence ${id}.`,
      character_id: 10,
      audio_duration_ms: 1000,
      reading_block_index: id,
      reading_block_type: "paragraph",
    });
    const requestedPages: number[] = [];
    mockFetch((url) => {
      const page = Number(
        new URL(url, "http://localhost").searchParams.get("page"),
      );
      requestedPages.push(page);
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            items: page === 1 ? [sentence(1)] : [sentence(1001)],
            total: 2,
          }),
      });
    });

    renderWithClient(
      <AudiobookReader
        bookId={11}
        aiEnabled
        chapters={[chapterFixture({ audio_file_path: "chapter.mp3" })]}
        characters={[characterFixture()]}
      />,
    );

    expect(await screen.findByText("Sentence 1001.")).toBeInTheDocument();
    expect(screen.getByText("Sentence 1.")).toBeInTheDocument();
    expect(requestedPages).toEqual([1, 2]);
  });

  it("plays audio-only tracks without requesting synchronized text", () => {
    const fetchMock = mockFetch();
    const { container } = renderWithClient(
      <AudiobookReader
        bookId={11}
        audioOnly
        imports={[
          editionFixture({
            id: 1,
            name: "Audio only",
            tracks: [1, 2].map((id) =>
              trackFixture(id, {
                title: `Track ${id}`,
                audio_url: `/audio/${id}`,
              }),
            ),
          }),
        ]}
      />,
    );
    expect(container.querySelector("audio")).toHaveAttribute("src", "/audio/1");
    fireEvent.change(screen.getByRole("combobox", { name: /Chapter/ }), {
      target: { value: "2" },
    });
    expect(container.querySelector("audio")).toHaveAttribute("src", "/audio/2");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByText(/Click any sentence/)).not.toBeInTheDocument();
  });
});
