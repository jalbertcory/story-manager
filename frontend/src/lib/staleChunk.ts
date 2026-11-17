import { createGuardedReload } from "./pageReload";

// After a deploy, lazily loaded pages may point at chunks the server no longer
// has. One reload picks up the new build; a second within the window means the
// chunk is genuinely missing, so the error is let through instead.
const staleChunkReload = createGuardedReload({
  storageKey: "story-manager:stale-chunk-reload",
  urlParam: "stale-chunk-reload",
  windowMs: 10_000,
});

export const consumeStaleChunkMarker = staleChunkReload.consumeMarker;
export const reloadAfterStaleChunk = staleChunkReload.reload;
