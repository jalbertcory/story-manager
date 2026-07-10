import { useState } from "react";

export function SelectorPills({ selectors, onChange }) {
  const [inputValue, setInputValue] = useState("");

  const addSelector = () => {
    const trimmed = inputValue.trim();
    if (trimmed && !selectors.includes(trimmed)) {
      onChange([...selectors, trimmed]);
    }
    setInputValue("");
  };

  const removeSelector = (sel) => {
    onChange(selectors.filter((s) => s !== sel));
  };

  return (
    <div className="selector-pills">
      <div className="pills">
        {selectors.map((sel) => (
          <span key={sel} className="pill">
            {sel}
            <button className="pill-remove" onClick={() => removeSelector(sel)}>
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="pill-input">
        <input
          type="text"
          placeholder="Add CSS selector, e.g. div.note"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && addSelector()}
        />
        <button onClick={addSelector}>Add</button>
      </div>
    </div>
  );
}

export function BookIdentifiersSection({
  identifiersExpanded,
  setIdentifiersExpanded,
  isbn10,
  setIsbn10,
  isbn13,
  setIsbn13,
  googleBooksVolumeId,
  setGoogleBooksVolumeId,
  openLibraryWorkKey,
  setOpenLibraryWorkKey,
  openLibraryEditionKey,
  setOpenLibraryEditionKey,
  openLibraryAuthorKey,
  setOpenLibraryAuthorKey,
  otherRemoteIdsJson,
  setOtherRemoteIdsJson,
  identifierError,
}) {
  return (
    <section className="settings-section">
      <button
        type="button"
        className="collapsible-header"
        onClick={() => setIdentifiersExpanded((e) => !e)}
        aria-expanded={identifiersExpanded}
        aria-controls="book-identifiers"
      >
        <h3>
          Identifiers
          {(isbn10 || isbn13 || googleBooksVolumeId || openLibraryWorkKey) && (
            <span className="field-count">
              {
                [
                  isbn10,
                  isbn13,
                  googleBooksVolumeId,
                  openLibraryWorkKey,
                  openLibraryEditionKey,
                  openLibraryAuthorKey,
                ].filter(Boolean).length
              }{" "}
              set
            </span>
          )}
        </h3>
        <span className="collapse-toggle">
          {identifiersExpanded ? "▲" : "▼"}
        </span>
      </button>
      {identifiersExpanded && (
        <div id="book-identifiers" className="collapsible-body">
          <div className="field-row">
            <label className="field-row-equal">
              ISBN-10
              <input
                value={isbn10}
                onChange={(e) => setIsbn10(e.target.value)}
                placeholder="Manual ISBN-10"
              />
            </label>
            <label className="field-row-equal">
              ISBN-13
              <input
                value={isbn13}
                onChange={(e) => setIsbn13(e.target.value)}
                placeholder="Manual ISBN-13"
              />
            </label>
          </div>
          <label>
            Google Books Volume ID
            <input
              value={googleBooksVolumeId}
              onChange={(e) => setGoogleBooksVolumeId(e.target.value)}
              placeholder="zyTCAlFPjgYC"
            />
          </label>
          <label>
            Open Library Work Key
            <input
              value={openLibraryWorkKey}
              onChange={(e) => setOpenLibraryWorkKey(e.target.value)}
              placeholder="/works/OL123W"
            />
          </label>
          <div className="field-row">
            <label className="field-row-equal">
              OL Edition Key
              <input
                value={openLibraryEditionKey}
                onChange={(e) => setOpenLibraryEditionKey(e.target.value)}
                placeholder="OL123M"
              />
            </label>
            <label className="field-row-equal">
              OL Author Key
              <input
                value={openLibraryAuthorKey}
                onChange={(e) => setOpenLibraryAuthorKey(e.target.value)}
                placeholder="OL123A"
              />
            </label>
          </div>
          <label>
            Other Identifiers (JSON)
            <textarea
              value={otherRemoteIdsJson}
              onChange={(e) => setOtherRemoteIdsJson(e.target.value)}
              placeholder={'{\n  "goodreads_id": "12345"\n}'}
              rows={3}
            />
          </label>
          {identifierError && <p className="error">{identifierError}</p>}
        </div>
      )}
    </section>
  );
}

export function SourceTagList({ tags }) {
  if (!tags?.length) return null;

  return (
    <div className="source-tag-list" aria-label="Source tags">
      {tags.map((tag) => (
        <span key={tag} className="source-tag">
          {tag}
        </span>
      ))}
    </div>
  );
}

export function SyncedGenreTagList({ tags }) {
  if (!tags?.length) {
    return (
      <span className="settings-empty-value">No synced genre tags yet</span>
    );
  }

  return (
    <div className="genre-tag-list" aria-label="Synced genre tags">
      {tags.map((tag) => (
        <span key={tag} className="genre-tag">
          {tag}
        </span>
      ))}
    </div>
  );
}

const EMPTY_UPDATE_HISTORY = {
  history: [],
  summary: {
    total_update_events: 0,
    total_chapters_added: 0,
    total_words_added: 0,
    average_words_per_week: null,
    average_words_per_month: null,
    average_days_between_updates: null,
    predicted_next_update_at: null,
    last_update_at: null,
  },
};

function normalizeUpdateHistory(data) {
  if (!data || !Array.isArray(data.history) || !data.summary) {
    return EMPTY_UPDATE_HISTORY;
  }
  return data;
}

function formatNumber(value, options = {}) {
  if (value == null || Number.isNaN(Number(value))) return "Not enough data";
  return new Intl.NumberFormat(undefined, options).format(value);
}

function formatCompactNumber(value) {
  if (value == null || Number.isNaN(Number(value))) return "0";
  return new Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatDate(value) {
  if (!value) return "Not enough data";
  return new Date(value).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatHistoryEntryLabel(entry) {
  if (entry.is_initial_sync) return "Initial sync";
  if (entry.is_catch_up_sync) return "Catch-up sync";
  return `+${entry.chapters_added} ch`;
}

export function ChapterUpdateHistory({
  updateHistory,
  isLoading,
  isError,
  error,
}) {
  const { history, summary } = normalizeUpdateHistory(updateHistory);
  const chartEntries = history.filter((entry) => entry.included_in_stats);
  const maxWords = Math.max(
    ...chartEntries.map((entry) => entry.words_added),
    1,
  );

  return (
    <section className="settings-section chapter-history-section">
      <h3>Update History</h3>
      {isLoading && <p className="hint">Loading update history...</p>}
      {isError && (
        <p className="error">
          Update history failed: {error?.message || "Unable to load history"}
        </p>
      )}
      {!isLoading && !isError && history.length === 0 && (
        <p className="hint">
          No tracked chapter updates yet. New chapter batches will appear here
          after a refresh finds them.
        </p>
      )}
      {!isLoading && !isError && history.length > 0 && (
        <>
          <div className="chapter-history-stats">
            <div className="chapter-history-stat">
              <span className="hint">Words / Week</span>
              <strong>
                {formatNumber(summary.average_words_per_week, {
                  maximumFractionDigits: 0,
                })}
              </strong>
            </div>
            <div className="chapter-history-stat">
              <span className="hint">Words / Month</span>
              <strong>
                {formatNumber(summary.average_words_per_month, {
                  maximumFractionDigits: 0,
                })}
              </strong>
            </div>
            <div className="chapter-history-stat">
              <span className="hint">Next Update</span>
              <strong>{formatDate(summary.predicted_next_update_at)}</strong>
            </div>
          </div>

          <div
            className="chapter-history-chart"
            aria-label="Words added by update date"
          >
            {chartEntries.length === 0 ? (
              <p className="hint chapter-history-chart-empty">
                No post-import chapter updates yet.
              </p>
            ) : (
              chartEntries.slice(-12).map((entry) => {
                const height = Math.max(
                  (entry.words_added / maxWords) * 100,
                  8,
                );
                return (
                  <div className="chapter-history-bar-wrap" key={entry.id}>
                    <div className="chapter-history-bar-stage">
                      <div
                        className="chapter-history-bar"
                        style={{ height: `${height}%` }}
                        title={`${formatDate(entry.timestamp)}: ${formatNumber(
                          entry.words_added,
                        )} words`}
                      />
                    </div>
                    <span>{formatCompactNumber(entry.words_added)}</span>
                  </div>
                );
              })
            )}
          </div>

          <ul className="chapter-history-list">
            {history
              .slice()
              .reverse()
              .map((entry) => (
                <li key={entry.id}>
                  <span>{formatDate(entry.timestamp)}</span>
                  <strong>
                    {formatHistoryEntryLabel(entry)} ·{" "}
                    {formatNumber(entry.words_added)} words
                  </strong>
                </li>
              ))}
          </ul>
        </>
      )}
    </section>
  );
}
