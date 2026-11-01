import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import type { components } from "../api/schema";
import { jsonResponse, mockFetch } from "../test-utils";
import type { FixtureFetch } from "../test-utils";
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

type CatalogBook = components["schemas"]["BookCatalogEntry"];
type ProcessingJob = components["schemas"]["ProcessingJob"];

const catalogBook = {
  id: 7,
  title: "Queued Story",
  author: "Test Author",
  source_type: "epub",
  audiobook_enabled: true,
  audio_playable: false,
  audiobook_pipeline_status: null,
  audiobook_types: [],
  cover_path: null,
  current_word_count: null,
  download_status: null,
  effective_genre_tags: null,
  effective_series_genre_tags: null,
  genre_tags: null,
  has_epub: true,
  refresh_status: null,
  series: null,
  series_index: null,
  series_user_genre_tags: null,
  source_url: null,
  universe_id: null,
  universe_name: null,
  updated_at: null,
  user_genre_tags: null,
} satisfies CatalogBook;

const runningJob = {
  id: 42,
  job_type: "clean_book",
  status: "running",
  resource_lane: "cpu",
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
  max_attempts: 3,
  cancel_requested: false,
  error: null,
  available_at: "2026-07-31T12:00:00Z",
  created_at: "2026-07-31T12:00:00Z",
  started_at: "2026-07-31T12:00:01Z",
  heartbeat_at: "2026-07-31T12:00:02Z",
  lease_expires_at: "2026-07-31T12:05:01Z",
  completed_at: null,
} satisfies ProcessingJob;

describe("ProcessingJobs", () => {
  let listFetch: Mock<FixtureFetch>;

  beforeEach(() => {
    listFetch = mockFetch(async (url) => {
      if (url.startsWith("/api/books/catalog")) {
        return jsonResponse({
          items: [catalogBook],
          next_cursor: null,
          total_count: 1,
          facets: null,
        } satisfies components["schemas"]["BookCatalogPage"]);
      }
      return jsonResponse([runningJob]);
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
    const toggle = summary.closest("summary");
    expect(toggle).not.toBeNull();
    fireEvent.click(toggle!);
    expect(panel).toHaveAttribute("open");
  });

  it("confirms library-wide jobs before queueing them", async () => {
    const posts: unknown[] = [];
    mockFetch(async (url, options) => {
      if (options?.method === "POST") {
        posts.push(JSON.parse(String(options.body)));
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

  it("shows why cancelling a job failed", async () => {
    mockFetch(async (url, options) => {
      if (options?.method === "DELETE") {
        return Response.json(
          { detail: "Job already finished" },
          { status: 409 },
        );
      }
      return listFetch(url, options);
    });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cancel failed: Job already finished",
    );
  });
});
