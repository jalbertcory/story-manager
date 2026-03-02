import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const fetchStatus = async () => {
  const res = await fetch("/api/scheduler/status");
  if (!res.ok) throw new Error("Failed to fetch scheduler status");
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

  const { data: task, isLoading: statusLoading } = useQuery({
    queryKey: ["scheduler-status"],
    queryFn: fetchStatus,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3000 : false,
  });

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ["scheduler-history"],
    queryFn: fetchHistory,
    refetchInterval: task?.status === "running" ? 5000 : false,
  });

  const triggerMutation = useMutation({
    mutationFn: () =>
      fetch("/api/scheduler/trigger", { method: "POST" }).then((r) => r.json()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scheduler-status"] });
      queryClient.invalidateQueries({ queryKey: ["scheduler-history"] });
    },
  });

  const isRunning = task?.status === "running";

  return (
    <div className="book-settings">
      <div className="settings-header">
        <button onClick={onBack}>← Back</button>
        <h2>Scheduler</h2>
      </div>

      <section className="settings-section">
        <h3>Current Run</h3>
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
