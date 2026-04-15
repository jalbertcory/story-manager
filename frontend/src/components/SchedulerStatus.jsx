import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const fetchStatus = async () => {
  const res = await fetch("/api/scheduler/status");
  if (!res.ok) throw new Error("Failed to fetch scheduler status");
  return res.json();
};

const fetchJob = async () => {
  const res = await fetch("/api/scheduler/job");
  if (!res.ok) throw new Error("Failed to fetch scheduler job");
  return res.json();
};

const fetchHistory = async () => {
  const res = await fetch("/api/scheduler/history?limit=10");
  if (!res.ok) throw new Error("Failed to fetch history");
  return res.json();
};

const fetchTaskLogs = async (taskId) => {
  const res = await fetch(`/api/scheduler/history/${taskId}/logs`);
  if (!res.ok) throw new Error("Failed to fetch task logs");
  return res.json();
};

function getBrowserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function timeAgo(dateStr) {
  if (!dateStr) return "Never";
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  return new Date(dateStr).toLocaleString();
}

function toTimeInputValue(dateStr) {
  if (!dateStr) return "06:00";
  const date = new Date(dateStr);
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${hours}:${minutes}`;
}

function formatTimeUntil(dateStr, now) {
  if (!dateStr) return "Not scheduled";

  const diff = new Date(dateStr).getTime() - now;
  if (diff <= 0) return "due now";

  const totalSeconds = Math.floor(diff / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function formatRunState(job) {
  if (!job) return "Unknown";
  if (job.run_in_progress) return "Running";
  if (job.last_run_status) {
    return job.last_run_status.charAt(0).toUpperCase() + job.last_run_status.slice(1);
  }
  return "Idle";
}

function TaskLogsList({ taskId }) {
  const { data: logs, isLoading } = useQuery({
    queryKey: ["task-logs", taskId],
    queryFn: () => fetchTaskLogs(taskId),
  });

  if (isLoading) return <p className="hint">Loading entries...</p>;
  if (!logs || logs.length === 0) return <p className="hint">No log entries for this run.</p>;

  const updatedLogs = logs.filter((l) => l.entry_type === "updated");
  const checkedLogs = logs.filter((l) => l.entry_type === "checked");
  const addedLogs = logs.filter((l) => l.entry_type === "added");
  const errorLogs = logs.filter((l) => l.entry_type === "error");

  return (
    <div className="task-logs">
      {updatedLogs.length > 0 && (
        <div>
          <p className="task-logs-group-label">Updated ({updatedLogs.length})</p>
          <ul className="task-logs-list">
            {updatedLogs.map((log) => (
              <li key={log.id} className="task-log-entry task-log-updated">
                <span className="task-log-title">{log.book_title}</span>
                <span className="task-log-detail">
                  {log.previous_chapter_count} → {log.new_chapter_count} ch
                  {log.words_added > 0 && ` (+${log.words_added.toLocaleString()} words)`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {addedLogs.length > 0 && (
        <div>
          <p className="task-logs-group-label">Added ({addedLogs.length})</p>
          <ul className="task-logs-list">
            {addedLogs.map((log) => (
              <li key={log.id} className="task-log-entry task-log-added">
                <span className="task-log-title">{log.book_title}</span>
                <span className="task-log-detail">{log.new_chapter_count} ch</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {checkedLogs.length > 0 && (
        <div>
          <p className="task-logs-group-label">Checked, no changes ({checkedLogs.length})</p>
          <ul className="task-logs-list task-logs-checked">
            {checkedLogs.map((log) => (
              <li key={log.id} className="task-log-entry task-log-checked">
                <span className="task-log-title">{log.book_title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {errorLogs.length > 0 && (
        <div>
          <p className="task-logs-group-label">Errors ({errorLogs.length})</p>
          <ul className="task-logs-list">
            {errorLogs.map((log) => (
              <li key={log.id} className="task-log-entry">
                <span className="task-log-title">{log.book_title}</span>
                <span className="task-log-detail">Update failed</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function TaskHistoryRow({ task }) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = task.status === "running";

  return (
    <div className="task-history-row">
      <button
        className="task-history-summary"
        onClick={() => setExpanded((e) => !e)}
      >
        <span className={`badge-config ${isRunning ? "badge-running" : ""}`}>
          {task.status}
        </span>
        <span className="task-history-date">{formatDate(task.started_at)}</span>
        <span className="hint">{task.completed_books} / {task.total_books} books</span>
        <span className="task-expand-icon">{expanded ? "▾" : "▸"}</span>
      </button>
      {expanded && <TaskLogsList taskId={task.id} />}
    </div>
  );
}

function SchedulerStatus({ onBack }) {
  const queryClient = useQueryClient();
  const [now, setNow] = useState(Date.now());
  const [scheduleTime, setScheduleTime] = useState("06:00");
  const [scheduleTimezone, setScheduleTimezone] = useState(() => getBrowserTimezone());
  const [scheduleDirty, setScheduleDirty] = useState(false);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(intervalId);
  }, []);

  const { data: task, isLoading: statusLoading } = useQuery({
    queryKey: ["scheduler-status"],
    queryFn: fetchStatus,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3000 : false,
  });

  const { data: job, isLoading: jobLoading } = useQuery({
    queryKey: ["scheduler-job"],
    queryFn: fetchJob,
    refetchInterval: task?.status === "running" ? 5000 : 60000,
  });

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ["scheduler-history"],
    queryFn: fetchHistory,
    refetchInterval: task?.status === "running" ? 5000 : false,
  });

  useEffect(() => {
    if (!job || scheduleDirty) return;
    setScheduleTime(job.schedule_time_local || toTimeInputValue(job.next_run_at));
    setScheduleTimezone(job.schedule_timezone || getBrowserTimezone());
  }, [job, scheduleDirty]);

  const triggerMutation = useMutation({
    mutationFn: () =>
      fetch("/api/scheduler/trigger", { method: "POST" }).then((r) => r.json()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduler-job"] });
      queryClient.invalidateQueries({ queryKey: ["scheduler-status"] });
      queryClient.invalidateQueries({ queryKey: ["scheduler-history"] });
    },
  });

  const scheduleMutation = useMutation({
    mutationFn: async ({ timeLocal, timezone }) => {
      const res = await fetch("/api/scheduler/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ time_local: timeLocal, timezone }),
      });
      if (!res.ok) {
        let detail = "Failed to update schedule";
        try {
          const body = await res.json();
          if (body?.detail) {
            detail = Array.isArray(body.detail)
              ? body.detail.map((item) => item.msg || item).join(", ")
              : body.detail;
          }
        } catch {
          // Ignore JSON parse failures and keep the default message.
        }
        throw new Error(detail);
      }
      return res.json();
    },
    onSuccess: (data) => {
      setScheduleDirty(false);
      queryClient.setQueryData(["scheduler-job"], data);
    },
  });

  const isRunning = task?.status === "running";
  const sectionTitle = job?.run_in_progress ? "Current Run" : "Latest Run";

  return (
    <div className={onBack ? "book-settings" : undefined}>
      {onBack && (
        <div className="settings-header">
          <button className="btn-text" onClick={onBack} style={{ flexShrink: 0 }}>← Back</button>
          <h2>Scheduler</h2>
        </div>
      )}

      <section className="settings-section">
        <h3>Automatic Schedule</h3>
        {jobLoading && <p>Loading...</p>}
        {job && (
          <>
            <div className="scheduler-grid">
              <div className="scheduler-stat">
                <span className="hint">Schedule</span>
                <strong className="scheduler-value">{job.schedule}</strong>
              </div>
              <div className="scheduler-stat">
                <span className="hint">Next Run</span>
                <strong className="scheduler-value">
                  {job.next_run_at ? formatDate(job.next_run_at) : "Not scheduled"}
                </strong>
              </div>
              <div className="scheduler-stat">
                <span className="hint">Time Until Next Run</span>
                <strong className="scheduler-value">
                  {formatTimeUntil(job.next_run_at, now)}
                </strong>
              </div>
              <div className="scheduler-stat">
                <span className="hint">Run State</span>
                <strong className="scheduler-value">
                  {formatRunState(job)}
                </strong>
              </div>
            </div>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                scheduleMutation.mutate({ timeLocal: scheduleTime, timezone: scheduleTimezone });
              }}
            >
              <label>
                Daily Run Time
                <input
                  type="time"
                  value={scheduleTime}
                  onChange={(event) => {
                    setScheduleDirty(true);
                    setScheduleTime(event.target.value);
                  }}
                />
              </label>
              <p className="hint">
                {job.schedule_mode === "daily_time"
                  ? `Saved in ${job.schedule_timezone}.`
                  : `Saving will switch from the rolling 24-hour interval to a fixed daily time in ${scheduleTimezone}.`}
              </p>
              <div className="settings-actions">
                <button type="submit" disabled={scheduleMutation.isPending}>
                  {scheduleMutation.isPending ? "Saving..." : "Save Schedule"}
                </button>
                {scheduleMutation.isError && (
                  <p className="error">Failed: {scheduleMutation.error.message}</p>
                )}
                {scheduleMutation.isSuccess && !scheduleMutation.isPending && (
                  <p className="hint">Daily schedule updated.</p>
                )}
              </div>
            </form>
          </>
        )}
      </section>

      <section className="settings-section">
        <h3>{sectionTitle}</h3>
        {statusLoading && <p>Loading...</p>}
        {!statusLoading && !task && <p>No runs recorded yet.</p>}
        {task && (
          <div>
            <p>
              <strong>Status:</strong>{" "}
              <span
                className={`badge-config ${isRunning ? "badge-running" : ""}`}
              >
                {task.status}
              </span>
            </p>
            <p>
              <strong>Started:</strong> {timeAgo(task.started_at)}
            </p>
            {task.completed_at && (
              <p>
                <strong>Completed:</strong> {timeAgo(task.completed_at)}
              </p>
            )}
            <p>
              <strong>Progress:</strong> {task.completed_books} /{" "}
              {task.total_books} books
            </p>
          </div>
        )}
      </section>

      <section className="settings-section settings-actions">
        <button
          onClick={() => triggerMutation.mutate()}
          disabled={isRunning || triggerMutation.isPending}
        >
          {triggerMutation.isPending ? "Triggering..." : "Run Now"}
        </button>
        {triggerMutation.isError && (
          <p className="error">Failed: {triggerMutation.error.message}</p>
        )}
        {triggerMutation.isSuccess && !isRunning && (
          <p className="hint">Update triggered.</p>
        )}
      </section>

      <section className="settings-section">
        <h3>Run History</h3>
        {historyLoading && <p>Loading...</p>}
        {!historyLoading && (!history || history.length === 0) && (
          <p className="hint">No history yet.</p>
        )}
        {history && history.map((t) => (
          <TaskHistoryRow key={t.id} task={t} />
        ))}
      </section>
    </div>
  );
}

export default SchedulerStatus;
