import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Each test is a fresh page load: the module keeps per-page state.
async function loadPage(href: string) {
  vi.resetModules();
  window.history.replaceState(null, "", href);
  return import("./staleChunk");
}

function fakeLocation() {
  return {
    href: window.location.href,
    reload: vi.fn<() => void>(),
    replace: vi.fn<(url: string | URL) => void>(),
  };
}

describe("stale chunk reload", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  it("reloads once, then lets the error through if the chunk is still missing", async () => {
    let page = await loadPage("/books/1");
    const first = fakeLocation();
    expect(page.reloadAfterStaleChunk(first)).toBe(true);
    expect(first.reload).toHaveBeenCalledTimes(1);

    page = await loadPage("/books/1");
    page.consumeStaleChunkMarker();
    const second = fakeLocation();
    expect(page.reloadAfterStaleChunk(second)).toBe(false);
    expect(second.reload).not.toHaveBeenCalled();
  });

  it("guards the reload through the URL when session storage throws", async () => {
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
      throw new DOMException("Storage is blocked", "SecurityError");
    });

    let page = await loadPage("/books/1?tab=audio#chapter-2");
    page.consumeStaleChunkMarker();
    const first = fakeLocation();
    expect(page.reloadAfterStaleChunk(first)).toBe(true);
    expect(first.reload).not.toHaveBeenCalled();
    expect(first.replace).toHaveBeenCalledTimes(1);
    const reloadedHref = String(first.replace.mock.calls[0]?.[0]);
    expect(new URL(reloadedHref).searchParams.get("stale-chunk-reload")).toBe(
      "1",
    );
    // A second failure before the page goes away does not navigate again.
    expect(page.reloadAfterStaleChunk(first)).toBe(false);
    expect(first.replace).toHaveBeenCalledTimes(1);

    page = await loadPage(reloadedHref);
    page.consumeStaleChunkMarker();
    expect(
      `${window.location.pathname}${window.location.search}${window.location.hash}`,
    ).toBe("/books/1?tab=audio#chapter-2");
    const second = fakeLocation();
    expect(page.reloadAfterStaleChunk(second)).toBe(false);
    expect(second.reload).not.toHaveBeenCalled();
    expect(second.replace).not.toHaveBeenCalled();
  });
});
