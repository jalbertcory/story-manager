import { api, unwrap, unwrapEmpty, requestInit } from "./client";
import type { RequestOptions } from "./client";
export function getAttentionDashboard(limit = 5, options?: RequestOptions) {
  return unwrap(
    api.GET("/api/dashboard/attention", {
      ...requestInit(options),
      params: { query: { limit } },
    }),
    "Failed to load library attention items",
  );
}
export const queueSeriesCheck = () =>
  unwrap(
    api.POST("/api/series-tracking/check"),
    "Failed to queue the series check",
  );
export const dismissSeriesGap = (seriesName: string) =>
  unwrapEmpty(
    api.POST("/api/series-tracking/gaps/dismiss", {
      body: { series_name: seriesName },
    }),
    "Failed to dismiss series gap",
  );
export const dismissSeriesRelease = (findingId: number) =>
  unwrapEmpty(
    api.POST("/api/series-tracking/releases/{finding_id}/dismiss", {
      params: { path: { finding_id: findingId } },
    }),
    "Failed to dismiss release",
  );
