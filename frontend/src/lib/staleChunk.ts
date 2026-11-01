const RELOAD_KEY = "story-manager:stale-chunk-reload";
const RELOAD_PARAM = "stale-chunk-reload";
const RELOAD_WINDOW_MS = 10_000;

type ReloadLocation = Pick<Location, "href" | "reload" | "replace">;

// True once this page load has used its one stale-chunk reload: either it
// started one, or it is the result of one that marked the URL.
let reloadSpent = false;

// Call before the app reads the URL. A reload made without session storage
// carries a marker in the query string; remember it and take it out of the
// address bar so it is not bookmarked or shared.
export function consumeStaleChunkMarker(): void {
  const url = new URL(window.location.href);
  if (!url.searchParams.has(RELOAD_PARAM)) return;
  reloadSpent = true;
  url.searchParams.delete(RELOAD_PARAM);
  window.history.replaceState(
    window.history.state,
    "",
    `${url.pathname}${url.search}${url.hash}`,
  );
}

// Reloads the page to fetch a fresh build, unless a reload for the same reason
// just happened (the chunk is genuinely missing), which would loop forever.
// Returns whether a reload was started.
export function reloadAfterStaleChunk(
  location: ReloadLocation = window.location,
): boolean {
  if (reloadSpent) return false;
  reloadSpent = true;
  const now = Date.now();
  try {
    const last = Number(window.sessionStorage.getItem(RELOAD_KEY) || 0);
    if (now - last < RELOAD_WINDOW_MS) return false;
    window.sessionStorage.setItem(RELOAD_KEY, String(now));
  } catch {
    // Session storage is unavailable (private mode or blocked site data), so
    // mark the reload in the URL instead; consumeStaleChunkMarker reads it.
    const url = new URL(location.href);
    url.searchParams.set(RELOAD_PARAM, "1");
    location.replace(url.href);
    return true;
  }
  location.reload();
  return true;
}
