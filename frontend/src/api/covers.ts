import { api, apiUrl, unwrap, multipart } from "./client";

export function uploadBookCover(bookId: number, file: File) {
  return unwrap(
    api.POST("/api/books/{book_id}/cover", {
      params: { path: { book_id: bookId } },
      body: { file },
      bodySerializer: multipart,
    }),
    "Cover upload failed",
  );
}

export function retryBookCover(bookId: number) {
  return unwrap(
    api.POST("/api/books/{book_id}/retry-cover", {
      params: { path: { book_id: bookId } },
    }),
    "Failed to retry cover",
  );
}

export function setBookCoverUrl(bookId: number, url: string) {
  return unwrap(
    api.POST("/api/books/{book_id}/cover-url", {
      params: { path: { book_id: bookId } },
      body: { url },
    }),
    "Failed to set cover from URL",
  );
}

export function getApiCoverUrl(bookId: number) {
  return apiUrl("/api/covers/{book_id}", { book_id: bookId });
}
