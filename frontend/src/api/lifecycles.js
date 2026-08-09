import { getJson } from "./client";

export function getLifecycleDefinitions() {
  return getJson("/api/lifecycles", "Failed to fetch lifecycle definitions");
}
