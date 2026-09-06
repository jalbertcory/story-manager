import { api, unwrap, unwrapEmpty } from "./client";
import type { Query } from "./client";
export const getReaderKeys = () =>
  unwrap(api.GET("/api/reader-keys"), "Failed to load reader keys");
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
export const getLogs = (query: Query<"/api/logs"> = {}) =>
  unwrap(api.GET("/api/logs", { params: { query } }), "Failed to load logs");
export const getHealth = () =>
  unwrap(api.GET("/api/observability/health"), "Failed to load service health");
export const getJobMetrics = (windowHours = 24) =>
  unwrap(
    api.GET("/api/observability/job-metrics", {
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
export const validateLibrary = () =>
  unwrap(api.GET("/api/library/validate"), "Library validation failed");
export const postClientLog = (
  message: string,
  source?: string,
  level = "ERROR",
) => unwrap(api.POST("/api/logs/client", { body: { message, source, level } }));
export const sendClientLog = postClientLog;
export const removeAllBooks = (dryRun = true) =>
  unwrap(
    api.POST("/api/books/remove-all", {
      params: { query: { dry_run: dryRun } },
    }),
    "Failed to remove books",
  );
export const getWebChecks = () =>
  unwrap(
    api.GET("/api/library/web-checks"),
    "Failed to load web update checks",
  );
