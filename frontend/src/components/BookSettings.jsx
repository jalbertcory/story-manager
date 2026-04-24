import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import {
  deleteBook,
  detachBookSource,
  getApiCoverUrl,
  getBook,
  getBookChapters,
  getBookCleanedChapters,
  getBookUpdateHistory,
  getMatchedConfigs,
  previewCleaning,
  processBook,
  queueMetadataSync,
  refreshBook,
  retryBookCover,
  setBookCoverUrl,
  updateBook,
  uploadBookCover,
} from "../api/books";
import { getSeries } from "../api/series";
import BookSettingsChapters from "./BookSettingsChapters";

const fetchChapters = async ({ queryKey }) => {
  const [_key, bookId] = queryKey;
  return getBookChapters(bookId);
};

const fetchCleanedChapters = async ({ queryKey }) => {
  const [_key, bookId] = queryKey;
  return getBookCleanedChapters(bookId);
};

const fetchMatchedConfig = async ({ queryKey }) => {
  const [_key, bookId] = queryKey;
  return getMatchedConfigs(bookId);
};

const fetchUpdateHistory = async ({ queryKey }) => {
  const [_key, bookId] = queryKey;
  return getBookUpdateHistory(bookId);
};

const COMMON_REMOTE_ID_KEYS = [
  "isbn_10",
  "isbn_13",
  "google_books_volume_id",
  "open_library_work_key",
  "open_library_edition_key",
  "open_library_author_key",
];

function splitRemoteIds(remoteIds) {
  const source = remoteIds && typeof remoteIds === "object" ? remoteIds : {};
  const common = {};
  COMMON_REMOTE_ID_KEYS.forEach((key) => {
    common[key] = source[key] || "";
  });

  const extras = Object.fromEntries(
    Object.entries(source).filter(
      ([key]) => !COMMON_REMOTE_ID_KEYS.includes(key),
    ),
  );

  return {
    common,
    extrasJson: Object.keys(extras).length
      ? JSON.stringify(extras, null, 2)
      : "",
  };
}

