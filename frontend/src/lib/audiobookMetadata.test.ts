import { describe, expect, it } from "vitest";
import {
  audiobookCueMetadata,
  audiobookFilenameMetadata,
  suggestAudiobookMetadata,
} from "./audiobookMetadata";

describe("audiobook metadata suggestions", () => {
  it("uses Libation folder names instead of track filenames", () => {
    expect(
      audiobookFilenameMetadata([
        {
          name: "audio.m4b",
          webkitRelativePath:
            "Backup/Artemis Fowl Movie Tie-In Edition_ Artemis Fowl, Book 1 [B002V8MYYE]/audio.m4b",
        },
      ]).title,
    ).toBe("Artemis Fowl Movie Tie-In Edition");
  });
  it("does not replace album metadata with chapter-level CUE labels", () => {
    expect(
      audiobookCueMetadata(
        'TITLE "The Book"\nPERFORMER "Author"\nTRACK 1 AUDIO\n TITLE "Opening"\n PERFORMER "Other"',
      ),
    ).toEqual({ title: "The Book", author: "Author" });
  });
  it("suggests CUE metadata without uploading audio", async () => {
    const cue = new File(
      ['TITLE "Tagged Book"\nPERFORMER "Tagged Author"'],
      "book.cue",
    );
    const audio = new File([], "book.m4b");
    expect(await suggestAudiobookMetadata([cue, audio])).toEqual({
      title: "Tagged Book",
      author: "Tagged Author",
    });
  });
  it("keeps the filename fallback if a CUE cannot be read", async () => {
    const cue = Object.assign(new File([], "My Book.cue"), {
      slice: () =>
        Object.assign(new Blob(), {
          text: () => Promise.reject(new Error("unreadable")),
        }),
    });
    expect(await suggestAudiobookMetadata([cue])).toEqual({
      title: "My Book",
      author: "",
    });
  });
});
