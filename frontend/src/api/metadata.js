import { getJson, getOptionalJson, sendJson, sendWithoutBody } from "./client";

export function previewMetadataSync(bookIds = null) {
  return sendJson("/api/metadata/sync-preview", {
    body: { book_ids: bookIds },
    fallbackMessage: "Failed to preview metadata sync",
  });
}

export function applyMetadataSync(bookIds = null) {
  return sendJson("/api/metadata/apply", {
    body: { book_ids: bookIds },
    fallbackMessage: "Failed to apply metadata sync",
  });
}

export function queueMetadataSync(bookIds = null, trigger = "manual") {
  return sendJson("/api/metadata/jobs", {
    body: { book_ids: bookIds, trigger },
    fallbackMessage: "Failed to queue metadata sync",
  });
}

export function getLatestMetadataJob() {
  return getOptionalJson("/api/metadata/jobs/latest");
}

export function getMetadataInbox() {
  return getJson("/api/metadata/inbox", "Failed to load metadata inbox");
}

export function approveMetadataMatch(matchId) {
  return sendWithoutBody(`/api/metadata/matches/${matchId}/approve`, {
    fallbackMessage: "Failed to approve metadata match",
  });
}

export function rejectMetadataMatch(matchId) {
  return sendWithoutBody(`/api/metadata/matches/${matchId}/reject`, {
    fallbackMessage: "Failed to reject metadata match",
  });
}

export function dismissMetadataProposal(proposalId) {
  return sendWithoutBody(`/api/metadata/proposals/${proposalId}/dismiss`, {
    fallbackMessage: "Failed to dismiss metadata proposal",
  });
}
