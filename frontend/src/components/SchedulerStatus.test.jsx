import { screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import SchedulerStatus from "./SchedulerStatus";
import { renderWithClient } from "../test-utils";

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
};

const mockTask = {
  id: 1,
  total_books: 5,
  completed_books: 5,
  status: "completed",
  started_at: new Date(Date.now() - 3600000).toISOString(),
  completed_at: new Date(Date.now() - 3500000).toISOString(),
};

const mockHistory = [
  {
    id: 2,
    total_books: 3,
    completed_books: 3,
    status: "completed",
    started_at: new Date(Date.now() - 1000).toISOString(),
    completed_at: new Date(Date.now() - 500).toISOString(),
  },
  {
    id: 1,
    total_books: 5,
    completed_books: 5,
    status: "completed",
    started_at: new Date(Date.now() - 90000000).toISOString(),
    completed_at: new Date(Date.now() - 89900000).toISOString(),
  },
];

const mockLogs = [
  {
    id: 1,
    book_id: 10,
    book_title: "Dragon's Lair",
    entry_type: "updated",
    previous_chapter_count: 20,
    new_chapter_count: 25,
    words_added: 8000,
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
    timestamp: new Date().toISOString(),
  },
];

describe("SchedulerStatus", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows no-runs message when status and history are empty", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockJob) });
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
    globalThis.fetch = vi.fn((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockJob) });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTask) });
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
    globalThis.fetch = vi.fn((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockJob) });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTask) });
      }
      if (url.includes("/api/scheduler/history") && !url.includes("/logs")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockHistory) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Run History")).toBeInTheDocument();
      // 3/3 books only appears in history (not in the current run which shows 5/5)
      expect(screen.getByText(/3 \/ 3 books/)).toBeInTheDocument();
      // 5/5 appears in both current run and history — just verify it's present
      expect(screen.getAllByText(/5 \/ 5 books/).length).toBeGreaterThan(0);
    });
  });

  it("expands a run to show per-book log entries", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockJob) });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTask) });
      }
      if (url.includes("/api/scheduler/history") && url.includes("/logs")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockLogs) });
      }
      if (url.includes("/api/scheduler/history")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockHistory) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    // Wait for history to load
    await waitFor(() => {
      expect(screen.getByText(/3 \/ 3 books/)).toBeInTheDocument();
    });

    // Click the first history row to expand it
    const expandButtons = screen.getAllByText(/▸/);
    fireEvent.click(expandButtons[0]);

    // Logs should now load and display
    await waitFor(() => {
      expect(screen.getByText("Dragon's Lair")).toBeInTheDocument();
      expect(screen.getByText("Moonlight")).toBeInTheDocument();
      expect(screen.getByText("Broken Orbit")).toBeInTheDocument();
      expect(screen.getByText("Errors (1)")).toBeInTheDocument();
    });

    // Updated entry shows chapter and word counts
    expect(screen.getByText(/20 → 25 ch/)).toBeInTheDocument();
    expect(screen.getByText(/\+8,000 words/)).toBeInTheDocument();
  });

  it("shows the configured schedule and next run timing", async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockJob) });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTask) });
      }
      if (url.includes("/api/scheduler/history")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });

    renderWithClient(<SchedulerStatus onBack={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("Automatic Schedule")).toBeInTheDocument();
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
    };
    const runningTask = {
      ...mockTask,
      status: "running",
      completed_at: null,
    };

    globalThis.fetch = vi.fn((url) => {
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(runningJob) });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(runningTask) });
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
    };

    globalThis.fetch = vi.fn((url, options) => {
      if (url === "/api/scheduler/config") {
        expect(options.method).toBe("PUT");
        expect(options.body).toContain("\"time_local\":\"06:30\"");
        expect(options.body).toContain("\"timezone\":");
        return Promise.resolve({ ok: true, json: () => Promise.resolve(savedJob) });
      }
      if (url.includes("/api/scheduler/job")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockJob) });
      }
      if (url.includes("/api/scheduler/status")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTask) });
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
      expect(screen.getByText("Daily at 6:30 AM (America/New_York)")).toBeInTheDocument();
    });
  });
});
