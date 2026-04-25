import { getJson, getOptionalJson, sendJson, sendWithoutBody } from "./client";

export function buildBookCatalogPath({
  q = "",
  sortBy = "title",
  sortOrder = "asc",
}) {
  const suffix = `sort_by=${encodeURIComponent(sortBy)}&sort_order=${encodeURIComponent(sortOrder)}`;
  if (!q) {
    return `/api/books/catalog?${suffix}`;
  }
  return `/api/books/catalog?q=${encodeURIComponent(q)}&${suffix}`;
}

export function getBookCatalog(params) {
  return getJson(buildBookCatalogPath(params), "Failed to fetch books");
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
  return getJson(
    `/api/books/${bookId}/cleaned-chapters`,
    "Failed to fetch cleaned chapters",
  );
}

export function getBookUpdateHistory(bookId) {
  return getJson(
    `/api/books/${bookId}/update-history`,
    "Failed to fetch update history",
  );
}
