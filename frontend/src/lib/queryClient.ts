import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";
import { isApiError } from "../api/client";
import { reportUnauthorized } from "./authSession";

const MAX_RETRIES = 3;

// Client errors will fail the same way again, so only transient failures
// (network errors, 5xx, rate limits, timeouts) are retried.
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (
    isApiError(error) &&
    error.status >= 400 &&
    error.status < 500 &&
    error.status !== 408 &&
    error.status !== 429
  )
    return false;
  return failureCount < MAX_RETRIES;
}

function handleError(error: unknown): void {
  if (isApiError(error, 401)) reportUnauthorized();
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({ onError: handleError }),
    mutationCache: new MutationCache({ onError: handleError }),
    defaultOptions: { queries: { retry: shouldRetry } },
  });
}
