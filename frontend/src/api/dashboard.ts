import { api, unwrap } from "./client";
export function getAttentionDashboard(limit = 5) {
  return unwrap(
    api.GET("/api/dashboard/attention", { params: { query: { limit } } }),
    "Failed to load library attention items",
  );
}
