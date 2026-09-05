import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../../test-utils";
import AudiobookReader from "./AudiobookReader";

describe("AudiobookReader", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it.each(["imported", "generated"])(
    "keeps the %s chapter picker and navigation in sync",
    async (kind) => {
      globalThis.fetch = vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve(kind === "imported" ? [] : { items: [], total: 0 }),
        }),
      );
      const chapters = [1, 2].map((id) => ({
        id,
        chapter_number: id,
        title: `Chapter ${id}`,
        audio_file_path: `${id}.mp3`,
        needs_reassembly: false,
      }));
      const imports = [
        {
          id: 7,
          name: "Narration",
          status: "ready",
          tracks: [1, 2].map((id) => ({
            id,
            title: `Chapter ${id}`,
            cue_count: 200,
            audio_url: `${id}.mp3`,
            source_start_ms: 0,
            source_end_ms: 1000,
          })),
        },
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
        screen.getByRole("heading", { name: "Chapter 2", exact: true }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Next", exact: true }),
      ).toBeDisabled();
      expect(
        screen.getByRole("button", { name: "Chapter 2", exact: true }),
      ).toHaveAttribute("aria-current", "true");
      fireEvent.click(
        screen.getByRole("button", { name: "Previous", exact: true }),
      );
      expect(picker).toHaveValue("1");
      expect(
        screen.queryByText(/synchronized passages/),
      ).not.toBeInTheDocument();
    },
  );

  it("groups synchronized sentences into their original book paragraphs", async () => {
    globalThis.fetch = vi.fn(() =>
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
          {
            id: 9,
            chapter_number: 1,
            title: "Chapter 1",
            audio_file_path: "chapter.mp3",
            needs_reassembly: false,
            sentence_count: 3,
          },
        ]}
        characters={[{ id: 10, name: "Narrator" }]}
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
  it("plays audio-only tracks without requesting synchronized text", () => {
    globalThis.fetch = vi.fn();
    const { container } = renderWithClient(
      <AudiobookReader
        audioOnly
        imports={[
          {
            id: 1,
            name: "Audio only",
            status: "ready",
            tracks: [1, 2].map((id) => ({
              id,
              title: `Track ${id}`,
              cue_count: 0,
              audio_url: `/audio/${id}`,
              source_start_ms: 0,
              source_end_ms: 1000,
            })),
          },
        ]}
      />,
    );
    expect(container.querySelector("audio")).toHaveAttribute("src", "/audio/1");
    fireEvent.change(screen.getByRole("combobox", { name: /Chapter/ }), {
      target: { value: "2" },
    });
    expect(container.querySelector("audio")).toHaveAttribute("src", "/audio/2");
    expect(globalThis.fetch).not.toHaveBeenCalled();
    expect(screen.queryByText(/Click any sentence/)).not.toBeInTheDocument();
  });
});
