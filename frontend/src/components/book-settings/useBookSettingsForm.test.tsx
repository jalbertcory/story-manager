import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Book } from "../../types";
import { useBookSettingsForm } from "./useBookSettingsForm";

const book = (overrides: Partial<Book> = {}): Book => ({
  id: 1,
  title: "Original Title",
  author: "Author",
  series: null,
  series_index: null,
  notes: null,
  metadata_remote_ids: null,
  metadata_details: null,
  metadata_sync_source: null,
  metadata_synced_at: null,
  genre_tags: null,
  source_tags: null,
  user_genre_tags: [],
  removed_chapters: [],
  content_selectors: [],
  refresh_status: "processing",
  download_status: null,
  source_type: "web",
  source_url: "https://example.com/story",
  immutable_path: "books/original.epub",
  current_path: "books/current.epub",
  cover_path: null,
  master_word_count: null,
  current_word_count: null,
  content_version: 1,
  content_updated_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
  deleted_at: null,
  purge_after: null,
  audiobook_enabled: false,
  audiobook_pipeline_status: null,
  audiobook_tts_provider: null,
  ...overrides,
});

describe("useBookSettingsForm", () => {
  it("keeps unsaved edits when the same book is refetched", () => {
    const { result, rerender } = renderHook(
      ({ current }) => useBookSettingsForm(current),
      { initialProps: { current: book() } },
    );

    act(() => result.current.setTitle("Edited Title"));
    expect(result.current.isDirty).toBe(true);

    rerender({ current: book({ refresh_status: "completed" }) });

    expect(result.current.title).toBe("Edited Title");
    expect(result.current.isDirty).toBe(true);
  });

  it("follows server changes while there are no unsaved edits", () => {
    const { result, rerender } = renderHook(
      ({ current }) => useBookSettingsForm(current),
      { initialProps: { current: book() } },
    );

    rerender({ current: book({ title: "Synced Title" }) });

    expect(result.current.title).toBe("Synced Title");
    expect(result.current.isDirty).toBe(false);
  });

  it("is clean once saved values come back from the server", () => {
    const { result, rerender } = renderHook(
      ({ current }) => useBookSettingsForm(current),
      { initialProps: { current: book() } },
    );

    act(() => result.current.setTitle("Saved Title"));
    rerender({ current: book({ title: "Saved Title" }) });

    expect(result.current.isDirty).toBe(false);
  });

  it("resets when a different book is opened", () => {
    const { result, rerender } = renderHook(
      ({ current }) => useBookSettingsForm(current),
      { initialProps: { current: book() } },
    );

    act(() => result.current.setTitle("Edited Title"));
    rerender({ current: book({ id: 2, title: "Other Book" }) });

    expect(result.current.title).toBe("Other Book");
    expect(result.current.isDirty).toBe(false);
  });

  it("saves only edited fields, keeping values synced while editing", () => {
    const { result, rerender } = renderHook(
      ({ current }) => useBookSettingsForm(current),
      { initialProps: { current: book() } },
    );

    act(() => result.current.setNotes("My notes"));
    // A metadata recheck updates the author on the server mid-edit.
    rerender({ current: book({ author: "Synced Author", series: "Saga" }) });

    expect(result.current.author).toBe("Synced Author");
    expect(result.current.notes).toBe("My notes");
    let update;
    act(() => {
      update = result.current.getUpdatedFields();
    });
    expect(update).toEqual({ notes: "My notes" });
  });

  it("rejects malformed extra identifiers only when they change", () => {
    const current = book();
    const { result } = renderHook(() => useBookSettingsForm(current));

    act(() => result.current.setOtherRemoteIdsJson("[1]"));
    let update;
    act(() => {
      update = result.current.getUpdatedFields();
    });
    expect(update).toBeNull();
    expect(result.current.identifierError).toBe(
      "Other identifiers must be a JSON object.",
    );
  });
});
