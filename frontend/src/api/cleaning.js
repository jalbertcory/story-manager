import { getJson, sendJson } from "./client";

export function getMatchedConfigs(bookId) {
  return getJson(
    `/api/books/${bookId}/matched-config`,
    "Failed to fetch matched config",
  );
}

export function previewCleaning(bookId, data) {
  return sendJson(`/api/books/${bookId}/preview-cleaning`, {
    body: data,
    fallbackMessage: "Preview failed",
  });
}
