import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../test-utils";
import LibationBackupImport from "./LibationBackupImport";

function backupFile(name, relativePath) {
  const file = new File(["audio"], name, { type: "audio/mp4" });
  Object.defineProperty(file, "webkitRelativePath", {
    configurable: true,
    value: relativePath,
  });
  return file;
}

describe("LibationBackupImport", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("imports matched and audio-only books together using preferred audio", async () => {
    const matchedM4b = backupFile(
      "Matched.m4b",
      "Backup/Matched Book [B012345678]/Matched.m4b",
    );
    const duplicateMp3 = backupFile(
      "Matched.mp3",
      "Backup/Matched Book [B012345678]/Matched.mp3",
    );
    const unmatchedM4b = backupFile(
      "Unknown.m4b",
      "Backup/Unknown Book [B111111111]/Unknown.m4b",
    );

    globalThis.fetch = vi.fn((url, options) => {
      if (url === "/api/audiobook/libation-backup/preview") {
        expect(JSON.parse(options.body).source_paths).toEqual([
          "Backup/Matched Book [B012345678]/Matched.m4b",
          "Backup/Matched Book [B012345678]/Matched.mp3",
          "Backup/Unknown Book [B111111111]/Unknown.m4b",
        ]);
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              matched_count: 1,
              unmatched_count: 1,
              ambiguous_count: 0,
              already_imported_count: 0,
              ignored_file_count: 0,
              groups: [
                {
                  source_key: "Backup/Matched Book [B012345678]",
                  folder_name: "Matched Book [B012345678]",
                  source_title: "Matched Book",
                  product_id: "B012345678",
                  file_count: 2,
                  status: "matched",
                  match_method: "title",
                  book_id: 7,
                  book_title: "Matched Book",
                  book_author: "Writer",
                },
                {
                  source_key: "Backup/Unknown Book [B111111111]",
                  folder_name: "Unknown Book [B111111111]",
                  source_title: "Unknown Book",
                  product_id: "B111111111",
                  file_count: 1,
                  status: "unmatched",
                  detail: "No library book has the same identifier or title.",
                },
              ],
            }),
        });
      }
      if (url === "/api/books/7/audiobook/imports") {
        expect(options.body.getAll("files").map((file) => file.name)).toEqual([
          "Matched.m4b",
        ]);
        expect(options.body.get("auto_align")).toBe("true");
        expect(options.body.get("name")).toBe("Libation · B012345678");
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ id: 19 }),
        });
      }
      if (url === "/api/audiobooks/upload") {
        expect(options.body.getAll("files")).toEqual([unmatchedM4b]);
        expect(options.body.get("title")).toBe("Unknown Book");
        expect(options.body.get("auto_align")).toBe("false");
        return Promise.resolve({ ok: true, json: async () => ({ id: 20 }) });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    renderWithClient(<LibationBackupImport />);
    fireEvent.change(screen.getByLabelText("Libation backup directory"), {
      target: { files: [matchedM4b, duplicateMp3, unmatchedM4b] },
    });

    expect(await screen.findByText("2 selected to import")).toBeInTheDocument();
    expect(screen.getByText("Audio only")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Import 2 Selected Books" }),
    );

    await waitFor(() => {
      expect(screen.getByText("Queued 2 of 2 books.")).toBeInTheDocument();
    });
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
  });

  it("lets the user attach an automatically selected audio-only book to a suggested match", async () => {
    const audiobook = backupFile(
      "Rhythm.m4b",
      "Backup/Rhythm of War [1250759781]/Rhythm.m4b",
    );

    globalThis.fetch = vi.fn((url) => {
      if (url === "/api/audiobook/libation-backup/preview") {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              matched_count: 0,
              unmatched_count: 1,
              ambiguous_count: 0,
              already_imported_count: 0,
              ignored_file_count: 0,
              library_books: [
                {
                  book_id: 9,
                  book_title: "Rhythm of War (The Stormlight Archive)",
                  book_author: "Brandon Sanderson",
                },
              ],
              groups: [
                {
                  source_key: "Backup/Rhythm of War [1250759781]",
                  source_title: "Rhythm of War",
                  product_id: "1250759781",
                  status: "unmatched",
                  candidates: [
                    {
                      book_id: 9,
                      book_title: "Rhythm of War (The Stormlight Archive)",
                      book_author: "Brandon Sanderson",
                      match_score: 0.98,
                    },
                  ],
                },
              ],
            }),
        });
      }
      if (url === "/api/books/9/audiobook/imports") {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ id: 20 }),
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    renderWithClient(<LibationBackupImport />);
    fireEvent.change(screen.getByLabelText("Libation backup directory"), {
      target: { files: [audiobook] },
    });

    expect(await screen.findByText("1 selected to import")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Rhythm of War (The Stormlight Archive) by Brandon Sanderson",
      }),
    );
    expect(screen.getByText("1 selected to import")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Import 1 Selected Book" }),
    );

    await waitFor(() => {
      expect(screen.getByText("Queued 1 of 1 books.")).toBeInTheDocument();
    });
  });

  it("clearly shows existing human audio and skips another edition by default", async () => {
    const audiobook = backupFile(
      "Matched.m4b",
      "Backup/Matched Book [B012345678]/Matched.m4b",
    );
    const existingAudio = {
      edition_id: 22,
      name: "Existing Libation audio",
      status: "ready",
      source_type: "libation",
      product_id: "B999999999",
    };

    globalThis.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            matched_count: 1,
            unmatched_count: 0,
            ambiguous_count: 0,
            already_imported_count: 0,
            existing_audio_match_count: 1,
            ignored_file_count: 0,
            library_books: [
              {
                book_id: 7,
                book_title: "Matched Book (Series Name)",
                book_author: "Writer",
                existing_audiobooks: [existingAudio],
              },
            ],
            groups: [
              {
                source_key: "Backup/Matched Book [B012345678]",
                source_title: "Matched Book",
                product_id: "B012345678",
                status: "matched",
                match_method: "title_variant",
                book_id: 7,
                book_title: "Matched Book (Series Name)",
                book_author: "Writer",
                existing_audiobooks: [existingAudio],
              },
            ],
          }),
      }),
    );

    renderWithClient(<LibationBackupImport />);
    fireEvent.change(screen.getByLabelText("Libation backup directory"), {
      target: { files: [audiobook] },
    });

    expect(await screen.findByText("0 selected to import")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "1 already have human audio",
    );
    expect(
      screen.getByText("This library book already has human audio."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Existing Libation audio · ready · B999999999"),
    ).toBeInTheDocument();
    expect(screen.getByText("Already has audio — skipped")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open existing audio" }),
    ).toHaveAttribute("href", "/books/7/audiobooks?tab=sources");

    fireEvent.click(
      screen.getByRole("checkbox", {
        name: "Import another audio edition anyway",
      }),
    );
    expect(screen.getByText("1 selected to import")).toBeInTheDocument();
  });
  it("can import an unmatched Libation book as audio only", async () => {
    const file = backupFile(
      "New Book.m4b",
      "Backup/New Book [B012345678]/New Book.m4b",
    );
    globalThis.fetch = vi.fn(async (url, options) => {
      if (url.endsWith("/preview"))
        return {
          ok: true,
          json: async () => ({
            groups: [
              {
                source_key: "Backup/New Book [B012345678]",
                source_title: "New Book",
                product_id: "B012345678",
                status: "unmatched",
                candidates: [],
                existing_audiobooks: [],
              },
            ],
            library_books: [],
          }),
        };
      expect(url).toBe("/api/audiobooks/upload");
      expect(options.body.get("title")).toBe("New Book");
      expect(options.body.get("auto_align")).toBe("false");
      expect(options.body.getAll("files")).toEqual([file]);
      return { ok: true, json: async () => ({ id: 5, book_id: 8 }) };
    });
    renderWithClient(<LibationBackupImport />);
    fireEvent.change(screen.getByLabelText("Libation backup directory"), {
      target: { files: [file] },
    });
    await screen.findByText("1 selected to import");
    expect(
      screen.queryByLabelText("Import as a new audio-only book"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Import 1 Selected Book" }),
    );
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
  });
});
