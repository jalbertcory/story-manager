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

function getCleanupFiles(preview) {
  return preview?.files || [];
}

function getCleanupBooks(preview) {
  return preview?.books || [];
}

function getCleanupTargetCount(preview) {
  return getCleanupFiles(preview).length + getCleanupBooks(preview).length;
}

function formatCleanupSummary(preview) {
  const parts = [];
  const fileCount = getCleanupFiles(preview).length;
  const bookCount = getCleanupBooks(preview).length;

  if (fileCount > 0) {
    parts.push(`${fileCount} file${fileCount !== 1 ? "s" : ""}`);
  }
  if (bookCount > 0) {
    parts.push(`${bookCount} failed import${bookCount !== 1 ? "s" : ""}`);
  }

  return parts.join(", ");
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
          Scans the library directory for orphaned EPUB and cover files, and
          failed web imports that never produced EPUB files.
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

          {preview && preview.dry_run && getCleanupTargetCount(preview) > 0 && (
            <button
              className="btn-danger"
              onClick={() => deleteMutation.mutate()}
              disabled={isPending}
            >
              {deleteMutation.isPending
                ? "Deleting..."
                : `Delete ${getCleanupTargetCount(preview)} item${getCleanupTargetCount(preview) !== 1 ? "s" : ""}${preview.total_bytes > 0 ? ` (${formatBytes(preview.total_bytes)})` : ""}`}
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
            {deleted ? "Deleted Items" : "Cleanup Candidates Found"}
            <span className="hint" style={{ fontWeight: "normal", marginLeft: "0.5rem" }}>
              {getCleanupTargetCount(preview) === 0
                ? "Nothing to remove"
                : `${formatCleanupSummary(preview)}${preview.total_bytes > 0 ? ` — ${formatBytes(preview.total_bytes)}` : ""}`}
            </span>
          </h3>

          {getCleanupTargetCount(preview) === 0 ? (
            <p className="hint">No orphaned files or failed web imports found. Library is clean.</p>
          ) : (
            <>
              {getCleanupFiles(preview).length > 0 && (
                <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                  {getCleanupFiles(preview).map((f) => (
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

              {getCleanupBooks(preview).length > 0 && (
                <ul style={{ listStyle: "none", padding: 0, margin: getCleanupFiles(preview).length > 0 ? "0.75rem 0 0 0" : 0, display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                  {getCleanupBooks(preview).map((book) => (
                    <li
                      key={book.book_id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "baseline",
                        fontSize: "0.85rem",
                        padding: "0.4rem 0.6rem",
                        borderRadius: "4px",
                        background: "var(--surface, #1a1a2e)",
                        gap: "1rem",
                      }}
                    >
                      <span style={{ wordBreak: "break-word" }}>
                        <strong>{book.title}</strong>
                        {book.author && <span className="hint"> by {book.author}</span>}
                      </span>
                      <span style={{ flexShrink: 0, color: "#f87171", fontFamily: "monospace", fontSize: "0.8rem" }}>
                        failed web import
                        {book.source_url && <span className="hint" style={{ marginLeft: "0.5rem" }}>{book.source_url}</span>}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          {deleted && getCleanupTargetCount(preview) > 0 && (
            <p style={{ marginTop: "0.75rem", color: "#4ade80", fontSize: "0.875rem" }}>
              Deleted {getCleanupTargetCount(preview)} item{getCleanupTargetCount(preview) !== 1 ? "s" : ""}{preview.total_bytes > 0 ? `, freed ${formatBytes(preview.total_bytes)}` : ""}.
            </p>
          )}
        </section>
      )}
    </div>
  );
}

export default StorageCleanup;
