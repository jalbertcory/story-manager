import type { Book } from "../../types";

export default function SourceSection({
  book,
  disabled,
  isDetaching,
  onDetach,
}: {
  book: Book;
  disabled: boolean;
  isDetaching: boolean;
  onDetach: () => void;
}) {
  const canDetachWebMarker =
    book.source_type === "web" && book.immutable_path && book.current_path;

  return (
    <section className="settings-section">
      <h3>Source</h3>
      {book.source_url ? (
        <div className="source-info">
          <span className="badge-web">{book.source_type}</span>
          <a
            href={book.source_url}
            target="_blank"
            rel="noreferrer"
            className="source-link"
          >
            {book.source_url}
          </a>
        </div>
      ) : (
        <p className="hint">No source URL is currently attached.</p>
      )}
      {book.source_type === "web" && (
        <div className="settings-actions" style={{ marginTop: "0.5rem" }}>
          <button
            type="button"
            className="btn-danger btn-sm"
            onClick={onDetach}
            disabled={disabled || !canDetachWebMarker}
          >
            {isDetaching ? "Converting…" : "Convert to EPUB-only"}
          </button>
          {!canDetachWebMarker && (
            <span className="hint" style={{ margin: 0, alignSelf: "center" }}>
              Requires EPUB files first
            </span>
          )}
        </div>
      )}
    </section>
  );
}
