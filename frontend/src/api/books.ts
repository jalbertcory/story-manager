import { api, unwrap, unwrapEmpty, unwrapOptional } from "./client";
import type { Body, Query, Schemas } from "./client";

type CatalogQuery = Query<"/api/books/catalog">;
export interface BookCatalogParams {
  q?: string;
  view?: CatalogQuery["view"];
  review?: CatalogQuery["review"] | "";
  audiobook?: CatalogQuery["audiobook"] | "";
  genre?: string;
  sortBy?: CatalogQuery["sort_by"];
  sortOrder?: CatalogQuery["sort_order"];
  limit?: number;
  cursor?: string;
  series?: string | null;
  universe?: number | null;
  source?: CatalogQuery["source"] | "";
}

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
}: BookCatalogParams) {
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

export function getBookCatalog({
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
}: BookCatalogParams = {}) {
  return unwrap(
    api.GET("/api/books/catalog", {
      params: {
        query: {
          q,
          view,
          ...(review ? { review } : {}),
          ...(audiobook ? { audiobook } : {}),
          ...(genre ? { genre } : {}),
          sort_by: sortBy,
          sort_order: sortOrder,
          limit,
          ...(cursor ? { cursor } : {}),
          ...(series != null ? { series } : {}),
          ...(universe != null ? { universe } : {}),
          ...(source ? { source } : {}),
        },
      },
    }),
    "Failed to fetch books",
  );
}

export async function getAllBookCatalog(params: BookCatalogParams = {}) {
  const books: Schemas["BookCatalogEntry"][] = [];
  let cursor = "";
  do {
    const page = await getBookCatalog({
      ...params,
      view: params.view ?? "all",
      limit: 100,
      cursor,
    });
    books.push(...(page.items ?? []));
    cursor = page.next_cursor ?? "";
  } while (cursor);
  return books;
}

export function getBook(bookId: number) {
  return unwrapOptional(
    api.GET("/api/books/{book_id}", { params: { path: { book_id: bookId } } }),
  );
}

export function updateBook(
  bookId: number,
  data: Body<"/api/books/{book_id}", "put">,
) {
  return unwrap(
    api.PUT("/api/books/{book_id}", {
      params: { path: { book_id: bookId } },
      body: data,
    }),
    "Failed to save",
  );
}

export function deleteBook(bookId: number) {
  return unwrapEmpty(
    api.DELETE("/api/books/{book_id}", {
      params: { path: { book_id: bookId } },
    }),
    "Delete failed",
  );
}

export function getRecycleBin() {
  return unwrap(api.GET("/api/recycle-bin"), "Failed to load recycle bin");
}

export function restoreRecycledBook(bookId: number) {
  return unwrap(
    api.POST("/api/recycle-bin/{book_id}/restore", {
      params: { path: { book_id: bookId } },
    }),
    "Restore failed",
  );
}

export function permanentlyDeleteRecycledBook(bookId: number) {
  return unwrapEmpty(
    api.DELETE("/api/recycle-bin/{book_id}", {
      params: { path: { book_id: bookId } },
    }),
    "Permanent delete failed",
  );
}

export function getBookRevisions(bookId: number) {
  return unwrap(
    api.GET("/api/books/{book_id}/revisions", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to load change history",
  );
}

export function restoreBookRevision(bookId: number, revisionId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/revisions/{revision_id}/restore", {
      params: { path: { book_id: bookId, revision_id: revisionId } },
    }),
    "Failed to restore revision",
  );
}

export function restoreOriginalEpub(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/restore-original", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to restore original EPUB",
  );
}

export function processBook(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/process", {
      params: { path: { book_id: bookId } },
    }),
    "Processing failed",
  );
}

export function refreshBook(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/refresh", {
      params: { path: { book_id: bookId } },
    }),
    "Refresh failed",
  );
}

export function detachBookSource(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/detach-source", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to remove web marker",
  );
}

export function getBookChapters(bookId: number) {
  return unwrap(
    api.GET("/api/books/{book_id}/chapters", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to fetch chapters",
  );
}

export function getBookCleanedChapters(bookId: number) {
  return unwrap(
    api.GET("/api/books/{book_id}/cleaned-chapters", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to fetch cleaned chapters",
  );
}

export function getBookUpdateHistory(bookId: number) {
  return unwrap(
    api.GET("/api/books/{book_id}/update-history", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to fetch update history",
  );
}
