import { api, unwrap, requestInit } from "./client";
import type { Body, RequestOptions } from "./client";

export function getStoryRecap(bookId: number, options?: RequestOptions) {
  return unwrap(
    api.GET("/api/books/{book_id}/recap", {
      params: { path: { book_id: bookId } },
      ...requestInit(options),
    }),
    "Failed to load recaps",
  );
}

export function queueStoryRecap(
  bookId: number,
  body: Body<"/api/books/{book_id}/recap", "post">,
) {
  return unwrap(
    api.POST("/api/books/{book_id}/recap", {
      params: { path: { book_id: bookId } },
      body,
    }),
    "Failed to start the recap",
  );
}
