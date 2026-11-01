import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { components } from "../api/schema";
import CleaningConfigs from "./CleaningConfigs";
import { renderWithClient } from "../test-utils";

type ReprocessStatus = components["schemas"]["ReprocessStatus"];

type Config = components["schemas"]["CleaningConfig"];

function mockApi(statuses: ReprocessStatus[], configs: Config[] = []) {
  let call = 0;
  const fetchMock = vi.fn((url: string, init?: Parameters<typeof fetch>[1]) => {
    let body: unknown = configs;
    if (init?.method === "DELETE")
      return Promise.resolve(new Response(null, { status: 204 }));
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
  globalThis.fetch = fetchMock as typeof fetch;
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
  it("confirms in a dialog before deleting a config", async () => {
    const fetchMock = mockApi(
      [{ running: false, total: 0, processed: 0 }],
      [
        {
          id: 3,
          name: "Royal Road notes",
          url_pattern: "royalroad",
          chapter_selectors: [],
          content_selectors: ["div.author-note"],
        } satisfies Config,
      ],
    );
    const deletes = () =>
      fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE");
    renderWithClient(<CleaningConfigs />);

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", {
      name: "Delete cleaning config “Royal Road notes”?",
    });
    expect(dialog).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(deletes()).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete config" }));
    await waitFor(() => expect(deletes()).toHaveLength(1));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});
