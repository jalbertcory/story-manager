import { renderHook, waitFor } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient } from "../lib/queryClient";
import useLibraryCatalog from "./useLibraryCatalog";

const json = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );

describe("useLibraryCatalog", () => {
  afterEach(() => vi.restoreAllMocks());

  it("refreshes the catalog when an active processing job finishes", async () => {
    let jobs = [{ id: 7, status: "running" }];
    const fetchMock = vi.fn((input: Request | string | URL) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes("/api/processing/jobs")) return json(jobs);
      return json({ items: [], next_cursor: null });
    });
    globalThis.fetch = fetchMock;
    const catalogCalls = () =>
      fetchMock.mock.calls.filter(([input]) =>
        String(input instanceof Request ? input.url : input).includes(
          "/api/books/catalog",
        ),
      ).length;

    const client = createQueryClient();
    client.setDefaultOptions({ queries: { retry: false } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useLibraryCatalog({ view: "all" }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    await waitFor(() =>
      expect(client.getQueryData(["active-processing-jobs"])).toEqual(jobs),
    );
    expect(catalogCalls()).toBe(1);

    jobs = [];
    await client.refetchQueries({ queryKey: ["active-processing-jobs"] });
    await waitFor(() => expect(catalogCalls()).toBe(2));
  });
});
