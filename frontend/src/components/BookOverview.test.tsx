import { fireEvent, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithClient } from "../test-utils";
import { getOriginalBookFiles } from "../api/books";
import BookOverview from "./BookOverview";
import type { Book } from "../types";
import type { Schemas } from "../api/client";

vi.mock("../api/books", () => ({
  getOriginalBookFiles: vi.fn(),
  getBookCleanedChapters: vi.fn(),
  refreshBook: vi.fn(),
}));
vi.mock("../api/library", () => ({
  getWebChecks: vi.fn().mockResolvedValue([]),
  getLibraryBookInfo: vi.fn().mockResolvedValue({ audio_playable: false }),
}));
vi.mock("./UniverseMembership", () => ({ default: () => null }));

const book: Book = {
  id: 7,
  title: "A book",
  author: "An author",
  source_type: "epub",
  current_path: "library/cleaned.epub",
  immutable_path: "library/original.epub",
  series: null,
  series_index: null,
  notes: null,
  source_url: null,
  cover_path: null,
  removed_chapters: [],
  content_selectors: [],
  genre_tags: null,
  source_tags: null,
  user_genre_tags: null,
  metadata_details: null,
  metadata_remote_ids: null,
  metadata_sync_source: null,
  metadata_synced_at: null,
  master_word_count: null,
  current_word_count: null,
  download_status: null,
  refresh_status: null,
  created_at: "2026-11-15T00:00:00Z",
  content_updated_at: "2026-11-15T00:00:00Z",
  content_version: 1,
  updated_at: null,
  deleted_at: null,
  purge_after: null,
  audiobook_enabled: false,
  audiobook_pipeline_status: null,
  audiobook_tts_provider: null,
};
const originalEpub: Schemas["OriginalBookFile"] = {
  filename: "original.epub",
  kind: "epub",
  edition_name: null,
  size_bytes: 1024,
  download_url: "/api/books/7/download-original",
};
const originalAudio: Schemas["OriginalBookFile"] = {
  filename: "Part 1.m4b",
  kind: "audio",
  edition_name: "Unabridged edition",
  size_bytes: 2048,
  download_url: "/api/books/7/original-audio/12?filename=Part+1.m4b",
};

beforeEach(() => vi.clearAllMocks());

describe("Book original downloads", () => {
  it("offers the original EPUB and every audio file alongside the current EPUB", async () => {
    vi.mocked(getOriginalBookFiles).mockResolvedValue([
      originalEpub,
      originalAudio,
      {
        ...originalAudio,
        filename: "Part 2.mp3",
        edition_name: "Another edition",
        download_url: "/api/books/7/original-audio/13?filename=Part+2.mp3",
      },
    ]);
    renderWithClient(
      <BookOverview book={book} onBack={vi.fn()} onSection={vi.fn()} />,
    );
    const disclosure = screen.getByRole("group", { name: "Original files" });
    expect(disclosure).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Original files", { selector: "summary" }));
    expect(disclosure).toHaveAttribute("open");
    const originals = within(disclosure);
    const epub = await originals.findByRole("link", {
      name: "Download original EPUB: original.epub",
    });
    expect(epub).toHaveAttribute("href", originalEpub.download_url);
    expect(epub).toHaveAttribute("download");
    expect(
      originals.getByRole("link", {
        name: "Download original audio: Part 1.m4b",
      }),
    ).toHaveAttribute("href", originalAudio.download_url);
    expect(
      originals.getByRole("link", {
        name: "Download original audio: Part 2.mp3",
      }),
    ).toHaveAttribute(
      "href",
      "/api/books/7/original-audio/13?filename=Part+2.mp3",
    );
    expect(originals.getByText(/Unabridged edition/)).toBeInTheDocument();
    expect(originals.getByText(/Another edition/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download EPUB" })).toHaveAttribute(
      "href",
      "/api/books/7/download",
    );
  });

  it("allows original audio downloads before an audio-only book is playable", async () => {
    vi.mocked(getOriginalBookFiles).mockResolvedValue([originalAudio]);
    renderWithClient(
      <BookOverview
        book={{ ...book, source_type: "audiobook", current_path: null }}
        onBack={vi.fn()}
        onSection={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Original files", { selector: "summary" }));
    expect(
      await screen.findByRole("link", {
        name: "Download original audio: Part 1.m4b",
      }),
    ).toHaveAttribute("download");
    expect(
      screen.queryByRole("link", { name: "Download EPUB" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Listen" }),
    ).not.toBeInTheDocument();
  });

  it("explains when originals are unavailable", async () => {
    vi.mocked(getOriginalBookFiles).mockResolvedValue([]);
    renderWithClient(
      <BookOverview book={book} onBack={vi.fn()} onSection={vi.fn()} />,
    );
    fireEvent.click(screen.getByText("Original files", { selector: "summary" }));
    expect(
      await screen.findByText("No original EPUB or audio files are available."),
    ).toBeInTheDocument();
  });

  it("shows a load failure without hiding the current EPUB download", async () => {
    vi.mocked(getOriginalBookFiles).mockRejectedValue(
      new Error("Could not load original files"),
    );
    renderWithClient(
      <BookOverview book={book} onBack={vi.fn()} onSection={vi.fn()} />,
    );
    fireEvent.click(screen.getByText("Original files", { selector: "summary" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load original files",
    );
    expect(
      screen.getByRole("link", { name: "Download EPUB" }),
    ).toBeInTheDocument();
  });
});
