import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveMetadataMatch,
  dismissMetadataProposal,
  getLatestMetadataJob,
  getMetadataInbox,
  queueMetadataSync,
  rejectMetadataMatch,
} from "../api/books";
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

function renderMetadataJobSummary(job) {
  if (!job) return "No metadata sync jobs have run yet.";
  const base = `${job.processed_books}/${job.total_books} processed, ${job.matched_books} matched, ${job.proposed_books} proposed, ${job.applied_books} applied.`;
  if (job.status === "failed" && job.error) {
    return `${base} Failed: ${job.error}`;
  }
  return base;
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
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
    },
  });

  const isPending = previewMutation.isPending || deleteMutation.isPending;
  const deleted = preview && !preview.dry_run;

  const reprocessMutation = useMutation({
    mutationFn: () =>
      fetch("/api/books/reprocess-all", { method: "POST" }).then((r) => r.json()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["book-catalog"] }),
  });

  const { data: latestMetadataJob } = useQuery({
    queryKey: ["metadata-job-latest"],
    queryFn: getLatestMetadataJob,
    staleTime: 5000,
    refetchOnWindowFocus: false,
    refetchInterval: ({ state }) => (state.data?.status === "running" || state.data?.status === "queued" ? 5000 : false),
  });

  const { data: metadataInbox = [] } = useQuery({
    queryKey: ["metadata-inbox"],
    queryFn: getMetadataInbox,
    staleTime: 15000,
    refetchOnWindowFocus: false,
    refetchInterval: latestMetadataJob?.status === "running" || latestMetadataJob?.status === "queued" ? 15000 : false,
  });

  const queueMetadataMutation = useMutation({
    mutationFn: () => queueMetadataSync(null, "manual"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["metadata-job-latest"] });
    },
  });

  const approveMatchMutation = useMutation({
    mutationFn: (matchId) => approveMetadataMatch(matchId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["metadata-inbox"] });
      queryClient.invalidateQueries({ queryKey: ["metadata-job-latest"] });
    },
  });

  const rejectMatchMutation = useMutation({
    mutationFn: (matchId) => rejectMetadataMatch(matchId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["metadata-inbox"] });
    },
  });

  const dismissProposalMutation = useMutation({
    mutationFn: (proposalId) => dismissMetadataProposal(proposalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["metadata-inbox"] });
    },
  });

  const handleDetectSeries = async () => {
    setDetectState("pending");
    try {
      const res = await fetch("/api/books/detect-series", { method: "POST" });
      const data = await res.json();
      if (data.updated > 0) {
        queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
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
    <div className={onBack ? "book-settings" : undefined}>
      {onBack && (
        <div className="settings-header">
          <button className="btn-text" onClick={onBack} style={{ flexShrink: 0 }}>
            ← Back
          </button>
          <h2>Utilities</h2>
        </div>
      )}

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
        <h3>Sync Online Metadata</h3>
        <p className="hint">
          Runs in the background for new books and stale books, then puts uncertain matches into an inbox for approval.
        </p>
        <div className="settings-actions">
          <button
            onClick={() => queueMetadataMutation.mutate()}
            disabled={queueMetadataMutation.isPending}
          >
            {queueMetadataMutation.isPending ? "Queueing…" : "Queue Library Metadata Sync"}
          </button>
        </div>
        {(queueMetadataMutation.isError || approveMatchMutation.isError || rejectMatchMutation.isError || dismissProposalMutation.isError) && (
          <p className="error" style={{ marginTop: "0.5rem" }}>
            {(queueMetadataMutation.error || approveMatchMutation.error || rejectMatchMutation.error || dismissProposalMutation.error)?.message}
          </p>
        )}
        <div style={{ marginTop: "1rem" }}>
          <p className="hint">
            Latest job: {latestMetadataJob ? `${latestMetadataJob.status} (${latestMetadataJob.trigger})` : "none"}
          </p>
          <p className="hint">{renderMetadataJobSummary(latestMetadataJob)}</p>
        </div>
        <div style={{ marginTop: "1rem" }}>
          <h4>
            Metadata Inbox
            <span className="hint" style={{ fontWeight: "normal", marginLeft: "0.5rem" }}>
              {metadataInbox.length} item{metadataInbox.length !== 1 ? "s" : ""}
            </span>
          </h4>
        </div>
        {metadataInbox.length > 0 ? (
          <div style={{ marginTop: "1rem" }}>
            <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: "0.75rem" }}>
              {metadataInbox.slice(0, 20).map((entry) => (
                <li
                  key={entry.id}
                  style={{
                    border: "1px solid rgba(148, 163, 184, 0.2)",
                    borderRadius: "8px",
                    padding: "0.75rem",
                    background: "rgba(15, 23, 42, 0.35)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", alignItems: "baseline" }}>
                    <strong>{entry.book_title}</strong>
                    <span className="hint">
                      {entry.match?.status || entry.status}
                    </span>
                  </div>
                  <p className="hint" style={{ marginTop: "0.35rem" }}>{entry.book_author}</p>
                  {entry.match && (
                    <p className="hint" style={{ marginTop: "0.5rem" }}>
                      Suggested match: {entry.match.remote_title || "Unknown title"}
                      {entry.match.remote_author ? ` by ${entry.match.remote_author}` : ""}
                      {entry.match.match_confidence != null ? ` (${Math.round(entry.match.match_confidence * 100)}%)` : ""}
                    </p>
                  )}
                  {entry.proposed_genre_tags.length > 0 && (
                    <p className="hint" style={{ marginTop: "0.5rem" }}>
                      Proposed genres: {entry.proposed_genre_tags.join(", ")}
                    </p>
                  )}
                  {entry.possible_missing_series_books.length > 0 && (
                    <p className="hint" style={{ marginTop: "0.5rem" }}>
                      Possible missing in series: {entry.possible_missing_series_books.join(", ")}
                    </p>
                  )}
                  {entry.note && (
                    <p className="hint" style={{ marginTop: "0.5rem" }}>
                      {entry.note}
                    </p>
                  )}
                  <div className="settings-actions" style={{ marginTop: "0.75rem" }}>
                    {entry.match?.status === "pending" && entry.match?.id ? (
                      <>
                        <button
                          onClick={() => approveMatchMutation.mutate(entry.match.id)}
                          disabled={approveMatchMutation.isPending || rejectMatchMutation.isPending}
                        >
                          {approveMatchMutation.isPending ? "Approving…" : "Approve Match"}
                        </button>
                        <button
                          className="btn-danger"
                          onClick={() => rejectMatchMutation.mutate(entry.match.id)}
                          disabled={approveMatchMutation.isPending || rejectMatchMutation.isPending}
                        >
                          {rejectMatchMutation.isPending ? "Rejecting…" : "Reject Match"}
                        </button>
                      </>
                    ) : (
                      <button
                        className="btn-text"
                        onClick={() => dismissProposalMutation.mutate(entry.id)}
                        disabled={dismissProposalMutation.isPending}
                      >
                        {dismissProposalMutation.isPending ? "Dismissing…" : "Dismiss"}
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="hint" style={{ marginTop: "0.75rem" }}>
            No metadata approvals are waiting right now.
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
