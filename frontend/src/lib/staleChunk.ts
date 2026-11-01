const RELOAD_KEY = "story-manager:stale-chunk-reload";
const RELOAD_WINDOW_MS = 10_000;

// Reloads the page to fetch a fresh build, unless a reload for the same reason
// just happened (the chunk is genuinely missing), which would loop forever.
// Returns whether a reload was started.
export function reloadAfterStaleChunk(): boolean {
  const now = Date.now();
  try {
    const last = Number(window.sessionStorage.getItem(RELOAD_KEY) || 0);
    if (now - last < RELOAD_WINDOW_MS) return false;
    window.sessionStorage.setItem(RELOAD_KEY, String(now));
  } catch {
    // Without session storage there is no loop protection; reload anyway.
  }
  window.location.reload();
  return true;
}
