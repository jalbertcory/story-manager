import { api, unwrap, requestInit } from "./client";
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
