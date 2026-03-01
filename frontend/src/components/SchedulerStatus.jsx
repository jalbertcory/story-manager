import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const fetchStatus = async () => {
  const res = await fetch("/api/scheduler/status");
  if (!res.ok) throw new Error("Failed to fetch scheduler status");
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

function SchedulerStatus({ onBack }) {
  const queryClient = useQueryClient();

  const { data: task, isLoading } = useQuery({
    queryKey: ["scheduler-status"],
    queryFn: fetchStatus,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3000 : false,
  });

  const triggerMutation = useMutation({
    mutationFn: () =>
      fetch("/api/scheduler/trigger", { method: "POST" }).then((r) => r.json()),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["scheduler-status"] }),
  });

  const isRunning = task?.status === "running";

  return (
    <div className="book-settings">
      <div className="settings-header">
        <button onClick={onBack}>← Back</button>
        <h2>Scheduler</h2>
      </div>

      <section className="settings-section">
        <h3>Last Run</h3>
        {isLoading && <p>Loading...</p>}
        {!isLoading && !task && <p>No runs recorded yet.</p>}
        {task && (
          <div>
            <p>
              <strong>Status:</strong>{" "}
              <span className={`badge-config ${isRunning ? "badge-running" : ""}`}>
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
              <strong>Progress:</strong> {task.completed_books} / {task.total_books} books
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
    </div>
  );
}

export default SchedulerStatus;
