import type { Book } from "../../types";

export default function BookActionsSection({
  book,
  disabled,
  saving,
  processing,
  refreshing,
  jobNotice,
  onSave,
  onProcess,
  onRefresh,
  onDelete,
}: {
  book: Book;
  disabled: boolean;
  saving: boolean;
  processing: boolean;
  refreshing: boolean;
  jobNotice: string;
  onSave: () => void;
  onProcess: () => void;
  onRefresh: () => void;
  onDelete: () => void;
}) {
  return (
    <section className="settings-section actions-bar" aria-label="Book actions">
      <div className="actions-heading">
        <h3>Book actions</h3>
        <span className="hint">
          Save edits before rebuilding or refreshing.
        </span>
      </div>
      <div className="actions-primary">
        <button className="btn-primary" onClick={onSave} disabled={disabled}>
          {saving ? "Saving..." : "Save Metadata"}
        </button>
        {book.current_path && (
          <button
            onClick={onProcess}
            disabled={disabled}
            title="Save changes and rebuild the EPUB file with current cleaning rules"
          >
            {processing ? "Queueing..." : "Queue EPUB rebuild from saved edits"}
          </button>
        )}
        {book.source_type === "web" && (
          <button onClick={onRefresh} disabled={disabled}>
            {refreshing
              ? "Queueing…"
              : book.refresh_status === "queued"
                ? "Queued for refresh…"
                : book.refresh_status === "processing"
                  ? "Refreshing from source…"
                  : "Refresh latest chapters"}
          </button>
        )}
      </div>
      {jobNotice && (
        <p className="job-queued-notice" role="status">
          {jobNotice} <a href="/activity/processing">View processing</a>
        </p>
      )}
      <p className="hint actions-hint">
        <strong>Save Metadata</strong> updates the database only.{" "}
        <strong>Rebuild EPUB</strong> saves edits and regenerates the file with
        your cleaning rules. Refreshing checks the original web source for new
        chapters.
      </p>
      <div className="actions-secondary">
        {book.current_path && (
          <a
            href={`/api/books/${book.id}/download`}
            download
            className="btn btn-secondary btn-sm"
          >
            Download EPUB
          </a>
        )}
        <button
          className="btn-danger btn-sm"
          onClick={onDelete}
          disabled={disabled}
        >
          Delete Book
        </button>
      </div>
    </section>
  );
}
