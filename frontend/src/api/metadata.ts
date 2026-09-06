import { api, unwrap, unwrapOptional } from "./client";

export function previewMetadataSync(bookIds: number[] | null = null) {
  return unwrap(
    api.POST("/api/metadata/sync-preview", { body: { book_ids: bookIds } }),
    "Failed to preview metadata sync",
  );
}

export function applyMetadataSync(bookIds: number[] | null = null) {
  return unwrap(
    api.POST("/api/metadata/apply", { body: { book_ids: bookIds } }),
    "Failed to apply metadata sync",
  );
}

export function queueMetadataSync(
  bookIds: number[] | null = null,
  trigger: string = "manual",
) {
  return unwrap(
    api.POST("/api/metadata/jobs", { body: { book_ids: bookIds, trigger } }),
    "Failed to queue metadata sync",
  );
}

export function getLatestMetadataJob() {
  return unwrapOptional(api.GET("/api/metadata/jobs/latest"));
}

export function getMetadataInbox({ offset = 0, limit = 100 } = {}) {
  return unwrap(
    api.GET("/api/metadata/inbox", { params: { query: { offset, limit } } }),
    "Failed to load metadata inbox",
  );
}

export function approveMetadataMatch(matchId: number) {
  return unwrap(
    api.POST("/api/metadata/matches/{match_id}/approve", {
      params: { path: { match_id: matchId } },
    }),
    "Failed to approve metadata match",
  );
}

export function rejectMetadataMatch(matchId: number) {
  return unwrap(
    api.POST("/api/metadata/matches/{match_id}/reject", {
      params: { path: { match_id: matchId } },
    }),
    "Failed to reject metadata match",
  );
}

export function dismissMetadataProposal(proposalId: number) {
  return unwrap(
    api.POST("/api/metadata/proposals/{proposal_id}/dismiss", {
      params: { path: { proposal_id: proposalId } },
    }),
    "Failed to dismiss metadata proposal",
  );
}
