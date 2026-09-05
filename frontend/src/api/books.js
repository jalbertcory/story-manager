import { getJson, getOptionalJson, sendJson, sendWithoutBody } from "./client";

export function buildBookCatalogPath({
  q = "",
  view = "series",
  review = "",
  audiobook = "",
  genre = "",
  sortBy = "title",
  sortOrder = "asc",
  limit = 30,
  cursor = "",
  series,
  universe,
  source,
}) {
  const params = [];
  if (series != null) params.push(`series=${encodeURIComponent(series)}`);
  if (universe != null) params.push(`universe=${universe}`);
  if (source) params.push(`source=${encodeURIComponent(source)}`);
  if (q) params.push(`q=${encodeURIComponent(q)}`);
  params.push(`sort_by=${encodeURIComponent(sortBy)}`);
  params.push(`sort_order=${encodeURIComponent(sortOrder)}`);
  if (view !== "series") params.push(`view=${encodeURIComponent(view)}`);
  if (limit !== 30) params.push(`limit=${limit}`);
  if (review) params.push(`review=${encodeURIComponent(review)}`);
  if (audiobook) params.push(`audiobook=${encodeURIComponent(audiobook)}`);
  if (genre) params.push(`genre=${encodeURIComponent(genre)}`);
  if (cursor) params.push(`cursor=${encodeURIComponent(cursor)}`);
  return `/api/books/catalog?${params.join("&")}`;
}

export function getBookCatalog(params) {
  return getJson(buildBookCatalogPath(params), "Failed to fetch books").then(
    (data) => {
      if (!Array.isArray(data)) return data;
      const series = new Set(
        data
          .filter((book) => book.series && !book.download_status)
          .map((book) => book.series),
      ).size;
      const standalone = data.filter(
        (book) =>
          book.source_type !== "web" &&
          (!book.series || Boolean(book.download_status)),
      ).length;
      const web = data.filter(
        (book) => book.source_type === "web" && !book.download_status,
      ).length;
      return {
        items: data,
        next_cursor: null,
        total_count: data.length,
        facets: { series, standalone, web, genres: [] },
      };
    },
  );
}

export async function getAllBookCatalog(params = {}) {
  const books = [];
  let cursor = "";
  do {
    const page = await getBookCatalog({
      ...params,
      view: params.view ?? "all",
      limit: 100,
      cursor,
    });
    books.push(...page.items);
    cursor = page.next_cursor ?? "";
  } while (cursor);
  return books;
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

export function getRecycleBin() {
  return getJson("/api/recycle-bin", "Failed to load recycle bin");
}

export function restoreRecycledBook(bookId) {
  return sendWithoutBody(`/api/recycle-bin/${bookId}/restore`, {
    fallbackMessage: "Restore failed",
  });
}

export function permanentlyDeleteRecycledBook(bookId) {
  return sendWithoutBody(`/api/recycle-bin/${bookId}`, {
    method: "DELETE",
    fallbackMessage: "Permanent delete failed",
  });
}

export function getBookRevisions(bookId) {
  return getJson(
    `/api/books/${bookId}/revisions`,
    "Failed to load change history",
  );
}

export function restoreBookRevision(bookId, revisionId) {
  return sendWithoutBody(
    `/api/books/${bookId}/revisions/${revisionId}/restore`,
    {
      fallbackMessage: "Failed to restore revision",
    },
  );
}

export function restoreOriginalEpub(bookId) {
  return sendWithoutBody(`/api/books/${bookId}/restore-original`, {
    fallbackMessage: "Failed to restore original EPUB",
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
