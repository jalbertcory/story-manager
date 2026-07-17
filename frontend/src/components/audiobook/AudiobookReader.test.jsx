import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../../test-utils";
import AudiobookReader from "./AudiobookReader";

describe("AudiobookReader", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("highlights the sentence at the playback time and scrolls it to the top", async () => {
    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            items: [
              {
                id: 1,
                original_text: "The first sentence.",
                character_id: 4,
                audio_duration_ms: 1000,
              },
              {
                id: 2,
                original_text: "The second sentence.",
                character_id: null,
                audio_duration_ms: 2000,
              },
            ],
          }),
      }),
    );

    const { container } = renderWithClient(
      <AudiobookReader
        bookId={11}
        chapters={[
          {
            id: 9,
            chapter_number: 1,
            title: "CHAPTER ONE",
            sentence_count: 2,
            audio_file_path: "audiobooks/11/chapter_1.mp3",
            needs_reassembly: false,
          },
        ]}
        characters={[{ id: 4, name: "Avery" }]}
      />,
    );

    const firstSentence = await screen.findByText("The first sentence.");
    const secondSentence = screen.getByText("The second sentence.");
    expect(screen.getAllByText("CHAPTER ONE")).toHaveLength(2);
    expect(firstSentence).toHaveAttribute("aria-current", "true");
    expect(firstSentence).toHaveClass("audiobook-reader-sentence--active");

    const transcript = container.querySelector(".audiobook-reader-text");
    const audio = container.querySelector("audio");
    transcript.scrollTo = vi.fn();
    Object.defineProperty(transcript, "scrollTop", {
      configurable: true,
      value: 20,
    });
    vi.spyOn(transcript, "getBoundingClientRect").mockReturnValue({
      top: 100,
    });
    vi.spyOn(secondSentence, "getBoundingClientRect").mockReturnValue({
      top: 260,
    });
    Object.defineProperty(audio, "currentTime", {
      configurable: true,
      value: 1.25,
    });

    fireEvent.timeUpdate(audio);

    await waitFor(() => {
      expect(secondSentence).toHaveAttribute("aria-current", "true");
    });
    expect(firstSentence).not.toHaveAttribute("aria-current");
    expect(secondSentence).toHaveClass("audiobook-reader-sentence--active");
    expect(transcript.scrollTo).toHaveBeenLastCalledWith({
      top: 180,
      behavior: "smooth",
    });

    fireEvent.change(screen.getByLabelText("Speed"), {
      target: { value: "1.5" },
    });
    expect(audio.playbackRate).toBe(1.5);
  });
});
