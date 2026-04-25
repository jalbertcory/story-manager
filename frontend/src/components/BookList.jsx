import React, { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { updateBook } from "../api/books";
import { buildCatalogGroups } from "../lib/catalogGrouping";
import { BookCard, BookRow, GenreTagList } from "./book-list/BookCards";
import { getCoverUrl, getSeriesGenreTags } from "./book-list/catalogDisplay";
import {
  getSeries,
  mergeSeries,
  renameSeries,
  reorderSeries,
  updateSeriesGenres,
} from "../api/series";

function SeriesSummaryRow({ series, books, onEdit, allSeries }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(null); // null | "rename" | "merge" | "genres"
  const [renameValue, setRenameValue] = useState(series);
  const [mergeTarget, setMergeTarget] = useState("");
  const [genreValue, setGenreValue] = useState("");
  const [orderedBooks, setOrderedBooks] = useState(books);
  const [draggedBookId, setDraggedBookId] = useState(null);
  const [dragOverBookId, setDragOverBookId] = useState(null);

  useEffect(() => {
    setOrderedBooks(books);
  }, [books]);

  const seriesGenreTags = useMemo(
    () => getSeriesGenreTags(orderedBooks),
    [orderedBooks],
  );

  useEffect(() => {
    setGenreValue(seriesGenreTags.join(", "));
  }, [seriesGenreTags, series]);

  const genreInputId = useMemo(
    () => `series-genres-${series.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
    [series],
  );

  const renameMutation = useMutation({
    mutationFn: (newName) => renameSeries(series, newName),
    onSuccess: () => {
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });

  const mergeMutation = useMutation({
    mutationFn: (target) => mergeSeries(series, target),
    onSuccess: () => {
      setEditing(null);
      setMergeTarget("");
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });

  const reorderMutation = useMutation({
    mutationFn: (orderedBookIds) => reorderSeries(series, orderedBookIds),
    onSuccess: () => {
      setDraggedBookId(null);
      setDragOverBookId(null);
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
    onError: () => {
      setOrderedBooks(books);
      setDraggedBookId(null);
      setDragOverBookId(null);
    },
  });

  const genresMutation = useMutation({
    mutationFn: (userGenreTags) => updateSeriesGenres(series, userGenreTags),
    onSuccess: () => {
      setEditing(null);
      queryClient.invalidateQueries({ queryKey: ["book-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["series"] });
    },
  });

  const summary = useMemo(() => {
    const authors = [
      ...new Set(orderedBooks.map((book) => book.author).filter(Boolean)),
    ];
    const totalWords = orderedBooks.reduce(
      (sum, book) => sum + (book.current_word_count ?? 0),
      0,
    );
    const coverBooks = orderedBooks
      .filter((book) => book.cover_path && !book.download_status)
      .slice(0, 4);
    const coverBook =
      coverBooks[0] ??
      orderedBooks.find((book) => !book.download_status) ??
      orderedBooks[0];

    const latestUpdate = orderedBooks.reduce((latest, book) => {
      if (!book.updated_at) return latest;
      const d = new Date(book.updated_at);
      return d > latest ? d : latest;
    }, new Date(0));

    return {
      authors,
      totalWords,
      hasWebNovel: orderedBooks.some((book) => book.source_type === "web"),
      coverBook,
      coverBooks,
      latestUpdate: latestUpdate.getTime() > 0 ? latestUpdate : null,
    };
  }, [orderedBooks]);

  const otherSeries = allSeries.filter(
    (s) => s.toLowerCase() !== series.toLowerCase(),
  );

  const moveBook = (fromId, toId) => {
    if (fromId == null || toId == null || fromId === toId) return;
    const currentIndex = orderedBooks.findIndex((book) => book.id === fromId);
    const targetIndex = orderedBooks.findIndex((book) => book.id === toId);
    if (currentIndex === -1 || targetIndex === -1) return;

    const next = [...orderedBooks];
    const [moved] = next.splice(currentIndex, 1);
    next.splice(targetIndex, 0, moved);
    setOrderedBooks(next);
    reorderMutation.mutate(next.map((book) => book.id));
  };

  const toggleExpanded = () => {
    setExpanded((current) => {
      const next = !current;
      if (!next) {
        setEditing(null);
      }
      return next;
    });
  };

  const formatWords = (n) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k`;
    return String(n);
  };

  return (
    <div className={`series-group${expanded ? " series-group--expanded" : ""}`}>
      <div className="series-header" onClick={toggleExpanded}>
        <div className="series-cover-stack">
          {summary.coverBooks.length > 1 ? (
            summary.coverBooks
              .slice(0, 3)
              .map((book, i) => (
                <img
                  key={book.id}
                  src={getCoverUrl(book)}
                  alt={i === 0 ? `${series} cover` : ""}
                  className="series-cover-image series-cover-stacked"
                  style={{ "--stack-i": i }}
                  loading="lazy"
                  decoding="async"
                />
              ))
          ) : summary.coverBook?.cover_path ? (
            <img
              src={getCoverUrl(summary.coverBook)}
              alt={`${series} cover`}
              className="series-cover-image"
              loading="lazy"
              decoding="async"
            />
          ) : (
            <div className="series-cover-placeholder">
              <span className="series-cover-placeholder-text">
                {series.charAt(0)}
              </span>
            </div>
          )}
        </div>
        <div className="series-summary">
          <div className="series-summary-topline">
            <span className="series-name">{series}</span>
            {summary.hasWebNovel && <span className="badge-web">Web</span>}
          </div>
          <div className="series-meta">
            <span className="series-meta-author">
              {summary.authors.join(", ") || "Unknown author"}
            </span>
          </div>
          <div className="series-stats">
            <span className="series-stat">
              <span className="series-stat-value">{books.length}</span>
              <span className="series-stat-label">
                book{books.length !== 1 ? "s" : ""}
              </span>
            </span>
            {summary.totalWords > 0 && (
              <span className="series-stat">
                <span className="series-stat-value">
                  {formatWords(summary.totalWords)}
                </span>
                <span className="series-stat-label">words</span>
              </span>
            )}
            {summary.latestUpdate && (
              <span className="series-stat series-stat--date">
                {summary.latestUpdate.toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                })}
              </span>
            )}
          </div>
          <GenreTagList
            tags={seriesGenreTags}
            className="series-header-genres"
          />
        </div>
        <span
          className={`series-toggle${expanded ? " series-toggle--open" : ""}`}
          aria-hidden="true"
        />
      </div>
      {expanded && (
        <div className="series-expanded">
          <div className="series-toolbar">
            <div className="series-actions">
              <button
                type="button"
                className={`series-action-btn${editing === "rename" ? " series-action-btn--active" : ""}`}
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
                className={`series-action-btn${editing === "merge" ? " series-action-btn--active" : ""}`}
                title="Merge into another series"
                onClick={() => {
                  setEditing(editing === "merge" ? null : "merge");
                  setMergeTarget("");
                }}
              >
                Merge
              </button>
              <button
                type="button"
                className={`series-action-btn${editing === "genres" ? " series-action-btn--active" : ""}`}
                title="Edit series genres"
                onClick={() => {
                  setEditing(editing === "genres" ? null : "genres");
                  setGenreValue(seriesGenreTags.join(", "));
                }}
              >
                Genres
              </button>
            </div>
          </div>
          {editing === "rename" && (
            <form
              className="series-edit-form"
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
              <button
                type="submit"
                className="btn"
                disabled={
                  !renameValue.trim() ||
                  renameValue.trim() === series ||
                  renameMutation.isPending
                }
              >
                {renameMutation.isPending ? "Saving..." : "Save"}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setEditing(null)}
              >
                Cancel
              </button>
              {renameMutation.isError && (
                <span className="error-text">
                  {renameMutation.error.message}
                </span>
              )}
            </form>
          )}
          {editing === "merge" && (
            <form
              className="series-edit-form"
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
              <button
                type="submit"
                className="btn"
                disabled={!mergeTarget.trim() || mergeMutation.isPending}
              >
                {mergeMutation.isPending ? "Merging..." : "Merge"}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setEditing(null)}
              >
                Cancel
              </button>
              {mergeMutation.isError && (
                <span className="error-text">
                  {mergeMutation.error.message}
                </span>
              )}
            </form>
          )}
          {editing === "genres" && (
            <form
              className="series-edit-form"
              onSubmit={(e) => {
                e.preventDefault();
                genresMutation.mutate(
                  genreValue
                    .split(",")
                    .map((tag) => tag.trim())
                    .filter(Boolean),
                );
              }}
            >
              <label htmlFor={genreInputId}>Genres:</label>
              <input
                id={genreInputId}
                value={genreValue}
                onChange={(e) => setGenreValue(e.target.value)}
                placeholder="Fantasy, Science Fiction, Progression Fantasy"
                autoFocus
              />
              <button
                type="submit"
                className="btn"
                disabled={genresMutation.isPending}
              >
                {genresMutation.isPending ? "Saving..." : "Save"}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setEditing(null)}
              >
                Cancel
              </button>
              {genresMutation.isError && (
                <span className="error-text">
                  {genresMutation.error.message}
                </span>
              )}
            </form>
          )}
          <div className="book-grid">
            {orderedBooks.map((book) => (
              <div
                key={book.id}
                className={`series-book-item${
                  draggedBookId === book.id ? " series-book-item--dragging" : ""
                }${dragOverBookId === book.id ? " series-book-item--drop-target" : ""}`}
                draggable={!reorderMutation.isPending}
                onDragStart={() => {
                  setDraggedBookId(book.id);
                  setDragOverBookId(null);
                }}
                onDragOver={(event) => {
                  event.preventDefault();
                  if (draggedBookId !== book.id) {
                    setDragOverBookId(book.id);
                  }
                }}
                onDragLeave={() => {
                  if (dragOverBookId === book.id) {
                    setDragOverBookId(null);
                  }
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  moveBook(draggedBookId, book.id);
                }}
                onDragEnd={() => {
                  setDraggedBookId(null);
                  setDragOverBookId(null);
                }}
              >
                <div className="series-book-order">
                  {book.series_index != null ? `#${book.series_index}` : "⋮⋮"}
                </div>
                <BookCard book={book} onEdit={onEdit} />
              </div>
            ))}
          </div>
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
    <div
      className="library-view-tabs"
      role="tablist"
      aria-label="Library views"
    >
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

