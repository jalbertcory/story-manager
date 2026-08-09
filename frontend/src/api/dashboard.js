import { getJson } from "./client";

export function getAttentionDashboard(limit = 5) {
  return getJson(
    `/api/dashboard/attention?limit=${limit}`,
    "Failed to load library attention items",
  );
}
