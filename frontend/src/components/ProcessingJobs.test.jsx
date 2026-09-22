import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProcessingJobs from "./ProcessingJobs";

vi.mock("../hooks/useLifecycleDefinitions", () => ({
  default: () => ({
    data: {
      processing_job: {
        states: [
          { value: "queued", label: "Queued" },
          { value: "running", label: "Running" },
          { value: "completed", label: "Completed" },
          { value: "error", label: "Failed" },
          { value: "canceled", label: "Canceled" },
        ],
        active_states: ["queued", "running"],
        terminal_states: ["completed", "error", "canceled"],
        retryable_states: ["error", "canceled"],
        groups: { running: ["running"], waiting: ["queued"] },
      },
    },
  }),
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ProcessingJobs />
    </QueryClientProvider>,
  );
}

describe("ProcessingJobs", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn(async (url) => {
      if (String(url).startsWith("/api/books/catalog")) {
        return {
          ok: true,
          json: async () => [
            {
              id: 7,
              title: "Queued Story",
              author: "Test Author",
              source_type: "epub",
              audiobook_enabled: true,
            },
          ],
        };
      }
      return {
        ok: true,
        json: async () => [
          {
            id: 42,
            job_type: "clean_book",
            status: "running",
            book_id: 7,
            book_title: "Queued Story",
            target_type: "book",
            target_id: 7,
            target_content_version: 2,
            parent_job_id: null,
            request_id: "request-42",
            payload: {},
            progress_current: 1,
            progress_total: 3,
            progress_detail: "Cleaning chapters",
            attempt_count: 1,
            cancel_requested: false,
            error: null,
            created_at: "2026-07-31T12:00:00Z",
            started_at: "2026-07-31T12:00:01Z",
            completed_at: null,
          },
        ],
      };
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows active durable jobs and their progress", async () => {
    renderPage();
    expect(
      await screen.findByRole("link", { name: "Queued Story" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Cleaning chapters")).toBeInTheDocument();
    expect(screen.getByText("33% · 1 / 3")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveValue(1);
    expect(screen.getByText(/Request request-42/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("keeps the dispatch controls collapsed until requested", async () => {
    renderPage();
    const summary = await screen.findByText("Queue work");
    const panel = summary.closest("details");

    expect(panel).not.toHaveAttribute("open");
    fireEvent.click(summary.closest("summary"));
    expect(panel).toHaveAttribute("open");
  });

  it("confirms library-wide jobs before queueing them", async () => {
    const posts = [];
    const listFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async (url, options) => {
      if (options?.method === "POST") {
        posts.push(JSON.parse(options.body));
        return Response.json({ jobs: [] });
      }
      return listFetch(url, options);
    });
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "Clean entire library" }),
    );
    const cleanDialog = screen.getByRole("dialog", {
      name: "Clean the entire library?",
    });
    expect(posts).toEqual([]);

    fireEvent.click(
      within(cleanDialog).getByRole("button", { name: "Cancel" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posts).toEqual([]);

    fireEvent.click(
      screen.getByRole("button", { name: "Refresh all web books" }),
    );
    const dialog = screen.getByRole("dialog", {
      name: "Refresh all web books?",
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Refresh all web books" }),
    );

    await waitFor(() =>
      expect(posts).toEqual([
        {
          job_type: "refresh_all",
          book_ids: [],
          payload: { trigger: "manual" },
        },
      ]),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });
});
