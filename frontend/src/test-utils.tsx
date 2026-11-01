import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { vi } from "vitest";

import { createQueryClient } from "./lib/queryClient";

// What a test's fetch mock may resolve to: a real Response, or the minimal
// `{ ok, status, json }` shape tests/setup.ts turns into one.
export type FixtureResponse =
  | Response
  | { ok?: boolean; status?: number; json: () => unknown };

export type FixtureFetch = (
  url: string,
  init?: RequestInit,
) => Promise<FixtureResponse>;

// Replaces the global fetch with a typed mock of the URL/init overload the
// component fixtures answer.
export function mockFetch(implementation?: FixtureFetch) {
  const fetchMock = vi.fn<FixtureFetch>(implementation);
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

// A fixture response carrying `body` as its JSON.
export const jsonResponse = (body: unknown, status = 200) => ({
  ok: status < 400,
  status,
  json: () => Promise.resolve(body),
});

// The app's client (with its global 401 handling), minus retries so failures
// surface immediately.
const createTestQueryClient = () => {
  const client = createQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });
  return client;
};

export const renderWithClient = (ui: ReactNode) => {
  const testQueryClient = createTestQueryClient();
  const { rerender, ...result } = render(
    <QueryClientProvider client={testQueryClient}>{ui}</QueryClientProvider>,
  );
  return {
    ...result,
    queryClient: testQueryClient,
    rerender: (rerenderUi: ReactNode) =>
      rerender(
        <QueryClientProvider client={testQueryClient}>
          {rerenderUi}
        </QueryClientProvider>,
      ),
  };
};
