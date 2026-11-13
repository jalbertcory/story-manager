import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import type { components } from "../api/schema";
import SchedulerStatus from "./SchedulerStatus";
import { mockFetch, renderWithClient } from "../test-utils";

type SchedulerJob = components["schemas"]["SchedulerJobStatus"];
type UpdateTask = components["schemas"]["UpdateTask"];
type RunSummary = components["schemas"]["UpdateTaskSummary"];
type BookLog = components["schemas"]["BookLogWithTitle"];

const mockJob = {
  job_id: "update_web_novels",
  schedule: "Every 24 hours",
  schedule_mode: "interval",
  schedule_time_local: null,
  schedule_timezone: null,
  next_run_at: new Date(Date.now() + 7200000).toISOString(),
  scheduler_running: true,
  run_in_progress: false,
  last_run_started_at: new Date(Date.now() - 3600000).toISOString(),
  last_run_completed_at: new Date(Date.now() - 3500000).toISOString(),
  last_run_status: "completed",
} satisfies SchedulerJob;

const mockTask = {
  id: 1,
  total_books: 5,
  completed_books: 5,
  status: "completed",
  started_at: new Date(Date.now() - 3600000).toISOString(),
  completed_at: new Date(Date.now() - 3500000).toISOString(),
} satisfies UpdateTask;

const mockHistory = [
  {
    id: 2,
    total_books: 3,
    completed_books: 3,
    status: "completed",
    started_at: new Date(Date.now() - 1000).toISOString(),
    completed_at: new Date(Date.now() - 500).toISOString(),
    updated_count: 1,
    unchanged_count: 1,
    failed_count: 1,
  },
  {
    id: 1,
    total_books: 5,
    completed_books: 5,
    status: "completed",
    started_at: new Date(Date.now() - 90000000).toISOString(),
    completed_at: new Date(Date.now() - 89900000).toISOString(),
    updated_count: 0,
    unchanged_count: 5,
    failed_count: 0,
  },
] satisfies RunSummary[];

const mockLogs = [
  {
    id: 1,
    book_id: 10,
    book_title: "Dragon's Lair",
    entry_type: "updated",
    previous_chapter_count: 20,
    new_chapter_count: 25,
    words_added: 8000,
    detail: null,
    timestamp: new Date().toISOString(),
  },
  {
    id: 2,
    book_id: 11,
    book_title: "Moonlight",
    entry_type: "checked",
    previous_chapter_count: 10,
    new_chapter_count: 10,
    words_added: 0,
    detail: null,
    timestamp: new Date().toISOString(),
  },
  {
    id: 3,
    book_id: 12,
    book_title: "Broken Orbit",
    entry_type: "error",
    previous_chapter_count: 7,
    new_chapter_count: 7,
    words_added: 0,
    detail: "Source site returned 404",
    timestamp: new Date().toISOString(),
  },
] satisfies BookLog[];

