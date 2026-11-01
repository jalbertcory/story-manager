import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { shouldRetry } from "./queryClient";

describe("shouldRetry", () => {
  it("does not retry client errors", () => {
    expect(shouldRetry(0, new ApiError("Unauthorized", 401))).toBe(false);
    expect(shouldRetry(0, new ApiError("Missing", 404))).toBe(false);
  });

  it("retries transient failures a few times", () => {
    expect(shouldRetry(0, new ApiError("Unavailable", 503))).toBe(true);
    expect(shouldRetry(0, new ApiError("Slow down", 429))).toBe(true);
    expect(shouldRetry(0, new TypeError("Failed to fetch"))).toBe(true);
    expect(shouldRetry(3, new TypeError("Failed to fetch"))).toBe(false);
  });
});
