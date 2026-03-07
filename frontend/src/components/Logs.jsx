import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

const LEVELS = ["ALL", "ERROR", "WARNING", "INFO", "DEBUG"];

const LEVEL_COLORS = {
  ERROR: "#f87171",
  WARNING: "#fbbf24",
  INFO: "#60a5fa",
  DEBUG: "#9ca3af",
};

function Logs({ onBack }) {
  const [level, setLevel] = useState("ALL");
  const [autoRefresh, setAutoRefresh] = useState(true);

  const { data: logs = [], isLoading, dataUpdatedAt, refetch } = useQuery({
    queryKey: ["logs", level],
    queryFn: async () => {
      const param = level !== "ALL" ? `&level=${level}` : "";
      const res = await fetch(`/api/logs?limit=500${param}`);
      if (!res.ok) throw new Error("Failed to fetch logs");
      return res.json();
    },
    refetchInterval: autoRefresh ? 3000 : false,
  });

  const reversed = [...logs].reverse();

  return (
    <div className="book-settings">
      <div className="settings-header">
        <button className="btn-text" onClick={onBack} style={{ flexShrink: 0 }}>
          ← Back
        </button>
        <h2>Application Logs</h2>
      </div>

      <section className="settings-section">
        <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap", marginBottom: "0.75rem" }}>
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            {LEVELS.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
          <label style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.875rem" }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh
          </label>
          <button onClick={() => refetch()} style={{ marginLeft: "auto" }}>
            Refresh
          </button>
          {dataUpdatedAt > 0 && (
            <span className="hint" style={{ fontSize: "0.75rem" }}>
              Updated {new Date(dataUpdatedAt).toLocaleTimeString()}
            </span>
          )}
        </div>

        {isLoading && <p>Loading...</p>}
        {!isLoading && reversed.length === 0 && (
          <p className="hint">No log entries.</p>
        )}

        <div
          style={{
            fontFamily: "monospace",
            fontSize: "0.78rem",
            overflowY: "auto",
            maxHeight: "70vh",
            background: "var(--surface, #1a1a2e)",
            borderRadius: "6px",
            padding: "0.5rem",
            display: "flex",
            flexDirection: "column",
            gap: "1px",
          }}
        >
          {reversed.map((entry, i) => (
            <div
              key={i}
              style={{
                display: "grid",
                gridTemplateColumns: "160px 56px 1fr",
                gap: "0.5rem",
                padding: "2px 4px",
                borderRadius: "3px",
                lineHeight: "1.4",
              }}
            >
              <span style={{ color: "#6b7280", whiteSpace: "nowrap" }}>
                {new Date(entry.timestamp).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
              <span
                style={{
                  color: LEVEL_COLORS[entry.level] ?? "#9ca3af",
                  fontWeight: "600",
                  textAlign: "right",
                }}
              >
                {entry.level}
              </span>
              <span style={{ color: "#e2e8f0", wordBreak: "break-all" }}>
                {entry.message}
              </span>
            </div>
          ))}
        </div>
        <p className="hint" style={{ marginTop: "0.5rem" }}>
          Showing {reversed.length} entries (last 500, most recent first). Buffer holds up to 1000.
        </p>
      </section>
    </div>
  );
}

export default Logs;