function StandaloneTagAction({ book, seriesOptions }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(book.series || "");

  useEffect(() => {
    setValue(book.series || "");
  }, [book.id, book.series]);

  const saveMutation = useMutation({
    mutationFn: (nextSeries) =>
      updateBook(book.id, { series: nextSeries.trim() || null }),
    onSuccess: () => {
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
      <button
        type="submit"
        className="btn"
        disabled={unchanged || saveMutation.isPending}
      >
        {saveMutation.isPending ? "Saving..." : "Save"}
      </button>
    </form>
  );
}

const TAB_PAGE_SIZE = 30;

function BookList({
  books = [],
  onEdit,
  libraryView: libraryViewProp,
  onLibraryViewChange,
  sortBy = "title",
  sortOrder = "asc",
}) {
  const sentinelRef = useRef(null);
  const [internalView, setInternalView] = useState("series");
  const libraryView = libraryViewProp ?? internalView;
  const [tabVisibleCount, setTabVisibleCount] = useState(TAB_PAGE_SIZE);
  const [showStandaloneSeriesEdit, setShowStandaloneSeriesEdit] =
    useState(false);

  const { data: allSeries = [] } = useQuery({
    queryKey: ["series"],
    queryFn: getSeries,
    staleTime: 60_000,
  });

  const handleTabChange = (tab) => {
    if (onLibraryViewChange) onLibraryViewChange(tab);
    else setInternalView(tab);
    setTabVisibleCount(TAB_PAGE_SIZE);
  };

  const { seriesMap, sortedSeries, standaloneBooks, webBooks, counts } =
    useMemo(
      () => buildCatalogGroups(books, sortBy, sortOrder),
      [books, sortBy, sortOrder],
    );

  const tabItems =
    libraryView === "series"
      ? sortedSeries
      : libraryView === "standalone"
        ? standaloneBooks
        : webBooks;

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
      <LibraryViewTabs
        view={libraryView}
        onChange={handleTabChange}
        counts={counts}
      />
      {libraryView === "series" &&
        (sortedSeries.length ? (
          sortedSeries
            .slice(0, tabVisibleCount)
            .map((series) => (
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
        ))}
      {libraryView === "standalone" &&
        (standaloneBooks.length ? (
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
                  subtitle={
                    book.series
                      ? `Series: ${book.series}`
                      : "No series assigned"
                  }
                  actions={
                    showStandaloneSeriesEdit && !book.download_status ? (
                      <StandaloneTagAction
                        book={book}
                        seriesOptions={allSeries.filter(
                          (series) => series !== book.series,
                        )}
                      />
                    ) : null
                  }
                />
              ))}
            </div>
          </>
        ) : (
          <p>No standalone books found.</p>
        ))}
      {libraryView === "web" &&
        (webBooks.length ? (
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
        ))}
      <div ref={sentinelRef} style={{ height: 1 }} />
    </div>
  );
}

export default BookList;
