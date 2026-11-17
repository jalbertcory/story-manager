import { QueryClient } from "@tanstack/react-query";
import { isApiError } from "../api/client";

const MAX_RETRIES = 3;

// Client errors will fail the same way again, so only transient failures
// (network errors, 5xx, rate limits, timeouts) are retried. Expired sign-ins
// (401) are reported by the API client itself, for every request.
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

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: shouldRetry } },
  });
}
