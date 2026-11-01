import { api, unwrap, unwrapEmpty, requestInit } from "./client";
import type { Query, RequestOptions } from "./client";
export const getReaderKeys = (options?: RequestOptions) =>
  unwrap(
    api.GET("/api/reader-keys", requestInit(options)),
    "Failed to load reader keys",
  );
export const createReaderKey = (label: string) =>
  unwrap(
    api.POST("/api/reader-keys", { body: { label } }),
    "Failed to create reader key",
  );
export const revokeReaderKey = (id: number) =>
  unwrapEmpty(
    api.DELETE("/api/reader-keys/{key_id}", {
      params: { path: { key_id: id } },
    }),
    "Failed to revoke reader key",
  );
export const getLogs = (
  query: Query<"/api/logs"> = {},
  options?: RequestOptions,
) =>
  unwrap(
    api.GET("/api/logs", { ...requestInit(options), params: { query } }),
    "Failed to load logs",
  );
export const getHealth = (options?: RequestOptions) =>
  unwrap(
    api.GET("/api/observability/health", requestInit(options)),
    "Failed to load service health",
  );
export const getJobMetrics = (windowHours = 24, options?: RequestOptions) =>
  unwrap(
    api.GET("/api/observability/job-metrics", {
      ...requestInit(options),
      params: { query: { window_hours: windowHours } },
    }),
    "Failed to load job metrics",
  );
export const cleanupStorage = (dryRun = true) =>
  unwrap(
    api.POST("/api/storage/cleanup", {
      params: { query: { dry_run: dryRun } },
    }),
    "Storage cleanup failed",
  );
export const validateLibrary = (options?: RequestOptions) =>
  unwrap(
    api.GET("/api/library/validate", requestInit(options)),
    "Library validation failed",
  );
export const postClientLog = (
  message: string,
  source?: string,
  level = "ERROR",
) =>
  unwrap(
    api.POST("/api/logs/client", {
      body: { message, ...(source !== undefined ? { source } : {}), level },
    }),
  );
export const sendClientLog = postClientLog;
export const removeAllBooks = (dryRun = true) =>
  unwrap(
    api.POST("/api/books/remove-all", {
      params: { query: { dry_run: dryRun } },
    }),
    "Failed to remove books",
  );
export const getWebChecks = (options?: RequestOptions) =>
  unwrap(
    api.GET("/api/library/web-checks", requestInit(options)),
    "Failed to load web update checks",
  );
