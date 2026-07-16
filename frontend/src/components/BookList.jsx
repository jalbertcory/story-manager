import React, { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { updateBook } from "../api/books";
import { getSeries } from "../api/series";
import { buildCatalogGroups } from "../lib/catalogGrouping";
import { BookRow } from "./book-list/BookCards";
import SeriesSummaryRow from "./book-list/SeriesSummaryRow";

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

function getWebNovelStatus(book) {
  if (book.refresh_status === "processing") {
    return { label: "Refreshing now", tone: "progress" };
  }
  if (book.refresh_status === "queued") {
    return { label: "Refresh queued", tone: "progress" };
  }
  if (book.refresh_status === "error") {
    return { label: "Refresh needs attention", tone: "error" };
  }
  if (!book.updated_at) {
    return { label: "No library update recorded", tone: "muted" };
  }
  return {
    label: `Library updated ${new Date(book.updated_at).toLocaleDateString()}`,
    tone: "muted",
  };
}

function LibraryFilters({
  reviewFilter,
  onReviewFilterChange,
  audiobookFilter,
  onAudiobookFilterChange,
}) {
  return (
    <div className="library-filters" aria-label="Library filters">
      <label>
        Review
        <select
          value={reviewFilter}
          onChange={(event) => onReviewFilterChange(event.target.value)}
        >
          <option value="">Everything</option>
          <option value="missing-series">Missing series</option>
          <option value="refreshing">Refreshing or queued</option>
          <option value="refresh-error">Refresh needs attention</option>
        </select>
      </label>
      <label>
        Audiobook
        <select
          value={audiobookFilter}
          onChange={(event) => onAudiobookFilterChange(event.target.value)}
        >
          <option value="">All books</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Not enabled</option>
        </select>
      </label>
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
  const [reviewFilter, setReviewFilter] = useState("");
  const [audiobookFilter, setAudiobookFilter] = useState("");

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

  const handleReviewFilterChange = (value) => {
    setReviewFilter(value);
    if (value === "missing-series") {
      handleTabChange("standalone");
    } else if (value === "refreshing" || value === "refresh-error") {
      handleTabChange("web");
    }
  };

  const filteredBooks = useMemo(
    () =>
      books.filter((book) => {
        if (audiobookFilter === "enabled" && !book.audiobook_enabled) {
          return false;
        }
        if (audiobookFilter === "disabled" && book.audiobook_enabled) {
          return false;
        }
        if (reviewFilter === "missing-series") {
          return (
            !book.series && book.source_type !== "web" && !book.download_status
          );
        }
        if (reviewFilter === "refreshing") {
          return ["queued", "processing"].includes(book.refresh_status);
        }
        if (reviewFilter === "refresh-error") {
          return book.refresh_status === "error";
        }
        return true;
      }),
    [audiobookFilter, books, reviewFilter],
  );

  const { seriesMap, sortedSeries, standaloneBooks, webBooks, counts } =
    useMemo(
      () => buildCatalogGroups(filteredBooks, sortBy, sortOrder),
      [filteredBooks, sortBy, sortOrder],
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
      <LibraryFilters
        reviewFilter={reviewFilter}
        onReviewFilterChange={handleReviewFilterChange}
        audiobookFilter={audiobookFilter}
        onAudiobookFilterChange={setAudiobookFilter}
      />
      <div className="library-results-summary" role="status">
        Showing {filteredBooks.length} of {books.length} books
      </div>
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
              <p>
                {standaloneBooks.length} book
                {standaloneBooks.length === 1 ? "" : "s"} without a series.
              </p>
              <button
                type="button"
                className={`btn btn-sm${showStandaloneSeriesEdit ? " btn-active" : ""}`}
                onClick={() => setShowStandaloneSeriesEdit((v) => !v)}
              >
                {showStandaloneSeriesEdit ? "Done assigning" : "Assign series"}
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
                subtitle={book.series ? `Series: ${book.series}` : null}
                status={getWebNovelStatus(book)}
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
