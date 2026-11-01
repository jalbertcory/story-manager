import { api, unwrap, requestInit } from "./client";
import type { RequestOptions } from "./client";

export function getLifecycleDefinitions(options?: RequestOptions) {
  return unwrap(
    api.GET("/api/lifecycles", requestInit(options)),
    "Failed to fetch lifecycle definitions",
  );
}
