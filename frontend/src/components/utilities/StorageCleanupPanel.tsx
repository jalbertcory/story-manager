import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { cleanupStorage as runCleanup } from "../../api/admin";
import { formatBytes } from "../../lib/format";

type CleanupPreview = Awaited<ReturnType<typeof runCleanup>>;

function getCleanupFiles(preview: CleanupPreview | null) {
  return preview?.files || [];
}

function getCleanupBooks(preview: CleanupPreview | null) {
  return preview?.books || [];
}

function getCleanupTargetCount(preview: CleanupPreview | null) {
  return getCleanupFiles(preview).length + getCleanupBooks(preview).length;
}

function formatCleanupSummary(preview: CleanupPreview | null) {
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

export default function StorageCleanupPanel() {
  const [preview, setPreview] = useState<CleanupPreview | null>(null);

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
    <section className="settings-section">
      <p className="hint">
        Scans the library directory for orphaned EPUB and cover files, and
        failed web imports that never produced EPUB files. Files owned by books
        in the recycle bin are protected.
      </p>

      <div className="settings-actions">
        {!preview && (
          <button onClick={() => previewMutation.mutate()} disabled={isPending}>
            {previewMutation.isPending
              ? "Scanning..."
              : "Scan for Orphaned Files"}
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
        <p className="error" role="alert">
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
            <span
              className="hint"
              style={{ fontWeight: "normal", marginLeft: "0.5rem" }}
            >
              {getCleanupTargetCount(preview) === 0
                ? "Nothing to remove"
                : `${formatCleanupSummary(preview)}${preview.total_bytes > 0 ? ` — ${formatBytes(preview.total_bytes)}` : ""}`}
            </span>
          </h4>

          {getCleanupTargetCount(preview) === 0 ? (
            <p className="hint">
              No orphaned files or failed web imports found. Library is clean.
            </p>
          ) : (
            <>
              {getCleanupFiles(preview).length > 0 && (
                <ul
                  style={{
                    listStyle: "none",
                    padding: 0,
                    margin: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.25rem",
                  }}
                >
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
                      <span
                        style={{
                          wordBreak: "break-all",
                          color: deleted ? "#6b7280" : "#e2e8f0",
                        }}
                      >
                        {f.path}
                      </span>
                      <span
                        className="hint"
                        style={{ flexShrink: 0, marginLeft: "1rem" }}
                      >
                        {formatBytes(f.size_bytes)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {getCleanupBooks(preview).length > 0 && (
                <ul
                  style={{
                    listStyle: "none",
                    padding: 0,
                    margin:
                      getCleanupFiles(preview).length > 0 ? "0.75rem 0 0 0" : 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.35rem",
                  }}
                >
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
                        {book.author && (
                          <span className="hint"> by {book.author}</span>
                        )}
                      </span>
                      <span
                        style={{
                          flexShrink: 0,
                          color: "#f87171",
                          fontFamily: "monospace",
                          fontSize: "0.8rem",
                        }}
                      >
                        failed web import
                        {book.source_url && (
                          <span
                            className="hint"
                            style={{ marginLeft: "0.5rem" }}
                          >
                            {book.source_url}
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          {deleted && getCleanupTargetCount(preview) > 0 && (
            <p
              style={{
                marginTop: "0.75rem",
                color: "#4ade80",
                fontSize: "0.875rem",
              }}
            >
              Deleted {getCleanupTargetCount(preview)} item
              {getCleanupTargetCount(preview) !== 1 ? "s" : ""}
              {preview.total_bytes > 0
                ? `, freed ${formatBytes(preview.total_bytes)}`
                : ""}
              .
            </p>
          )}
        </div>
      )}
    </section>
  );
}
