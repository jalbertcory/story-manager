import React, { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const NO_COVER_SVG =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='250'%3E%3Crect width='200' height='250' fill='%23e0e0e0'/%3E%3Ctext x='100' y='125' dominant-baseline='middle' text-anchor='middle' font-family='sans-serif' font-size='14' fill='%23888'%3ENo Cover%3C/text%3E%3C/svg%3E";

function getCoverUrl(book) {
  if (!book.cover_path) {
    return null;
  }
  return `/api/covers/${book.id}`;
}

function BookCard({ book, onEdit }) {
  const isPending = book.download_status === "pending";
  const isError = book.download_status === "error";

  const handleCoverError = (e) => {
    e.target.onerror = null;
    e.target.src = NO_COVER_SVG;
  };

  const formattedDate = book.updated_at
    ? new Date(book.updated_at).toLocaleDateString()
    : null;

  let coverContent;
  if (isPending) {
    coverContent = (
      <div className="book-cover book-cover--placeholder">
        <div className="spinner" />
        <span>Downloading…</span>
      </div>
    );
  } else if (isError) {
    coverContent = (
      <div className="book-cover book-cover--placeholder book-cover--error">
        <span>⚠ Download failed</span>
      </div>
    );
  } else if (book.cover_path) {
    coverContent = (
      <div className="book-cover-container">
        <img
          src={getCoverUrl(book)}
          alt={`${book.title} cover`}
          className="book-cover"
          loading="lazy"
          decoding="async"
          onError={handleCoverError}
        />
        <div className="book-cover-title-overlay">{book.title}</div>
      </div>
    );
  } else {
    coverContent = (
      <div className="book-cover book-cover--placeholder book-cover--no-cover">
        <span className="book-no-cover-title">{book.title}</span>
        {book.author && <span className="book-no-cover-author">{book.author}</span>}
      </div>
    );
  }

  return (
    <div
      className={`book-card${isPending ? " book-card--pending" : ""}${isError ? " book-card--error" : ""}`}
      onClick={isPending ? undefined : () => onEdit(book)}
    >
      {coverContent}
      <div className="book-info">
        <h3 title={isPending || isError ? book.source_url : book.title}>
          {isPending
            ? "Downloading…"
            : isError
              ? "Download failed"
              : book.title}
        </h3>
        {!isPending && <p className="book-author">{book.author}</p>}
        {!isPending && book.series && (
          <p className="book-series">Series: {book.series}</p>
        )}
        {!isPending && (
          <p className="book-words">
            {book.current_word_count != null
              ? book.current_word_count.toLocaleString() + " words"
              : "—"}
          </p>
        )}
        {formattedDate && !isPending && (
          <p className="book-updated">Updated: {formattedDate}</p>
        )}
        {book.source_type === "web" && !isPending && (
          <span className="badge-web">Web</span>
        )}
        {isError && book.source_url && (
          <p className="book-error-url" title={book.source_url}>
            {book.source_url.length > 40
              ? book.source_url.slice(0, 40) + "…"
              : book.source_url}
          </p>
        )}
      </div>
    </div>
  );
}

function SeriesSummaryRow({ series, books, onEdit, allSeries }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(null); // null | "rename" | "merge"
  const [renameValue, setRenameValue] = useState(series);
  const [mergeTarget, setMergeTarget] = useState("");

  const renameMutation = useMutation({
    mutationFn: async (newName) => {
      const res = await fetch(`/api/series/${encodeURIComponent(series)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_name: newName }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to rename series");
      }
      return res.json();
    },
    onSuccess: () => {
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });

  const mergeMutation = useMutation({
    mutationFn: async (target) => {
      const res = await fetch("/api/series/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: series, target }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to merge series");
      }
      return res.json();
    },
    onSuccess: () => {
      setEditing(null);
      setMergeTarget("");
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });

  const summary = useMemo(() => {
    const authors = [...new Set(books.map((book) => book.author).filter(Boolean))];
    const totalWords = books.reduce(
      (sum, book) => sum + (book.current_word_count ?? 0),
      0,
    );
    const coverBook =
      books.find((book) => book.cover_path && !book.download_status) ??
      books.find((book) => !book.download_status) ??
      books[0];

    return {
      authors,
      totalWords,
      hasWebNovel: books.some((book) => book.source_type === "web"),
      coverBook,
    };
  }, [books]);

  const otherSeries = allSeries.filter((s) => s.toLowerCase() !== series.toLowerCase());

  return (
    <div className="series-group">
      <div className="series-header" onClick={() => setExpanded(!expanded)}>
        <span className="series-toggle">{expanded ? "▼" : "▶"}</span>
        <div className="series-cover">
          {summary.coverBook?.cover_path ? (
            <img
              src={getCoverUrl(summary.coverBook)}
              alt={`${series} cover`}
              className="series-cover-image"
              loading="lazy"
              decoding="async"
            />
          ) : (
            <div className="series-cover-placeholder">No cover</div>
          )}
        </div>
        <div className="series-summary">
          <div className="series-summary-topline">
            <span className="series-name">{series}</span>
            {summary.hasWebNovel && <span className="badge-web">Web in series</span>}
          </div>
          <div className="series-meta">
            <span>
              {books.length} book{books.length !== 1 ? "s" : ""}
            </span>
            <span>{summary.authors.join(", ") || "Unknown author"}</span>
            <span>
              {summary.totalWords
                ? `${summary.totalWords.toLocaleString()} words`
                : "Word count unavailable"}
            </span>
          </div>
        </div>
        <div className="series-actions" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="btn btn-sm"
            title="Rename series"
            onClick={() => {
              setEditing(editing === "rename" ? null : "rename");
              setRenameValue(series);
            }}
          >
            Rename
          </button>
          <button
            type="button"
            className="btn btn-sm"
            title="Merge into another series"
            onClick={() => {
              setEditing(editing === "merge" ? null : "merge");
              setMergeTarget("");
            }}
          >
            Merge
          </button>
        </div>
      </div>
      {editing === "rename" && (
        <form
          className="series-edit-form"
          onClick={(e) => e.stopPropagation()}
          onSubmit={(e) => {
            e.preventDefault();
            const trimmed = renameValue.trim();
            if (trimmed && trimmed !== series) {
              renameMutation.mutate(trimmed);
            }
          }}
        >
          <input
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            placeholder="New series name"
            autoFocus
          />
          <button type="submit" className="btn" disabled={!renameValue.trim() || renameValue.trim() === series || renameMutation.isPending}>
            {renameMutation.isPending ? "Saving..." : "Save"}
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => setEditing(null)}>Cancel</button>
          {renameMutation.isError && <span className="error-text">{renameMutation.error.message}</span>}
        </form>
      )}
      {editing === "merge" && (
        <form
          className="series-edit-form"
          onClick={(e) => e.stopPropagation()}
          onSubmit={(e) => {
            e.preventDefault();
            const trimmed = mergeTarget.trim();
            if (trimmed) {
              mergeMutation.mutate(trimmed);
            }
          }}
        >
          <label>Merge into:</label>
          <input
            list="merge-target-options"
            value={mergeTarget}
            onChange={(e) => setMergeTarget(e.target.value)}
            placeholder="Target series name"
            autoFocus
          />
          <datalist id="merge-target-options">
            {otherSeries.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
          <button type="submit" className="btn" disabled={!mergeTarget.trim() || mergeMutation.isPending}>
            {mergeMutation.isPending ? "Merging..." : "Merge"}
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => setEditing(null)}>Cancel</button>
          {mergeMutation.isError && <span className="error-text">{mergeMutation.error.message}</span>}
        </form>
      )}
      {expanded && (
        <div className="book-grid">
          {books.map((book) => (
            <BookCard key={book.id} book={book} onEdit={onEdit} />
          ))}
        </div>
      )}
    </div>
  );
}

function LibraryViewTabs({ view, onChange, counts }) {
  const tabs = [
    { id: "series", label: "Series", count: counts.series },
    { id: "standalone", label: "Standalone", count: counts.standalone },
    { id: "web", label: "Web", count: counts.web },
  ];

  return (
    <div className="library-view-tabs" role="tablist" aria-label="Library views">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={view === tab.id}
          className={`library-view-tab${view === tab.id ? " library-view-tab--active" : ""}`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
          <span className="library-view-tab-count">{tab.count}</span>
        </button>
      ))}
    </div>
  );
}

function BookRow({ book, onEdit, actions = null, subtitle = null }) {
  const handleOpen = () => onEdit(book);

  return (
    <div className="book-row">
      <button type="button" className="book-row-main" onClick={handleOpen}>
        <div className="book-row-cover">
          {book.cover_path ? (
            <img
              src={getCoverUrl(book)}
              alt={`${book.title} cover`}
              className="book-row-cover-image"
              loading="lazy"
              decoding="async"
            />
          ) : (
            <div className="book-row-cover-placeholder">No cover</div>
          )}
        </div>
        <div className="book-row-body">
          <div className="book-row-title">{book.title}</div>
          <div className="book-row-meta">
            <span>{book.author || "Unknown author"}</span>
            <span>
              {book.current_word_count != null
                ? `${book.current_word_count.toLocaleString()} words`
                : "Word count unavailable"}
            </span>
            {book.source_type === "web" && <span className="badge-web">Web</span>}
          </div>
          {subtitle && <div className="book-row-subtitle">{subtitle}</div>}
        </div>
      </button>
      {actions ? <div className="book-row-actions">{actions}</div> : null}
    </div>
  );
}

function StandaloneTagAction({ book, seriesOptions }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(book.series || "");

  useEffect(() => {
    setValue(book.series || "");
  }, [book.id, book.series]);

  const saveMutation = useMutation({
    mutationFn: async (nextSeries) => {
      const res = await fetch(`/api/books/${book.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ series: nextSeries.trim() || null }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to update series");
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["books"] });
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });

  const unchanged = (book.series || "") === value.trim();

  return (
    <form
      className="standalone-tag-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!unchanged) {
          saveMutation.mutate(value);
        }
      }}
    >
      <label className="standalone-tag-label" htmlFor={`series-tag-${book.id}`}>
        Series
      </label>
      <input
        id={`series-tag-${book.id}`}
        list={`series-options-${book.id}`}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Add to a series"
      />
      <datalist id={`series-options-${book.id}`}>
        {seriesOptions.map((series) => (
          <option key={series} value={series} />
        ))}
      </datalist>
      <button type="submit" className="btn" disabled={unchanged || saveMutation.isPending}>
        {saveMutation.isPending ? "Saving..." : "Save"}
      </button>
    </form>
  );
}

