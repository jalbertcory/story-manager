import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { components } from "../api/schema";
import CleaningConfigs from "./CleaningConfigs";
import { renderWithClient } from "../test-utils";

type ReprocessStatus = components["schemas"]["ReprocessStatus"];

function mockApi(statuses: ReprocessStatus[]) {
  let call = 0;
  const fetchMock = vi.fn((input: Request | string | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    let body: unknown = [];
    if (url.includes("/api/books/reprocess-all/status")) {
      body = statuses[Math.min(call, statuses.length - 1)];
      call += 1;
    }
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  globalThis.fetch = fetchMock;
  return fetchMock;
}

describe("CleaningConfigs", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("resumes progress polling for a clean already running when mounted", async () => {
    mockApi([
      { running: true, total: 4, processed: 1 },
      { running: true, total: 4, processed: 3 },
      { running: false, total: 4, processed: 4, status: "completed" },
    ]);
    renderWithClient(<CleaningConfigs />);

    expect(
      await screen.findByText(/1 \/ 4 books\s+processed/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cleaning..." })).toBeDisabled();

    expect(
      await screen.findByText(/3 \/ 4 books\s+processed/, undefined, {
        timeout: 3000,
      }),
    ).toBeInTheDocument();
    await waitFor(
      () =>
        expect(
          screen.getByRole("button", { name: "Clean All Books" }),
        ).toBeEnabled(),
      { timeout: 3000 },
    );
    expect(screen.getByText("Cleaning job completed.")).toBeInTheDocument();
  }, 10_000);
});
