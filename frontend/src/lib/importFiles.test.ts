import { describe, expect, it } from "vitest";

import {
  extractEpubsFromEntries,
  isBookFile,
  selectAudiobookFiles,
} from "./importFiles";

const named = (...names: string[]) => names.map((name) => ({ name }));
const names = (files: { name: string }[]) => files.map((file) => file.name);

function fileEntry(name: string): FileSystemEntry {
  return {
    name,
    isFile: true,
    isDirectory: false,
    file: (resolve: (file: File) => void) => resolve(new File(["x"], name)),
  } as unknown as FileSystemEntry;
}

function dirEntry(name: string, children: FileSystemEntry[]): FileSystemEntry {
  return {
    name,
    isFile: false,
    isDirectory: true,
    createReader: () => {
      let read = false;
      return {
        readEntries: (resolve: (entries: FileSystemEntry[]) => void) => {
          resolve(read ? [] : children);
          read = true;
        },
      };
    },
  } as unknown as FileSystemEntry;
}

describe("isBookFile", () => {
  it("accepts EPUB and ZIP files in any case", () => {
    expect(isBookFile("a.EPUB")).toBe(true);
    expect(isBookFile("a.zip")).toBe(true);
    expect(isBookFile("a.pdf")).toBe(false);
  });
});

describe("selectAudiobookFiles", () => {
  it("keeps supported audio, CUE, and ZIP files", () => {
    expect(
      names(selectAudiobookFiles(named("01.MP3", "book.cue", "cover.jpg"))),
    ).toEqual(["01.MP3", "book.cue"]);
    expect(selectAudiobookFiles(null)).toEqual([]);
  });

  it("drops loose tracks when an m4b is selected", () => {
    expect(
      names(
        selectAudiobookFiles(
          named("book.m4b", "01.mp3", "book.cue", "extra.zip", "02.flac"),
        ),
      ),
    ).toEqual(["book.m4b", "book.cue", "extra.zip"]);
  });
});

describe("extractEpubsFromEntries", () => {
  it("collects EPUBs from nested folders and dropped book files", async () => {
    const files = await extractEpubsFromEntries([
      dirEntry("library", [
        fileEntry("one.epub"),
        fileEntry("notes.txt"),
        fileEntry("archive.zip"),
        dirEntry("nested", [fileEntry("two.EPUB")]),
      ]),
      fileEntry("three.zip"),
      fileEntry("four.pdf"),
    ]);
    expect(names(files)).toEqual(["one.epub", "two.EPUB", "three.zip"]);
  });
});
