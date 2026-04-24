import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveMetadataMatch,
  dismissMetadataProposal,
  getLatestMetadataJob,
  getMetadataInbox,
  queueMetadataSync,
  rejectMetadataMatch,
} from "../api/metadata";
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

async function runLibraryValidation() {
  const res = await fetch("/api/library/validate");
  if (!res.ok) throw new Error("Validation request failed");
  return res.json();
}

function formatAuditIssue(issue) {
  switch (issue.issue) {
    case "pending_web_import":
      return "pending web import";
    case "failed_web_import":
      return "failed web import";
    default:
      return issue.issue.replace(/_/g, " ");
  }
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

  const validateMutation = useMutation({
    mutationFn: runLibraryValidation,
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

  const validationResult = validateMutation.data;

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
        <h3>Library Audit</h3>
        <p className="hint">
          Checks every book record for missing or broken file paths (EPUB files, covers).
        </p>
        <div className="settings-actions">
          <button
            onClick={() => validateMutation.mutate()}
            disabled={validateMutation.isPending}
          >
            {validateMutation.isPending ? "Auditing..." : "Run Library Audit"}
          </button>
          {validationResult && (
            <button
              className="btn-text"
              onClick={() => validateMutation.reset()}
            >
              Reset
            </button>
          )}
        </div>
        {validateMutation.isError && (
          <p className="error" style={{ marginTop: "0.5rem" }}>
            {validateMutation.error?.message}
          </p>
        )}
        {validationResult && (
          <div style={{ marginTop: "1rem" }}>
            <h4>
              {validationResult.issues_count === 0 ? "No Issues Found" : "Issues Found"}
              <span className="hint" style={{ fontWeight: "normal", marginLeft: "0.5rem" }}>
                {validationResult.total_books} book{validationResult.total_books !== 1 ? "s" : ""} checked,{" "}
                {validationResult.issues_count} issue{validationResult.issues_count !== 1 ? "s" : ""}
              </span>
            </h4>
            {validationResult.issues_count === 0 ? (
              <p className="hint">All books have valid file paths. Library is healthy.</p>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                {validationResult.issues.map((issue, i) => (
                  <li
                    key={i}
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
                      <strong>{issue.title}</strong>
                      {issue.author && <span className="hint"> by {issue.author}</span>}
                    </span>
                    <span style={{ flexShrink: 0, color: "#f87171", fontFamily: "monospace", fontSize: "0.8rem" }}>
                      {formatAuditIssue(issue)}
                      {issue.path && <span className="hint" style={{ marginLeft: "0.5rem" }}>{issue.path}</span>}
                      {!issue.path && issue.source_url && (
                        <span className="hint" style={{ marginLeft: "0.5rem" }}>{issue.source_url}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
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

        {preview?.skipped_reason && (
          <p className="hint" style={{ marginTop: "0.5rem", color: "#fbbf24" }}>
            {preview.skipped_reason}
          </p>
        )}

        {preview && !preview.skipped_reason && (
          <div style={{ marginTop: "1rem" }}>
            <h4>
              {deleted ? "Deleted Items" : "Cleanup Candidates Found"}
              <span className="hint" style={{ fontWeight: "normal", marginLeft: "0.5rem" }}>
                {getCleanupTargetCount(preview) === 0
                  ? "Nothing to remove"
                  : `${formatCleanupSummary(preview)}${preview.total_bytes > 0 ? ` — ${formatBytes(preview.total_bytes)}` : ""}`}
              </span>
            </h4>

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
          </div>
        )}
      </section>

      <ReaderKeys />
    </div>
  );
}

export default Utilities;
