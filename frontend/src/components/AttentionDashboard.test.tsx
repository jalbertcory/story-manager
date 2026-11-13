import { renderWithClient as render, type FixtureFetch } from "../test-utils";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../api/schema";
import AttentionDashboard from "./AttentionDashboard";

type Dashboard = components["schemas"]["AttentionDashboard"];
type JobItem = components["schemas"]["AttentionJobItem"];
type BookItem = components["schemas"]["AttentionBookItem"];
type FileItem = components["schemas"]["AttentionFileItem"];
type MetadataItem = components["schemas"]["AttentionMetadataItem"];

afterEach(() => vi.unstubAllGlobals());

const emptyCategory = { count: 0, items: [] };

function dashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    total_count: 0,
    failed_jobs: emptyCategory,
    failed_refreshes: emptyCategory,
    stale_audiobooks: emptyCategory,
    metadata_proposals: emptyCategory,
    broken_files: emptyCategory,
    missing_covers: emptyCategory,
    ...overrides,
  };
}

const jobItem = (overrides: Partial<JobItem> = {}): JobItem => ({
  id: 1,
  job_type: "refresh_book",
  book_id: null,
  book_title: null,
  error: null,
  completed_at: null,
  ...overrides,
});

const bookItem = (overrides: Partial<BookItem> = {}): BookItem => ({
  book_id: 1,
  title: "Book",
  author: "Test Author",
  issue: "refresh_failed",
  detail: null,
  can_retry_refresh: false,
  ...overrides,
});

const fileItem = (overrides: Partial<FileItem> = {}): FileItem => ({
  book_id: 1,
  title: "Book",
  author: "Test Author",
  issue: "missing_file",
  detail: null,
  path: null,
  can_retry_cover: false,
  can_retry_refresh: false,
  ...overrides,
});

const metadataItem = (overrides: Partial<MetadataItem> = {}): MetadataItem => ({
  proposal_id: 1,
  book_id: 1,
  title: "Book",
  author: "Test Author",
  note: null,
  ...overrides,
});

type DashboardProps = ComponentProps<typeof AttentionDashboard>;

const renderDashboard = (props: Partial<DashboardProps>) =>
  render(
    <AttentionDashboard
      data={undefined}
      isLoading={false}
      error={null}
      isRefreshing={false}
      onRefresh={() => {}}
      {...props}
    />,
  );

describe("AttentionDashboard", () => {
  it("shows a clear healthy state", () => {
    renderDashboard({ data: dashboard() });

    expect(screen.getByText("Your library looks healthy.")).toBeInTheDocument();
    expect(screen.getAllByText("No attention needed")).toHaveLength(6);
  });

  it("shows actionable items and their destinations", () => {
    const data = dashboard({
      total_count: 3,
      failed_jobs: {
        count: 1,
        items: [
          jobItem({
            id: 8,
            job_type: "refresh_book",
            book_id: 2,
            book_title: "Failed Story",
            error: "Source unavailable",
          }),
        ],
      },
      stale_audiobooks: {
        count: 1,
        items: [
          bookItem({
            book_id: 3,
            title: "Stale Audio",
            author: "Narrator",
            issue: "audiobook_stale",
            detail: "Generated audiobook needs reconciliation.",
          }),
        ],
      },
      metadata_proposals: {
        count: 1,
        items: [
          metadataItem({
            proposal_id: 9,
            book_id: 4,
            title: "Metadata Book",
            author: "Metadata Author",
            note: "Review genres",
          }),
        ],
      },
    });

    renderDashboard({ data });

    expect(screen.getByText("Source unavailable")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review jobs" })).toHaveAttribute(
      "href",
      "/activity/processing?status=error",
    );
    expect(screen.getByRole("link", { name: "Stale Audio" })).toHaveAttribute(
      "href",
      "/books/3/audiobooks?tab=sources",
    );
    expect(
      screen.getByRole("link", { name: "Review metadata" }),
    ).toHaveAttribute("href", "/review");
  });

  it("lets the user retry a failed dashboard request", () => {
    const refresh = vi.fn();
    renderDashboard({
      error: new Error("Dashboard unavailable"),
      onRefresh: refresh,
    });

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refresh).toHaveBeenCalledOnce();
  });
});