describe("SchedulerStatus", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows no-runs message when status and history are empty", async () => {
    mockFetch((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockJob),
        });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
      }
      if (url.includes("/api/scheduler/history")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(null) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("No runs recorded yet.")).toBeInTheDocument();
      expect(screen.getByText("No history yet.")).toBeInTheDocument();
    });
  });

  it("displays current run status", async () => {
    mockFetch((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockJob),
        });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockTask),
        });
      }
      // Return empty history so the current run section is unambiguous
      if (url.includes("/api/scheduler/history") && !url.includes("/logs")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Latest Run")).toBeInTheDocument();
      // "Status:" label is only in the current run section
      expect(screen.getByText(/Started:/)).toBeInTheDocument();
      expect(screen.getByText(/Progress:/)).toBeInTheDocument();
    });
  });

  it("displays run history list", async () => {
    mockFetch((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockJob),
        });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockTask),
        });
      }
      if (url.includes("/api/scheduler/history") && !url.includes("/logs")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockHistory),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Previous checks")).toBeInTheDocument();
      // Each run says what it found without being expanded.
      expect(
        screen.getByText(
          (_, element) =>
            element?.className === "task-history-outcome" &&
            element.textContent === "1 updated · 1 unchanged · 1 failed",
        ),
      ).toBeInTheDocument();
      // 3/3 books only appears in history (not in the current run which shows 5/5)
      expect(screen.getByText(/3 \/ 3 books/)).toBeInTheDocument();
      // 5/5 appears in both current run and history — just verify it's present
      expect(screen.getAllByText(/5 \/ 5 books/).length).toBeGreaterThan(0);
    });
  });

  it("expands a run to show per-book log entries", async () => {
    mockFetch((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockJob),
        });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockTask),
        });
      }
      if (url.includes("/api/scheduler/history") && url.includes("/logs")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockLogs),
        });
      }
      if (url.includes("/api/scheduler/history")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockHistory),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    // Wait for history to load
    await waitFor(() => {
      expect(screen.getByText(/3 \/ 3 books/)).toBeInTheDocument();
    });

    // Click the first history row to expand it
    const [firstExpandButton] = screen.getAllByText(/▸/);
    // getAllByText throws when nothing matches, so the first entry exists.
    fireEvent.click(firstExpandButton!);

    // Logs should now load and display
    await waitFor(() => {
      expect(screen.getByText("Dragon's Lair")).toBeInTheDocument();
      expect(screen.getByText("Moonlight")).toBeInTheDocument();
      expect(screen.getByText("Broken Orbit")).toBeInTheDocument();
      expect(screen.getByText(/Failed \(1\)/)).toBeInTheDocument();
      expect(screen.getByText("Source site returned 404")).toBeInTheDocument();
    });

    // Updated entry shows chapter and word counts
    expect(screen.getByText(/20 → 25 ch/)).toBeInTheDocument();
    expect(screen.getByText(/\+8,000 words/)).toBeInTheDocument();
  });

  it("shows the configured schedule and next run timing", async () => {
    mockFetch((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockJob),
        });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockTask),
        });
      }
      if (url.includes("/api/scheduler/history")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Automatic schedule")).toBeInTheDocument();
      expect(screen.getByText("Every 24 hours")).toBeInTheDocument();
      expect(screen.getByText("Completed")).toBeInTheDocument();
      expect(screen.getByText("Time Until Next Run")).toBeInTheDocument();
      expect(screen.getByText("Run State")).toBeInTheDocument();
    });
  });

  it("shows current run when a job is actively executing", async () => {
    const runningJob = {
      ...mockJob,
      run_in_progress: true,
      last_run_status: "running",
    } satisfies SchedulerJob;
    const runningTask = {
      ...mockTask,
      status: "running",
      completed_at: null,
    } satisfies UpdateTask;

    mockFetch((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(runningJob),
        });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(runningTask),
        });
      }
      if (url.includes("/api/scheduler/history")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Current Run")).toBeInTheDocument();
      expect(screen.getAllByText("Running").length).toBeGreaterThan(0);
    });
  });

  it("saves a daily scheduler time from the app", async () => {
    const savedJob = {
      ...mockJob,
      schedule: "Daily at 6:30 AM (America/New_York)",
      schedule_mode: "daily_time",
      schedule_time_local: "06:30",
      schedule_timezone: "America/New_York",
    } satisfies SchedulerJob;

    mockFetch((url, options) => {
      if (url === "/api/scheduler/config") {
        expect(options?.method).toBe("PUT");
        expect(options?.body).toContain('"time_local":"06:30"');
        expect(options?.body).toContain('"timezone":');
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(savedJob),
        });
      }
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockJob),
        });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(mockTask),
        });
      }
      if (url.includes("/api/scheduler/history")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    const timeInput = await screen.findByLabelText("Daily Run Time");
    fireEvent.change(timeInput, { target: { value: "06:30" } });
    fireEvent.click(screen.getByText("Save Schedule"));

    await waitFor(() => {
      expect(screen.getByText("Daily schedule updated.")).toBeInTheDocument();
      expect(
        screen.getByText("Daily at 6:30 AM (America/New_York)"),
      ).toBeInTheDocument();
    });
  });
});