const TAB_PAGE_SIZE = 30;

function BookList({ books = [], onEdit, libraryView: libraryViewProp, onLibraryViewChange }) {
  const sentinelRef = useRef(null);
  const [internalView, setInternalView] = useState("series");
  const libraryView = libraryViewProp ?? internalView;
  const [tabVisibleCount, setTabVisibleCount] = useState(TAB_PAGE_SIZE);
  const [showStandaloneSeriesEdit, setShowStandaloneSeriesEdit] = useState(false);

  const { data: allSeries = [] } = useQuery({
    queryKey: ["series"],
    queryFn: async () => {
      const res = await fetch("/api/series");
      if (!res.ok) throw new Error("Failed to load series");
      return res.json();
    },
    staleTime: 60_000,
  });

  const handleTabChange = (tab) => {
    if (onLibraryViewChange) onLibraryViewChange(tab);
    else setInternalView(tab);
    setTabVisibleCount(TAB_PAGE_SIZE);
  };

  const { seriesMap, sortedSeries, standaloneBooks, webBooks, counts } = useMemo(() => {
    const sMap = {};
    const standalone = [];
    const web = [];

    for (const book of books) {
      if (book.source_type === "web" && !book.download_status) {
        web.push(book);
      }

      if (book.series && !book.download_status) {
        if (!sMap[book.series]) {
          sMap[book.series] = [];
        }
        sMap[book.series].push(book);
      } else if (book.source_type !== "web") {
        standalone.push(book);
      }
    }

    for (const seriesBooks of Object.values(sMap)) {
      seriesBooks.sort((left, right) => left.title.localeCompare(right.title));
    }

    const sorted = Object.keys(sMap).sort();
    return {
      seriesMap: sMap,
      sortedSeries: sorted,
      standaloneBooks: standalone,
      webBooks: web,
      counts: { series: sorted.length, standalone: standalone.length, web: web.length },
    };
  }, [books]);

  const tabItems =
    libraryView === "series" ? sortedSeries :
    libraryView === "standalone" ? standaloneBooks :
    webBooks;

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || tabVisibleCount >= tabItems.length) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setTabVisibleCount((c) => c + TAB_PAGE_SIZE);
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [libraryView, tabVisibleCount, tabItems.length]);

  if (!books.length) {
    return <p>No books found.</p>;
  }

  return (
    <div className="book-list">
      <LibraryViewTabs view={libraryView} onChange={handleTabChange} counts={counts} />
      {libraryView === "series" && (
        sortedSeries.length ? (
          sortedSeries.slice(0, tabVisibleCount).map((series) => (
            <SeriesSummaryRow
              key={series}
              series={series}
              books={seriesMap[series]}
              onEdit={onEdit}
              allSeries={allSeries}
            />
          ))
        ) : (
          <p>No series found.</p>
        )
      )}
      {libraryView === "standalone" && (
        standaloneBooks.length ? (
          <>
            <div className="standalone-header">
              <button
                type="button"
                className={`btn btn-sm${showStandaloneSeriesEdit ? " btn-active" : ""}`}
                onClick={() => setShowStandaloneSeriesEdit((v) => !v)}
              >
                {showStandaloneSeriesEdit ? "Hide Series Edit" : "Edit Series"}
              </button>
            </div>
            <div className="book-rows">
              {standaloneBooks.slice(0, tabVisibleCount).map((book) => (
                <BookRow
                  key={book.id}
                  book={book}
                  onEdit={onEdit}
                  subtitle={book.series ? `Series: ${book.series}` : "No series assigned"}
                  actions={
                    showStandaloneSeriesEdit && !book.download_status ? (
                      <StandaloneTagAction
                        book={book}
                        seriesOptions={allSeries.filter((series) => series !== book.series)}
                      />
                    ) : null
                  }
                />
              ))}
            </div>
          </>
        ) : (
          <p>No standalone books found.</p>
        )
      )}
      {libraryView === "web" && (
        webBooks.length ? (
          <div className="book-rows book-rows--web">
            {webBooks.slice(0, tabVisibleCount).map((book) => (
              <BookRow
                key={book.id}
                book={book}
                onEdit={onEdit}
                subtitle={book.series ? `Series: ${book.series}` : "Web novel"}
              />
            ))}
          </div>
        ) : (
          <p>No web novels found.</p>
        )
      )}
      <div ref={sentinelRef} style={{ height: 1 }} />
    </div>
  );
}

export default BookList;
