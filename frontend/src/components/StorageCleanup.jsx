import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function runCleanup(dryRun) {
  const res = await fetch(`/api/storage/cleanup?dry_run=${dryRun}`, { method: "POST" });
  if (!res.ok) throw new Error("Cleanup request failed");
  return res.json();
}

function StorageCleanup({ onBack }) {
  const [preview, setPreview] = useState(null);

  const previewMutation = useMutation({
    mutationFn: () => runCleanup(true),
    onSuccess: (data) => setPreview(data),
  });

  const deleteMutation = useMutation({
    mutationFn: () => runCleanup(false),
    onSuccess: (data) => setPreview(data),
  });

  const isPending = previewMutation.isPending || deleteMutation.isPending;
  const deleted = preview && !preview.dry_run;

  return (
    <div className="book-settings">
      <div className="settings-header">
        <button className="btn-text" onClick={onBack} style={{ flexShrink: 0 }}>
          ← Back
        </button>
        <h2>Storage Cleanup</h2>
      </div>

      <section className="settings-section">
        <p className="hint">
          Scans the library directory for EPUB and cover files that are not
          referenced by any book in the database.
        </p>

        <div className="settings-actions">
          {!preview && (
            <button
              onClick={() => previewMutation.mutate()}
              disabled={isPending}
            >
              {previewMutation.isPending ? "Scanning..." : "Scan for Orphaned Files"}
            </button>
          )}

          {preview && preview.dry_run && preview.files.length > 0 && (
            <button
              className="btn-danger"
              onClick={() => deleteMutation.mutate()}
              disabled={isPending}
            >
              {deleteMutation.isPending
                ? "Deleting..."
                : `Delete ${preview.files.length} file${preview.files.length !== 1 ? "s" : ""} (${formatBytes(preview.total_bytes)})`}
            </button>
          )}

          {preview && (
            <button
              className="btn-text"
              onClick={() => {
                setPreview(null);
                previewMutation.reset();
                deleteMutation.reset();
              }}
              disabled={isPending}
            >
              Reset
            </button>
          )}
        </div>

        {(previewMutation.isError || deleteMutation.isError) && (
          <p className="error">
            {(previewMutation.error || deleteMutation.error)?.message}
          </p>
        )}
      </section>

      {preview && (
        <section className="settings-section">
          <h3>
            {deleted ? "Deleted Files" : "Orphaned Files Found"}
            <span className="hint" style={{ fontWeight: "normal", marginLeft: "0.5rem" }}>
              {preview.files.length} file{preview.files.length !== 1 ? "s" : ""} — {formatBytes(preview.total_bytes)}
            </span>
          </h3>

          {preview.files.length === 0 ? (
            <p className="hint">No orphaned files found. Library is clean.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "0.25rem" }}>
              {preview.files.map((f) => (
                <li
                  key={f.path}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    fontFamily: "monospace",
                    fontSize: "0.8rem",
                    padding: "0.3rem 0.5rem",
                    borderRadius: "4px",
                    background: "var(--surface, #1a1a2e)",
                  }}
                >
                  <span style={{ wordBreak: "break-all", color: deleted ? "#6b7280" : "#e2e8f0" }}>
                    {f.path}
                  </span>
                  <span className="hint" style={{ flexShrink: 0, marginLeft: "1rem" }}>
                    {formatBytes(f.size_bytes)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {deleted && preview.files.length > 0 && (
            <p style={{ marginTop: "0.75rem", color: "#4ade80", fontSize: "0.875rem" }}>
              Deleted {preview.files.length} file{preview.files.length !== 1 ? "s" : ""}, freed {formatBytes(preview.total_bytes)}.
            </p>
          )}
        </section>
      )}
    </div>
  );
}

export default StorageCleanup;
