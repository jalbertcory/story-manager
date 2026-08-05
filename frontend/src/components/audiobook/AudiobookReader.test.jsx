import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../../test-utils";
import AudiobookReader from "./AudiobookReader";

describe("AudiobookReader", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

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
});