it("queues cover recovery once, reports progress, and refreshes on completion", async () => {
  const onRefresh = vi.fn();
  const job = {
    id: 22,
    status: "queued",
    progress_detail: "Cover recovery queued",
  };
  const fetch = vi.fn<FixtureFetch>((url) =>
    Promise.resolve({
      ok: true,
      json: async () =>
        url === "/api/processing/jobs"
          ? { jobs: [job] }
          : { ...job, status: "completed", progress_detail: "Done" },
    }),
  );
  vi.stubGlobal("fetch", fetch);
  renderDashboard({
    onRefresh: onRefresh,
    data: dashboard({
      total_count: 1,
      missing_covers: {
        count: 1,
        items: [
          fileItem({
            book_id: 7,
            title: "Coverless",
            issue: "missing_cover",
            can_retry_cover: true,
          }),
        ],
      },
    }),
  });
  const button = screen.getByRole("button", {
    name: "Recover cover for Coverless",
  });
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(onRefresh).toHaveBeenCalledOnce());
  expect(
    fetch.mock.calls.filter(([url]) => url === "/api/processing/jobs"),
  ).toHaveLength(1);
  const queueBody = fetch.mock.calls[0]?.[1]?.body;
  expect(typeof queueBody).toBe("string");
  expect(JSON.parse(String(queueBody))).toEqual({
    job_type: "retry_cover",
    book_ids: [7],
    payload: {},
  });
  expect(
    await screen.findByText(/Coverless: Task completed/),
  ).toBeInTheDocument();
});

it("keeps bulk failures visible and allows retrying failed items", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn<FixtureFetch>((_url, options) => {
      const body: { book_ids: number[] } | undefined =
        typeof options?.body === "string"
          ? JSON.parse(options.body)
          : undefined;
      return Promise.resolve({
        ok: body?.book_ids[0] !== 8,
        json: async () =>
          body?.book_ids[0] === 8
            ? { detail: "Source is unavailable" }
            : body
              ? { jobs: [{ id: 21, status: "running" }] }
              : { id: 21, status: "running" },
      });
    }),
  );
  renderDashboard({
    onRefresh: vi.fn(),
    data: dashboard({
      total_count: 2,
      failed_refreshes: {
        count: 2,
        items: [7, 8].map((id) =>
          bookItem({
            book_id: id,
            title: `Book ${id}`,
            can_retry_refresh: true,
          }),
        ),
      },
    }),
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Retry shown checks (2)" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Book 8: Source is unavailable",
  );
  expect(
    screen.getByRole("button", { name: "Retry update check for Book 7" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Retry update check for Book 8" }),
  ).toBeEnabled();
});

it("retries a failed processing job through its existing endpoint", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: async () => ({ id: 8, status: "queued" }),
      }),
    ),
  );
  renderDashboard({
    onRefresh: vi.fn(),
    data: dashboard({
      total_count: 1,
      failed_jobs: {
        count: 1,
        items: [
          jobItem({ id: 8, job_type: "refresh_book", book_title: "Story" }),
        ],
      },
    }),
  });
  fireEvent.click(screen.getByRole("button", { name: "Retry task for Story" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/processing/jobs/8/retry",
      expect.objectContaining({
        method: "POST",
      }),
    ),
  );
});

it("shows a retryable error when a queue request returns no jobs", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ jobs: [] }),
    }),
  );
  renderDashboard({
    onRefresh: vi.fn(),
    data: dashboard({
      total_count: 1,
      failed_refreshes: {
        count: 1,
        items: [
          bookItem({
            book_id: 7,
            title: "Missing job",
            can_retry_refresh: true,
          }),
        ],
      },
    }),
  });
  const button = screen.getByRole("button", {
    name: "Retry update check for Missing job",
  });
  fireEvent.click(button);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The server did not queue a job. Please retry.",
  );
  expect(button).toBeEnabled();
  fireEvent.click(button);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
});
