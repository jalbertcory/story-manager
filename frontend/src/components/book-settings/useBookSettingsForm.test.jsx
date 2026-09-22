import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useBookSettingsForm } from "./useBookSettingsForm";

const book = (overrides = {}) => ({
  id: 1,
  title: "Original Title",
  author: "Author",
  series: null,
  series_index: null,
  notes: null,
  metadata_remote_ids: null,
  user_genre_tags: [],
  removed_chapters: [],
  content_selectors: [],
  refresh_status: "processing",
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
});
