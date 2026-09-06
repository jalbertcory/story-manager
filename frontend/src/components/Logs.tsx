import { getLogs, getHealth, getJobMetrics } from "../api/admin";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

const LEVELS = ["ALL", "ERROR", "WARNING", "INFO", "DEBUG"];

const LEVEL_COLORS: Record<string, string> = {
  ERROR: "#f87171",
  WARNING: "#fbbf24",
  INFO: "#60a5fa",
  DEBUG: "#9ca3af",
};

function HealthCard({
  label,
  status,
  detail,
}: {
  label: string;
  status?: string;
  detail?: string;
}) {
  const healthy = ["alive", "available", "configured"].includes(status ?? "");
  return (
    <div
      className={`observability-card observability-card--${healthy ? "healthy" : "muted"}`}
    >
      <span>{label}</span>
      <strong>{status || "unknown"}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}

function formatDuration(value: number | null | undefined) {
  if (value == null) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

function Logs({ onBack }: { onBack?: () => void }) {
  const [level, setLevel] = useState("ALL");
  const [autoRefresh, setAutoRefresh] = useState(true);

  const logsQuery = useQuery({
    queryKey: ["logs", level],
    queryFn: () =>
      getLogs({ limit: 500, level: level !== "ALL" ? level : undefined }),
    refetchInterval: autoRefresh ? 3000 : false,
  });
  const healthQuery = useQuery({
    queryKey: ["observability-health"],
    queryFn: getHealth,
    refetchInterval: autoRefresh ? 10000 : false,
  });
  const metricsQuery = useQuery({
    queryKey: ["observability-job-metrics"],
    queryFn: () => getJobMetrics(24),
    refetchInterval: autoRefresh ? 10000 : false,
  });

  const logs = logsQuery.data || [];
  const health = healthQuery.data;
  const metrics = metricsQuery.data;
  const reversed = [...logs].reverse();
  const refreshAll = () => {
    logsQuery.refetch();
    healthQuery.refetch();
    metricsQuery.refetch();
  };

  return (
    <div className={onBack ? "book-settings" : undefined}>
      <div className="settings-header">
        {onBack && (
          <button
            className="btn-text"
            onClick={onBack}
            style={{ flexShrink: 0 }}
          >
            ← Back
          </button>
        )}
        <h2>Application Logs</h2>
      </div>

      <section className="settings-section observability-overview">
        <div className="observability-heading">
          <div>
            <h3>System health</h3>
            <p className="hint">
              Required services and optional AI providers, without exposing
              credentials.
            </p>
          </div>
          <a
            className="btn-secondary"
            href="/api/observability/diagnostics"
            download
          >
            Download diagnostic bundle
          </a>
        </div>
        {healthQuery.isLoading && <p>Loading health…</p>}
        {health && (
          <div className="observability-grid">
            <HealthCard label="Database" status={health.database.status} />
            <HealthCard
              label="Workers"
              status={health.workers.status}
              detail={`${health.workers.active_workers}/${health.workers.configured_workers} active`}
            />
            <HealthCard
              label="Storage"
              status={health.storage.status}
              detail={
                health.storage.percent_free != null
                  ? `${health.storage.percent_free}% free`
                  : undefined
              }
            />
            {health.providers.map((provider) => (
              <HealthCard
                key={provider.capability}
                label={provider.capability.toUpperCase()}
                status={provider.status}
                detail={
                  provider.configured_endpoints
                    ? `${provider.configured_endpoints} endpoint(s)`
                    : "Optional"
                }
              />
            ))}
          </div>
        )}

        {metrics && (
          <div className="observability-metrics">
            <h3>Background jobs · last 24 hours</h3>
            {Object.keys(metrics.by_job_type).length === 0 ? (
              <p className="hint">No background jobs during this window.</p>
            ) : (
              <div className="observability-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Job type</th>
                      <th>Total</th>
                      <th>Failed</th>
                      <th>Canceled</th>
                      <th>Retries</th>
                      <th>Queue delay</th>
                      <th>Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(metrics.by_job_type).map(
                      ([jobType, values]) => (
                        <tr key={jobType}>
                          <td>{jobType.replaceAll("_", " ")}</td>
                          <td>{values.total}</td>
                          <td>{values.failed}</td>
                          <td>{values.canceled}</td>
                          <td>{values.retries}</td>
                          <td>
                            {formatDuration(values.average_queue_delay_ms)}
                          </td>
                          <td>{formatDuration(values.average_duration_ms)}</td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="settings-section">
        <div className="observability-controls">
          <select
            aria-label="Log level"
            value={level}
            onChange={(event) => setLevel(event.target.value)}
          >
            {LEVELS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <label>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.target.checked)}
            />
            Auto-refresh
          </label>
          <button onClick={refreshAll} style={{ marginLeft: "auto" }}>
            Refresh
          </button>
          {logsQuery.dataUpdatedAt > 0 && (
            <span className="hint">
              Updated {new Date(logsQuery.dataUpdatedAt).toLocaleTimeString()}
            </span>
          )}
        </div>

        {logsQuery.isLoading && <p>Loading…</p>}
        {!logsQuery.isLoading && reversed.length === 0 && (
          <p className="hint">No log entries.</p>
        )}

        <div className="observability-logs">
          {reversed.map((entry, index) => (
            <div
              className="observability-log-row"
              key={`${entry.timestamp}-${index}`}
            >
              <span className="observability-time">
                {new Date(entry.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
              <span
                className="observability-level"
                style={{ color: LEVEL_COLORS[entry.level] ?? "#9ca3af" }}
              >
                {entry.level}
              </span>
              <span className="observability-message">
                {entry.message}
                {(entry.request_id || entry.job_id != null) && (
                  <small>
                    {entry.request_id && `request ${entry.request_id}`}
                    {entry.request_id && entry.job_id != null && " · "}
                    {entry.job_id != null && `job ${entry.job_id}`}
                  </small>
                )}
              </span>
            </div>
          ))}
        </div>
        <p className="hint">
          Showing {reversed.length} entries (last 500, most recent first).
          Recent logs survive restarts.
        </p>
      </section>
    </div>
  );
}

export default Logs;
