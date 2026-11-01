import { api, unwrap, unwrapEmpty, requestInit } from "./client";
import type { Body, RequestOptions } from "./client";

export function getMatchedConfigs(bookId: number, options?: RequestOptions) {
  return unwrap(
    api.GET("/api/books/{book_id}/matched-config", {
      ...requestInit(options),
      params: { path: { book_id: bookId } },
    }),
    "Failed to fetch matched config",
  );
}

export function previewCleaning(
  bookId: number,
  data: Body<"/api/books/{book_id}/preview-cleaning", "post">,
) {
  return unwrap(
    api.POST("/api/books/{book_id}/preview-cleaning", {
      params: { path: { book_id: bookId } },
      body: data,
    }),
    "Preview failed",
  );
}

export const getCleaningConfigs = (options?: RequestOptions) =>
  unwrap(api.GET("/api/cleaning-configs", requestInit(options)));
export const createCleaningConfig = (
  body: Body<"/api/cleaning-configs", "post">,
) => unwrap(api.POST("/api/cleaning-configs", { body }));
export const updateCleaningConfig = (
  id: number,
  body: Body<"/api/cleaning-configs/{config_id}", "put">,
) =>
  unwrap(
    api.PUT("/api/cleaning-configs/{config_id}", {
      params: { path: { config_id: id } },
      body,
    }),
  );
export const deleteCleaningConfig = (id: number) =>
  unwrapEmpty(
    api.DELETE("/api/cleaning-configs/{config_id}", {
      params: { path: { config_id: id } },
    }),
  );
export const reprocessAllBooks = () =>
  unwrap(api.POST("/api/books/reprocess-all"));
export const getReprocessAllStatus = (options?: RequestOptions) =>
  unwrap(api.GET("/api/books/reprocess-all/status", requestInit(options)));
