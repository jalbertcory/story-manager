import type { CatalogBook, OpenBook } from "../types";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import StandaloneTagAction from "./book-list/StandaloneTagAction";
import { getSeries } from "../api/series";
import { buildCatalogGroups } from "../lib/catalogGrouping";
import { BookRow } from "./book-list/BookCards";
import SeriesSummaryRow from "./book-list/SeriesSummaryRow";

export function LibraryViewTabs({
  view,
  onChange,
  counts,
}: {
  view: string;
  onChange: (view: string) => void;
  counts: { series: number; standalone: number; web: number };
}) {
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

function getWebNovelStatus(book: CatalogBook) {
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

function BookList({
  books = [],
  totalCount = 0,
  onEdit,
  libraryView = "series",
  sortBy = "title",
  sortOrder = "asc",
  fetchNextPage,
  hasNextPage = false,
  isFetchingNextPage = false,
}: {
  books?: CatalogBook[];
  totalCount?: number;
  onEdit: OpenBook;
  libraryView?: string;
  sortBy?: string;
  sortOrder?: string;
  fetchNextPage?: () => unknown;
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
}) {
  const sentinelRef = useRef<HTMLDivElement>(null);
  const [showStandaloneSeriesEdit, setShowStandaloneSeriesEdit] =
    useState(false);

  const { data: allSeries = [] } = useQuery({
    queryKey: ["series"],
    queryFn: getSeries,
    staleTime: 60_000,
  });

  const { seriesMap, sortedSeries, standaloneBooks, webBooks } = useMemo(
    () => buildCatalogGroups(books, sortBy, sortOrder),
    [books, sortBy, sortOrder],
  );
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || !hasNextPage || isFetchingNextPage) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          void fetchNextPage?.();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage, libraryView]);

  return (
    <div className="book-list">
      {libraryView === "series" &&
        (sortedSeries.length ? (
          sortedSeries.map((series) => (
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
                {totalCount} book
                {totalCount === 1 ? "" : "s"} without a series.
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
              {standaloneBooks.map((book) => (
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
            {webBooks.map((book) => (
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
      {isFetchingNextPage && (
        <p className="catalog-loading-more">Loading more…</p>
      )}
    </div>
  );
}

export default BookList;
