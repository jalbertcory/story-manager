import { api, unwrap } from "./client";

export function getLifecycleDefinitions() {
  return unwrap(
    api.GET("/api/lifecycles"),
    "Failed to fetch lifecycle definitions",
  );
}
