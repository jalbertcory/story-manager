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

  it("previews the whole backup and uploads only matched preferred audio", async () => {
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
      throw new Error(`Unexpected request: ${url}`);
    });

    renderWithClient(<LibationBackupImport />);
    fireEvent.change(screen.getByLabelText("Libation backup directory"), {
      target: { files: [matchedM4b, duplicateMp3, unmatchedM4b] },
    });

    expect(await screen.findByText("1 selected to import")).toBeInTheDocument();
    expect(screen.getByText("No library match")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Import 1 Selected Book" }),
    );

    await waitFor(() => {
      expect(
        screen.getByText("Queued 1 of 1 matched books."),
      ).toBeInTheDocument();
    });
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("lets the user review a suggestion before including an unmatched book", async () => {
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

    expect(await screen.findByText("0 selected to import")).toBeInTheDocument();
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
      expect(
        screen.getByText("Queued 1 of 1 matched books."),
      ).toBeInTheDocument();
    });
  });
});
