import { getJson, getOptionalJson, sendForm, sendJson, sendWithoutBody } from "./client";

export function buildBookCatalogPath({ q = "", sortBy = "title", sortOrder = "asc" }) {
  const suffix = `sort_by=${encodeURIComponent(sortBy)}&sort_order=${encodeURIComponent(sortOrder)}`;
  if (!q) {
    return `/api/books/catalog?${suffix}`;
  }
  return `/api/books/catalog?q=${encodeURIComponent(q)}&${suffix}`;
}

export function getBookCatalog(params) {
  return getJson(buildBookCatalogPath(params), "Failed to fetch books");
}

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

export function getBook(bookId) {
  return getOptionalJson(`/api/books/${bookId}`);
}

export function updateBook(bookId, data) {
  return sendJson(`/api/books/${bookId}`, {
    method: "PUT",
    body: data,
    fallbackMessage: "Failed to save",
  });
}

export function deleteBook(bookId) {
  return sendWithoutBody(`/api/books/${bookId}`, {
    method: "DELETE",
    fallbackMessage: "Delete failed",
  });
}

export function processBook(bookId) {
  return sendWithoutBody(`/api/books/${bookId}/process`, {
    fallbackMessage: "Processing failed",
  });
}

export function refreshBook(bookId) {
  return sendWithoutBody(`/api/books/${bookId}/refresh`, {
    fallbackMessage: "Refresh failed",
  });
}

export function detachBookSource(bookId) {
  return sendWithoutBody(`/api/books/${bookId}/detach-source`, {
    fallbackMessage: "Failed to remove web marker",
  });
}

export function getBookChapters(bookId) {
  return getJson(`/api/books/${bookId}/chapters`, "Failed to fetch chapters");
}

export function getBookCleanedChapters(bookId) {
  return getJson(`/api/books/${bookId}/cleaned-chapters`, "Failed to fetch cleaned chapters");
}

export function getMatchedConfigs(bookId) {
  return getJson(`/api/books/${bookId}/matched-config`, "Failed to fetch matched config");
}

export function previewCleaning(bookId, data) {
  return sendJson(`/api/books/${bookId}/preview-cleaning`, {
    body: data,
    fallbackMessage: "Preview failed",
  });
}

export function uploadBookCover(bookId, file) {
  const form = new FormData();
  form.append("file", file);
  return sendForm(`/api/books/${bookId}/cover`, form, {
    fallbackMessage: "Cover upload failed",
  });
}

export function retryBookCover(bookId) {
  return sendWithoutBody(`/api/books/${bookId}/retry-cover`, {
    fallbackMessage: "Failed to retry cover",
  });
}

export function setBookCoverUrl(bookId, url) {
  return sendJson(`/api/books/${bookId}/cover-url`, {
    body: { url },
    fallbackMessage: "Failed to set cover from URL",
  });
}

export function getApiCoverUrl(bookId) {
  return `/api/covers/${bookId}`;
}