function SelectorPills({ selectors, onChange }) {
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

function SourceTagList({ tags }) {
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

function SyncedGenreTagList({ tags }) {
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

function ChapterUpdateHistory({ updateHistory, isLoading, isError, error }) {
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

function BookSettings({ book: initialBook, onBack }) {
  const queryClient = useQueryClient();
  const coverInputRef = useRef(null);

  // Poll the individual book while a refresh is in-flight so the UI reflects
  // backend state without the user navigating away. The query is seeded with
  // the book the parent passed so the page renders immediately; staleTime is
  // Infinity so we only hit the network when the refetchInterval fires or when
  // a mutation explicitly invalidates this key.
  const { data: polledBook } = useQuery({
    queryKey: ["book", initialBook.id],
    queryFn: () => getBook(initialBook.id),
    initialData: initialBook,
    staleTime: Infinity,
    refetchInterval: ({ state }) => {
      const current = state.data;
      if (!current || typeof current !== "object" || !current.id) return false;
      return current.refresh_status === "queued" ||
        current.refresh_status === "processing"
        ? 2000
        : false;
    },
  });

  // Guard against malformed responses (e.g., a test mock's catch-all): if the
  // polled value doesn't look like a book, fall back to the prop.
  const book =
    polledBook && typeof polledBook === "object" && polledBook.id
      ? polledBook
      : initialBook;
  const isRefreshing =
    book.refresh_status === "queued" || book.refresh_status === "processing";
  const refreshErrored = book.refresh_status === "error";

  // Cache-buster for the cover <img> — incremented whenever a cover mutation
  // succeeds so the browser fetches the freshly-saved file instead of a stale
  // copy at the same deterministic URL.
  const [coverVersion, setCoverVersion] = useState(0);

  const [title, setTitle] = useState(initialBook.title || "");
  const [author, setAuthor] = useState(initialBook.author || "");
  const [series, setSeries] = useState(initialBook.series || "");
  const [seriesIndex, setSeriesIndex] = useState(
    initialBook.series_index != null ? String(initialBook.series_index) : "",
  );
  const [notes, setNotes] = useState(initialBook.notes || "");
  const [isbn10, setIsbn10] = useState(
    initialBook.metadata_remote_ids?.isbn_10 || "",
  );
  const [isbn13, setIsbn13] = useState(
    initialBook.metadata_remote_ids?.isbn_13 || "",
  );
  const [googleBooksVolumeId, setGoogleBooksVolumeId] = useState(
    initialBook.metadata_remote_ids?.google_books_volume_id || "",
  );
  const [openLibraryWorkKey, setOpenLibraryWorkKey] = useState(
    initialBook.metadata_remote_ids?.open_library_work_key || "",
  );
  const [openLibraryEditionKey, setOpenLibraryEditionKey] = useState(
    initialBook.metadata_remote_ids?.open_library_edition_key || "",
  );
  const [openLibraryAuthorKey, setOpenLibraryAuthorKey] = useState(
    initialBook.metadata_remote_ids?.open_library_author_key || "",
  );
  const [otherRemoteIdsJson, setOtherRemoteIdsJson] = useState(
    splitRemoteIds(initialBook.metadata_remote_ids).extrasJson,
  );
  const [identifierError, setIdentifierError] = useState("");
  const [userGenreTags, setUserGenreTags] = useState(
    (initialBook.user_genre_tags || []).join(", "),
  );
  const [removedChapters, setRemovedChapters] = useState(
    initialBook.removed_chapters || [],
  );
  const [contentSelectors, setContentSelectors] = useState(
    initialBook.content_selectors || [],
  );
  const [previewResult, setPreviewResult] = useState(null);
  const [previewedChapter, setPreviewedChapter] = useState(null);
  const [chapterSearch, setChapterSearch] = useState("");
  const [chaptersExpanded, setChaptersExpanded] = useState(false);
  const [chapterPreviewMode, setChapterPreviewMode] = useState("original");
  const [identifiersExpanded, setIdentifiersExpanded] = useState(false);

  // Reset form state when the parent navigates to a different book. We key this
  // on the initial prop (not the polled `book`) so background refetches — e.g.
  // while a refresh is in-flight — don't wipe out in-progress edits.
  useEffect(() => {
    setTitle(initialBook.title || "");
    setAuthor(initialBook.author || "");
    setSeries(initialBook.series || "");
    setSeriesIndex(
      initialBook.series_index != null ? String(initialBook.series_index) : "",
    );
    setNotes(initialBook.notes || "");
    setIsbn10(initialBook.metadata_remote_ids?.isbn_10 || "");
    setIsbn13(initialBook.metadata_remote_ids?.isbn_13 || "");
    setGoogleBooksVolumeId(
      initialBook.metadata_remote_ids?.google_books_volume_id || "",
    );
    setOpenLibraryWorkKey(
      initialBook.metadata_remote_ids?.open_library_work_key || "",
    );
    setOpenLibraryEditionKey(
      initialBook.metadata_remote_ids?.open_library_edition_key || "",
    );
    setOpenLibraryAuthorKey(
      initialBook.metadata_remote_ids?.open_library_author_key || "",
    );
    setOtherRemoteIdsJson(
      splitRemoteIds(initialBook.metadata_remote_ids).extrasJson,
    );
    setIdentifierError("");
    setUserGenreTags((initialBook.user_genre_tags || []).join(", "));
    setRemovedChapters(initialBook.removed_chapters || []);
    setContentSelectors(initialBook.content_selectors || []);
    setPreviewResult(null);
    setChapterSearch("");
    setChaptersExpanded(false);
    setChapterPreviewMode("original");
    setIdentifiersExpanded(false);
  }, [initialBook]);

  useEffect(() => {
    setPreviewResult(null);
  }, [contentSelectors, removedChapters]);

  const { data: chapters = [], isLoading: chaptersLoading } = useQuery({
    queryKey: ["chapters", book.id],
    queryFn: fetchChapters,
    enabled: Boolean(book.immutable_path),
  });

  const { data: cleanedChapters = [], isLoading: cleanedChaptersLoading } =
    useQuery({
      queryKey: ["cleaned-chapters", book.id],
      queryFn: fetchCleanedChapters,
      enabled: chapterPreviewMode === "cleaned" && Boolean(book.current_path),
    });

  const { data: matchedConfigs = [] } = useQuery({
    queryKey: ["matched-config", book.id],
    queryFn: fetchMatchedConfig,
  });

  const {
    data: updateHistory,
    isLoading: updateHistoryLoading,
    isError: updateHistoryIsError,
    error: updateHistoryError,
  } = useQuery({
    queryKey: ["book-update-history", book.id, book.content_version],
    queryFn: fetchUpdateHistory,
    enabled: book.source_type === "web",
    refetchInterval: isRefreshing ? 5000 : false,
  });

  const { data: allSeries = [] } = useQuery({
    queryKey: ["series"],
    queryFn: getSeries,
    staleTime: 60_000,
  });

  const saveMutation = useMutation({
    mutationFn: (data) => updateBook(book.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });

  const processMutation = useMutation({
    mutationFn: () => processBook(book.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({
        queryKey: ["cleaned-chapters", book.id],
      });
    },
  });

  // Kicks off an async refresh job and returns immediately. The useQuery above
  // polls until the book's refresh_status goes back to null (or "error"). We
  // keep the user on the page so they can see the progress and the final result
  // without having to rediscover the book in the catalog.
  const refreshMutation = useMutation({
    mutationFn: () => refreshBook(book.id),
    onSuccess: (updatedBook) => {
      queryClient.setQueryData(["book", book.id], updatedBook);
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({
        queryKey: ["book-update-history", book.id],
      });
    },
  });

  const detachSourceMutation = useMutation({
    mutationFn: () => detachBookSource(book.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      onBack();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteBook(book.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      onBack();
    },
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      previewCleaning(book.id, {
        content_selectors: contentSelectors,
        removed_chapters: removedChapters,
      }),
    onSuccess: (data) => setPreviewResult(data),
  });

  const [coverUrl, setCoverUrl] = useState("");

  // Cover files live at a deterministic URL (/api/covers/{book_id}), so the
  // browser happily caches them. Whenever any cover mutation succeeds we bump
  // `coverVersion` and append it as a cache-busting query param on the <img>,
  // forcing the browser to fetch the freshly-written file.
  const bumpCoverVersion = () => setCoverVersion((v) => v + 1);

  const coverMutation = useMutation({
    mutationFn: (file) => uploadBookCover(book.id, file),
    onSuccess: () => {
      bumpCoverVersion();
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["book", book.id] });
    },
  });

  const retryCoverMutation = useMutation({
    mutationFn: () => retryBookCover(book.id),
    onSuccess: () => {
      bumpCoverVersion();
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["book", book.id] });
    },
  });

  const coverUrlMutation = useMutation({
    mutationFn: (url) => setBookCoverUrl(book.id, url),
    onSuccess: () => {
      bumpCoverVersion();
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["book", book.id] });
      setCoverUrl("");
    },
  });

  const metadataSyncMutation = useMutation({
    mutationFn: () => queueMetadataSync([book.id], "manual"),
  });

  const getUpdatedFields = () => {
    let extraRemoteIds = {};
    if (otherRemoteIdsJson.trim()) {
      try {
        const parsed = JSON.parse(otherRemoteIdsJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          setIdentifierError("Other identifiers must be a JSON object.");
          return null;
        }
        extraRemoteIds = parsed;
      } catch {
        setIdentifierError("Other identifiers must be valid JSON.");
        return null;
      }
    }

    setIdentifierError("");

    const metadataRemoteIds = {
      ...extraRemoteIds,
      ...(isbn10.trim() ? { isbn_10: isbn10.trim() } : {}),
      ...(isbn13.trim() ? { isbn_13: isbn13.trim() } : {}),
      ...(googleBooksVolumeId.trim()
        ? { google_books_volume_id: googleBooksVolumeId.trim() }
        : {}),
      ...(openLibraryWorkKey.trim()
        ? { open_library_work_key: openLibraryWorkKey.trim() }
        : {}),
      ...(openLibraryEditionKey.trim()
        ? { open_library_edition_key: openLibraryEditionKey.trim() }
        : {}),
      ...(openLibraryAuthorKey.trim()
        ? { open_library_author_key: openLibraryAuthorKey.trim() }
        : {}),
    };

    return {
      title,
      author,
      series: series.trim() || null,
      series_index: seriesIndex.trim() ? Number.parseFloat(seriesIndex) : null,
      user_genre_tags: userGenreTags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      metadata_remote_ids: Object.keys(metadataRemoteIds).length
        ? metadataRemoteIds
        : null,
      removed_chapters: removedChapters,
      content_selectors: contentSelectors,
      notes: notes || null,
    };
  };

  const handleSave = () => {
    const payload = getUpdatedFields();
    if (!payload) return;
    saveMutation.mutate(payload);
  };

  const handleProcess = async () => {
    try {
      const payload = getUpdatedFields();
      if (!payload) return;
      await saveMutation.mutateAsync(payload);
      await processMutation.mutateAsync();
    } catch (err) {
      console.error("Save or process failed", err);
    }
  };

  const handleDelete = () => {
    if (window.confirm(`Delete "${book.title}"? This cannot be undone.`)) {
      deleteMutation.mutate();
    }
  };

  const handleDetachSource = () => {
    if (
      window.confirm(
        `Remove the web marker from "${book.title}"? This will keep the EPUB files but stop treating it as a web novel.`,
      )
    ) {
      detachSourceMutation.mutate();
    }
  };

  const toggleChapter = (filename) => {
    setRemovedChapters((prev) =>
      prev.includes(filename)
        ? prev.filter((f) => f !== filename)
        : [...prev, filename],
    );
  };

  const toggleChapterPreview = (filename) => {
    setPreviewedChapter((prev) => (prev === filename ? null : filename));
  };

  const isBusy =
    saveMutation.isPending ||
    processMutation.isPending ||
    refreshMutation.isPending ||
    detachSourceMutation.isPending ||
    deleteMutation.isPending ||
    isRefreshing;
  const canDetachWebMarker =
    book.source_type === "web" && book.immutable_path && book.current_path;

  return (
    <div className="book-settings">
      <div className="settings-header">
        <button
          className="btn-text"
          onClick={onBack}
          disabled={
            saveMutation.isPending ||
            processMutation.isPending ||
            refreshMutation.isPending ||
            detachSourceMutation.isPending ||
            deleteMutation.isPending
          }
          style={{ flexShrink: 0 }}
        >
          ← Back
        </button>
        <h2>{book.title}</h2>
      </div>

      {isRefreshing && (
        <div className="hint" role="status" style={{ marginBottom: "0.75rem" }}>
          {book.refresh_status === "queued"
            ? "This book is queued for refresh. It will start once the previous job finishes."
            : "Refreshing from source — pulling new chapters via FanFicFare. This can take a few minutes for long stories."}
        </div>
      )}
      {refreshErrored && (
        <p className="error" role="alert">
          The last refresh attempt failed. Check the logs, then click “Refresh
          from Source” to try again.
        </p>
      )}

      <section className="settings-section">
        <h3>Metadata</h3>
        <div className="settings-row-with-cover">
          <div className="settings-fields">
            <label>
              Title
              <input value={title} onChange={(e) => setTitle(e.target.value)} />
            </label>
            <label>
              Author
              <input
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
              />
            </label>
            <div className="field-row">
              <label className="field-row-grow">
                Series
                <input
                  list="series-options"
                  value={series}
                  onChange={(e) => setSeries(e.target.value)}
                  placeholder="Leave blank if none"
                />
                <datalist id="series-options">
                  {allSeries.map((s) => (
                    <option key={s} value={s} />
                  ))}
                </datalist>
              </label>
              <label className="field-row-shrink">
                Order
                <input
                  type="number"
                  step="0.01"
                  value={seriesIndex}
                  onChange={(e) => setSeriesIndex(e.target.value)}
                  placeholder="e.g. 2.5"
                />
              </label>
            </div>
            <div className="settings-tag-field">
              <span className="settings-field-label">Synced Genre Tags</span>
              <SyncedGenreTagList tags={book.genre_tags || []} />
            </div>
            {(book.source_tags || []).length > 0 && (
              <div className="settings-tag-field">
                <span className="settings-field-label">Source Tags</span>
                <SourceTagList tags={book.source_tags || []} />
              </div>
            )}
            <label>
              User Genre Tags
              <input
                value={userGenreTags}
                onChange={(e) => setUserGenreTags(e.target.value)}
                placeholder="Fantasy, Romance, LitRPG"
              />
            </label>
            {book.metadata_synced_at && (
              <p className="hint">
                Synced from {book.metadata_sync_source || "online metadata"} on{" "}
                {new Date(book.metadata_synced_at).toLocaleString()}.
              </p>
            )}
            <div className="settings-actions">
              <button
                type="button"
                onClick={() => metadataSyncMutation.mutate()}
                disabled={metadataSyncMutation.isPending}
              >
                {metadataSyncMutation.isPending
                  ? "Queueing…"
                  : "Recheck Online Metadata"}
              </button>
            </div>
            {metadataSyncMutation.isSuccess && (
              <p className="hint">Metadata recheck queued.</p>
            )}
          </div>
          <div className="settings-cover-aside">
            {book.cover_path ? (
              <img
                src={`${getApiCoverUrl(book.id)}?v=${coverVersion}`}
                alt="Cover"
                className="settings-cover-img"
              />
            ) : (
              <div className="settings-cover-placeholder">No cover</div>
            )}
            <input
              ref={coverInputRef}
              type="file"
              accept=".jpg,.jpeg,.png,.webp"
              style={{ display: "none" }}
              onChange={(e) =>
                e.target.files[0] && coverMutation.mutate(e.target.files[0])
              }
            />
            <button
              className="btn-sm"
              onClick={() => coverInputRef.current.click()}
              disabled={coverMutation.isPending || coverUrlMutation.isPending}
            >
              {coverMutation.isPending
                ? "Uploading…"
                : book.cover_path
                  ? "Replace"
                  : "Upload"}
            </button>
            {book.immutable_path && (
              <button
                className="btn-sm btn-secondary"
                onClick={() => retryCoverMutation.mutate()}
                disabled={
                  retryCoverMutation.isPending ||
                  coverMutation.isPending ||
                  coverUrlMutation.isPending
                }
              >
                {retryCoverMutation.isPending ? "Retrying…" : "Re-extract"}
              </button>
            )}
            <div className="cover-url-row">
              <input
                type="text"
                placeholder="Image URL…"
                value={coverUrl}
                onChange={(e) => setCoverUrl(e.target.value)}
                onKeyDown={(e) =>
                  e.key === "Enter" &&
                  coverUrl.trim() &&
                  coverUrlMutation.mutate(coverUrl.trim())
                }
              />
              <button
                className="btn-sm"
                onClick={() => coverUrlMutation.mutate(coverUrl.trim())}
                disabled={
                  !coverUrl.trim() ||
                  coverUrlMutation.isPending ||
                  coverMutation.isPending
                }
              >
                {coverUrlMutation.isPending ? "…" : "Set"}
              </button>
            </div>
            {coverMutation.isError && (
              <p className="error">{coverMutation.error.message}</p>
            )}
            {coverUrlMutation.isError && (
              <p className="error">{coverUrlMutation.error.message}</p>
            )}
            {retryCoverMutation.isError && (
              <p className="error">{retryCoverMutation.error.message}</p>
            )}
          </div>
        </div>
      </section>

      <section className="settings-section">
        <h3>Notes</h3>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Personal notes about this book"
          rows={3}
        />
      </section>

      {(book.source_url || book.source_type === "web") && (
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
                onClick={handleDetachSource}
                disabled={isBusy || !canDetachWebMarker}
              >
                {detachSourceMutation.isPending
                  ? "Removing…"
                  : "Remove Web Marker"}
              </button>
              {!canDetachWebMarker && (
                <span
                  className="hint"
                  style={{ margin: 0, alignSelf: "center" }}
                >
                  Requires EPUB files first
                </span>
              )}
            </div>
          )}
        </section>
      )}

      {book.source_type === "web" && (
        <ChapterUpdateHistory
          updateHistory={updateHistory}
          isLoading={updateHistoryLoading}
          isError={updateHistoryIsError}
          error={updateHistoryError}
        />
      )}

      <section className="settings-section">
        <div
          className="collapsible-header"
          onClick={() => setIdentifiersExpanded((e) => !e)}
        >
          <h3>
            Identifiers
            {(isbn10 ||
              isbn13 ||
              googleBooksVolumeId ||
              openLibraryWorkKey) && (
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
        </div>
        {identifiersExpanded && (
          <div className="collapsible-body">
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

      {matchedConfigs.map((cfg) => (
        <section key={cfg.id} className="settings-section">
          <h3>
            Inherited Cleaning Rules{" "}
            <span className="badge-config">{cfg.name}</span>
          </h3>
          <p className="hint">
            These site-wide rules apply automatically and cannot be edited here.
          </p>
          {cfg.chapter_selectors?.length > 0 && (
            <div>
              <strong>Chapter selectors:</strong>
              <div className="pills readonly">
                {cfg.chapter_selectors.map((s) => (
                  <span key={s} className="pill">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
          {cfg.content_selectors?.length > 0 && (
            <div>
              <strong>Content selectors:</strong>
              <div className="pills readonly">
                {cfg.content_selectors.map((s) => (
                  <span key={s} className="pill">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>
      ))}

      <section className="settings-section">
        <h3>Per-Book Content Selectors</h3>
        <p className="hint">
          CSS selectors for content to remove from this book only.
        </p>
        <SelectorPills
          selectors={contentSelectors}
          onChange={setContentSelectors}
        />
        <div
          style={{
            marginTop: "0.5rem",
            display: "flex",
            alignItems: "center",
            gap: "1rem",
          }}
        >
          <button
            onClick={() => previewMutation.mutate()}
            disabled={previewMutation.isPending}
          >
            {previewMutation.isPending ? "Previewing..." : "Preview"}
          </button>
          {previewResult && (
            <span className="hint">
              Would remove {previewResult.elements_removed} elements · ~
              {previewResult.estimated_word_count.toLocaleString()} words
              remaining
            </span>
          )}
          {previewMutation.isError && (
            <span className="error">{previewMutation.error.message}</span>
          )}
        </div>
      </section>

      <BookSettingsChapters
        book={book}
        chapters={chapters}
        cleanedChapters={cleanedChapters}
        chaptersLoading={chaptersLoading}
        cleanedChaptersLoading={cleanedChaptersLoading}
        chaptersExpanded={chaptersExpanded}
        setChaptersExpanded={setChaptersExpanded}
        chapterPreviewMode={chapterPreviewMode}
        setChapterPreviewMode={setChapterPreviewMode}
        chapterSearch={chapterSearch}
        setChapterSearch={setChapterSearch}
        removedChapters={removedChapters}
        toggleChapter={toggleChapter}
        previewedChapter={previewedChapter}
        toggleChapterPreview={toggleChapterPreview}
      />

      <section className="settings-section actions-bar">
        <div className="actions-primary">
          <button
            className="btn-primary"
            onClick={handleSave}
            disabled={isBusy}
          >
            {saveMutation.isPending ? "Saving..." : "Save Metadata"}
          </button>
          <button
            onClick={handleProcess}
            disabled={isBusy}
            title="Save changes and rebuild the EPUB file with current cleaning rules"
          >
            {processMutation.isPending
              ? "Rebuilding..."
              : "Save & Rebuild EPUB"}
          </button>
          {book.source_type === "web" && (
            <button onClick={() => refreshMutation.mutate()} disabled={isBusy}>
              {refreshMutation.isPending
                ? "Queueing…"
                : book.refresh_status === "queued"
                  ? "Queued for refresh…"
                  : book.refresh_status === "processing"
                    ? "Refreshing from source…"
                    : "Refresh from Source"}
            </button>
          )}
        </div>
        <p className="hint actions-hint">
          <strong>Save Metadata</strong> updates the database only.{" "}
          <strong>Save & Rebuild EPUB</strong> also regenerates the downloadable
          file with your cleaning rules applied.
        </p>
        <div className="actions-secondary">
          <a
            href={`/api/books/${book.id}/download`}
            download
            className="btn btn-secondary btn-sm"
          >
            Download EPUB
          </a>
          <button
            className="btn-danger btn-sm"
            onClick={handleDelete}
            disabled={isBusy}
          >
            Delete Book
          </button>
        </div>
      </section>

      {saveMutation.isError && (
        <p className="error">Save failed: {saveMutation.error.message}</p>
      )}
      {processMutation.isError && (
        <p className="error">Process failed: {processMutation.error.message}</p>
      )}
      {refreshMutation.isError && (
        <p className="error">Refresh failed: {refreshMutation.error.message}</p>
      )}
      {detachSourceMutation.isError && (
        <p className="error">
          Remove web marker failed: {detachSourceMutation.error.message}
        </p>
      )}
      {deleteMutation.isError && (
        <p className="error">Delete failed: {deleteMutation.error.message}</p>
      )}
    </div>
  );
}

export default BookSettings;
