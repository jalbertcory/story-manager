import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import ReaderKeys from "./ReaderKeys.jsx";

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

async function runRemoveAllBooks(dryRun) {
  const res = await fetch(`/api/books/remove-all?dry_run=${dryRun}`, { method: "POST" });
  if (!res.ok) throw new Error("Remove-all request failed");
  return res.json();
}

function buildRemoveAllWarning(preview) {
  const lines = [
    `This will permanently remove ${preview.book_count} book${preview.book_count !== 1 ? "s" : ""} from the library.`,
    `${preview.file_count} file${preview.file_count !== 1 ? "s" : ""} will be deleted (${formatBytes(preview.total_bytes)}).`,
    `${preview.log_count} log entr${preview.log_count === 1 ? "y" : "ies"} will also be removed.`,
  ];

  if (preview.books.length > 0) {
    lines.push("");
    lines.push("Books to remove:");
    preview.books.slice(0, 5).forEach((book) => {
      lines.push(`- ${book.title} by ${book.author}`);
    });
    if (preview.books.length > 5) {
      lines.push(`- ...and ${preview.books.length - 5} more`);
    }
  }

  if (preview.paths.length > 0) {
    lines.push("");
    lines.push("Files to delete:");
    preview.paths.slice(0, 5).forEach((path) => lines.push(`- ${path}`));
    if (preview.paths.length > 5) {
      lines.push(`- ...and ${preview.paths.length - 5} more`);
    }
  }

  lines.push("");
  lines.push("This cannot be undone.");
  return lines.join("\n");
}

function Utilities({ onBack }) {
  const queryClient = useQueryClient();
  const [preview, setPreview] = useState(null);
  const [detectState, setDetectState] = useState(null); // null | "pending" | { updated, series_detected, error? }
  const [removeAllError, setRemoveAllError] = useState("");

  const previewMutation = useMutation({
    mutationFn: () => runCleanup(true),
    onSuccess: (data) => setPreview(data),
  });

  const deleteMutation = useMutation({
    mutationFn: () => runCleanup(false),
    onSuccess: (data) => setPreview(data),
  });

  const removeAllMutation = useMutation({
    mutationFn: () => runRemoveAllBooks(false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
    },
  });

  const isPending = previewMutation.isPending || deleteMutation.isPending;
  const deleted = preview && !preview.dry_run;

  const reprocessMutation = useMutation({
    mutationFn: () =>
      fetch("/api/books/reprocess-all", { method: "POST" }).then((r) => r.json()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["books"] }),
  });

  const handleDetectSeries = async () => {
    setDetectState("pending");
    try {
      const res = await fetch("/api/books/detect-series", { method: "POST" });
      const data = await res.json();
      if (data.updated > 0) {
        queryClient.invalidateQueries({ queryKey: ["books"] });
      }
      setDetectState(data);
    } catch {
      setDetectState({ updated: 0, series_detected: [], error: true });
    }
  };

  const handleRemoveAllBooks = async () => {
    setRemoveAllError("");
    try {
      const preview = await runRemoveAllBooks(true);
      if (preview.book_count === 0) {
        window.alert("No books are currently stored in the library.");
        return;
      }

      if (!window.confirm(buildRemoveAllWarning(preview))) {
        return;
      }

      removeAllMutation.mutate();
    } catch (error) {
      setRemoveAllError(error.message || "Remove-all request failed");
    }
  };

  return (
    <div className="book-settings">
      <div className="settings-header">
        <button className="btn-text" onClick={onBack} style={{ flexShrink: 0 }}>
          ← Back
        </button>
        <h2>Utilities</h2>
      </div>

      <section className="settings-section">
        <h3>Clean All Books</h3>
        <p className="hint">
          Re-applies cleaning configs and selectors to every book in the library.
        </p>
        <div className="settings-actions">
          <button
            onClick={() => reprocessMutation.mutate()}
            disabled={reprocessMutation.isPending}
          >
            {reprocessMutation.isPending ? "Cleaning..." : "Clean All Books"}
          </button>
        </div>
        {reprocessMutation.isError && (
          <p className="error" style={{ marginTop: "0.5rem" }}>
            {reprocessMutation.error?.message}
          </p>
        )}
        {reprocessMutation.isSuccess && (
          <p className="hint" style={{ marginTop: "0.5rem" }}>Done.</p>
        )}
      </section>

      <section className="settings-section">
        <h3>Remove All Books</h3>
        <p className="hint">
          Permanently deletes every book record, its EPUB files, extracted covers, and update history.
        </p>
        <div className="settings-actions">
          <button
            className="btn-danger"
            onClick={handleRemoveAllBooks}
            disabled={removeAllMutation.isPending}
          >
            {removeAllMutation.isPending ? "Removing..." : "Remove All Books"}
          </button>
        </div>
        {(removeAllError || removeAllMutation.isError) && (
          <p className="error" style={{ marginTop: "0.5rem" }}>
            {removeAllError || removeAllMutation.error?.message}
          </p>
        )}
        {removeAllMutation.isSuccess && (
          <p className="hint" style={{ marginTop: "0.5rem" }}>
            Library cleared.
          </p>
        )}
      </section>

      <section className="settings-section">
        <h3>Detect Series</h3>
        <p className="hint">
          Scans all books without a series and attempts to detect one from the title.
        </p>
        <div className="settings-actions">
          <button
            onClick={handleDetectSeries}
            disabled={detectState === "pending"}
          >
            {detectState === "pending" ? "Detecting…" : "Detect Series in Library"}
          </button>
        </div>
        {detectState && detectState !== "pending" && (
          <p className={detectState.error ? "error" : "hint"} style={{ marginTop: "0.5rem" }}>
            {detectState.error
              ? "Error running detection."
              : detectState.updated === 0
              ? "No new series found."
              : `Updated ${detectState.updated} book${detectState.updated > 1 ? "s" : ""}: ${detectState.series_detected.join(", ")}`}
          </p>
        )}
      </section>

      <section className="settings-section">
        <h3>Storage Cleanup</h3>
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

        {preview && (
          <div style={{ marginTop: "1rem" }}>
            <h4>
              {deleted ? "Deleted Files" : "Orphaned Files Found"}
              <span className="hint" style={{ fontWeight: "normal", marginLeft: "0.5rem" }}>
                {preview.files.length} file{preview.files.length !== 1 ? "s" : ""} — {formatBytes(preview.total_bytes)}
              </span>
            </h4>

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
          </div>
        )}
      </section>

      <ReaderKeys />
    </div>
  );
}

export default Utilities;
