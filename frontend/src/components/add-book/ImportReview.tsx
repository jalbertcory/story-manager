import type { previewBookImports } from "../../api/imports";
import type { ImportResult } from "./importTypes";

export type ImportPreview = Awaited<ReturnType<typeof previewBookImports>>;

function previewStatusLabel(status: string) {
  switch (status) {
    case "ready":
      return "Ready";
    case "duplicate":
      return "Duplicate — will skip";
    case "unsupported":
      return "Unsupported";
    default:
      return "Needs correction";
  }
}

function resultLabel(status: string) {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function ImportReview({
  preview,
  duplicatesReviewed,
  onDuplicatesReviewed,
  importing,
  onImport,
  onChangeSelection,
}: {
  preview: ImportPreview;
  duplicatesReviewed: boolean;
  onDuplicatesReviewed: (reviewed: boolean) => void;
  importing: boolean;
  onImport: () => void;
  onChangeSelection: () => void;
}) {
  const canImport =
    (preview.ready_count > 0 || preview.duplicate_count > 0) &&
    (preview.duplicate_count === 0 || duplicatesReviewed);
  return (
    <section className="import-panel" aria-labelledby="import-preview-heading">
      <span className="import-step-code">02 / REVIEW</span>
      <h3 id="import-preview-heading">Review before importing</h3>
      <p className="import-preview-summary" role="status">
        <strong>{preview.ready_count} ready</strong>
        {` · ${preview.duplicate_count} duplicate · ${preview.unsupported_count} unsupported · ${preview.error_count} with errors`}
      </p>
      <div className="import-preview-list">
        {preview.items.map((item) => (
          <article
            key={item.key}
            className={`import-preview-item import-preview-item--${item.status}`}
          >
            <div>
              <strong>{item.title || item.source_url || item.name}</strong>
              {item.author && <span>{item.author}</span>}
              {item.series && <small>Series: {item.series}</small>}
              {item.cleaning_configs?.length > 0 && (
                <small>Cleaning: {item.cleaning_configs.join(", ")}</small>
              )}
              {item.detail && <small>{item.detail}</small>}
            </div>
            <span className="import-preview-status">
              {previewStatusLabel(item.status)}
            </span>
          </article>
        ))}
      </div>
      {preview.duplicate_count > 0 && (
        <label className="import-checkbox import-duplicate-confirmation">
          <input
            type="checkbox"
            checked={duplicatesReviewed}
            onChange={(event) => onDuplicatesReviewed(event.target.checked)}
          />
          I reviewed the duplicates and want to skip them.
        </label>
      )}
      <div className="import-actions">
        <button
          type="button"
          className="btn-primary"
          disabled={!canImport || importing}
          onClick={onImport}
        >
          {importing
            ? "Starting import…"
            : preview.ready_count > 0
              ? `Import ${preview.ready_count} ready`
              : preview.duplicate_count > 0
                ? `Finish with ${preview.duplicate_count} skipped`
                : "Nothing ready to import"}
        </button>
        <button type="button" className="btn-text" onClick={onChangeSelection}>
          Change selection
        </button>
      </div>
    </section>
  );
}

export function ImportResults({
  results,
  directImport,
  onImportMore,
}: {
  results: ImportResult[];
  directImport: boolean;
  onImportMore: () => void;
}) {
  return (
    <section className="import-panel" aria-labelledby="import-results-heading">
      <span className="import-step-code">
        {directImport ? "02" : "03"} / RESULTS
      </span>
      <h3 id="import-results-heading">Import results</h3>
      <div className="import-result-list" role="status">
        {results.map((item, index) => (
          <div
            className={`import-result import-result--${item.status}`}
            key={`${item.name}-${index}`}
          >
            <strong>{item.name}</strong>
            <span>{resultLabel(item.status)}</span>
            {item.detail && <small>{item.detail}</small>}
          </div>
        ))}
      </div>
      <div className="import-actions">
        <button type="button" className="btn-primary" onClick={onImportMore}>
          Import more
        </button>
        <a className="btn" href="/activity/processing">
          View progress
        </a>
      </div>
    </section>
  );
}
