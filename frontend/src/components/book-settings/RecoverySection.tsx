import { useQuery } from "@tanstack/react-query";
import { getBookRevisions } from "../../api/books";
import type { components } from "../../api/schema";
import { displayValue, stringValue } from "../../lib/errors";
import { queryKeys } from "../../lib/queryKeys";
import type { Book } from "../../types";

type BookRevision = components["schemas"]["BookRevision"];

function describeRevisionSnapshot(revision: BookRevision) {
  const snapshot = revision.snapshot || {};
  if (
    revision.action === "cleaning_rules_changed" ||
    revision.action === "original_restored"
  ) {
    const removedCount = Array.isArray(snapshot.removed_chapters)
      ? snapshot.removed_chapters.length
      : 0;
    const selectorCount = Array.isArray(snapshot.content_selectors)
      ? snapshot.content_selectors.length
      : 0;
    return `Previous content rules: ${removedCount} removed chapter${removedCount === 1 ? "" : "s"}, ${selectorCount} selector${selectorCount === 1 ? "" : "s"}`;
  }
  if (revision.action === "series_changed") {
    const seriesIndex = displayValue(snapshot.series_index);
    return `Previous series: ${stringValue(snapshot.series) || "None"}${seriesIndex != null ? ` · order ${seriesIndex}` : ""}`;
  }
  return `Previous metadata: “${stringValue(snapshot.title) || "Untitled"}” by ${stringValue(snapshot.author) || "Unknown author"}`;
}

export default function RecoverySection({
  book,
  disabled,
  onRestoreOriginal,
  onRestoreRevision,
}: {
  book: Book;
  disabled: boolean;
  onRestoreOriginal: () => void;
  onRestoreRevision: (revision: BookRevision) => void;
}) {
  const { data: revisions = [] } = useQuery({
    queryKey: queryKeys.bookRevisions(book.id),
    queryFn: ({ signal }) => getBookRevisions(book.id, { signal }),
  });

  return (
    <section className="settings-section">
      <h3>Recovery &amp; change history</h3>
      <p className="hint">
        Restore the current EPUB from its immutable original, or roll metadata
        and series fields back to a saved revision.
      </p>
      <div
        className="settings-actions"
        style={{ marginBottom: revisions.length ? "0.85rem" : 0 }}
      >
        <button
          type="button"
          onClick={onRestoreOriginal}
          disabled={disabled || !book.immutable_path || !book.current_path}
        >
          Restore original EPUB
        </button>
      </div>
      {revisions.length > 0 ? (
        <ul className="revision-list">
          {revisions.map((revision) => (
            <li className="revision-item" key={revision.id}>
              <div>
                <strong>{revision.summary}</strong>
                <p className="hint">
                  {new Date(revision.created_at).toLocaleString()} ·{" "}
                  {revision.action.replace(/_/g, " ")}
                </p>
                <p className="hint">{describeRevisionSnapshot(revision)}</p>
              </div>
              <button
                type="button"
                className="btn-text btn-sm"
                onClick={() => onRestoreRevision(revision)}
                disabled={disabled}
              >
                Restore
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="hint">No reversible changes have been recorded yet.</p>
      )}
    </section>
  );
}
