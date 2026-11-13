function choice<T extends string, F extends string>(
  value: string | null,
  choices: readonly T[],
  fallback: F,
): T | F {
  return choices.find((option) => option === value) ?? fallback;
}
import type { LibraryValues, Navigate, OpenBook } from "../types";
import { useEffect, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import type { BookCatalogParams } from "../api/books";
import { getSeries } from "../api/series";
import { getLibraryGroups, getWebChecks } from "../api/library";
import {
  isRecentUpdate,
  lastUpdateLabel,
  libraryPath,
  RECENT_UPDATE_DAYS,
} from "../lib/library";
import useLibraryCatalog from "../hooks/useLibraryCatalog";
import useDebouncedValue from "../hooks/useDebouncedValue";
import { BookRow } from "./book-list/BookCards";
import StandaloneTagAction from "./book-list/StandaloneTagAction";
import LibraryGroups from "./library/LibraryGroups";
import LibraryToolbar from "./library/LibraryToolbar";
import SavedLibraryViews from "./library/SavedLibraryViews";
import SeriesOrganizer from "./library/SeriesOrganizer";
import Icon from "./ui/Icon";
import { queryKeys } from "../lib/queryKeys";

export default function LibraryWorkspace({
  search,
  hash,
  onNavigate,
  onEdit,
  onReady,
  filtersOpen,
  onFiltersToggle,
}: {
  search: string;
  hash: string;
  onNavigate: Navigate;
  onEdit: OpenBook;
  onReady?: () => void;
  filtersOpen?: boolean;
  onFiltersToggle?: (open: boolean) => void;
}) {
  const params = new URLSearchParams(search);
  const legacy = hash?.slice(1);
  const requestedGroup =
    params.get("group") ||
    (["standalone", "web"].includes(legacy) ? "none" : "series");
  const group = ["series", "universe", "none"].includes(requestedGroup)
    ? requestedGroup
    : "series";
  const series = params.has("series")
    ? params.get("series")
    : legacy === "standalone"
      ? ""
      : undefined;
  const universe = params.has("universe")
    ? Number(params.get("universe"))
    : undefined;
  const universeName = params.get("universeName") || "No universe";
  const source = choice(
    params.get("source"),
    ["web", "epub", "audiobook"] as const,
    legacy === "web" ? "web" : "",
  );
  const genre = params.get("genre") || "";
  const audiobook = choice(
    params.get("audiobook"),
    ["available", "none", "playable", "unplayable"] as const,
    "",
  );
  const review = choice(
    params.get("review"),
    ["missing-series", "refreshing", "refresh-error"] as const,
    "",
  );
  const defaultSort = series ? "series_index" : "title";
  const allowedSorts: NonNullable<BookCatalogParams["sortBy"]>[] = [
    "title",
    "author",
    "word_count",
    "updated_at",
    ...(series ? ["series_index" as const] : []),
  ];
  const sort = choice(params.get("sort"), allowedSorts, defaultSort);
  const order: "desc" | "asc" = params.get("order") === "desc" ? "desc" : "asc";
  const [q, setQ] = useState(params.get("q") || "");
  const [assigningSeries, setAssigningSeries] = useState(false);
  const [organizing, setOrganizing] = useState(false);
  useEffect(() => {
    setQ(new URLSearchParams(search).get("q") || "");
    setOrganizing(false);
  }, [search]);
  const query = useDebouncedValue(q.trim(), 250);
  const grouped = series == null && group !== "none";
  const groupBy =
    universe == null && group === "universe" ? "universe" : "series";
  const request = {
    q: query,
    ...(universe != null ? { universe } : {}),
    source,
    genre,
    audiobook,
    review,
    sortBy: sort,
    sortOrder: order,
  };
  const groups = useInfiniteQuery({
    queryKey: queryKeys.libraryGroups.list({ groupBy, ...request }),
    queryFn: ({ pageParam, signal }) =>
      getLibraryGroups(
        {
          groupBy,
          ...request,
          sortBy:
            sort === "series_index" || sort === "audiobook_enabled"
              ? "title"
              : sort,
          cursor: pageParam,
        },
        { signal },
      ),
    initialPageParam: "",
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: grouped,
  });
  const catalog = useLibraryCatalog({
    ...request,
    ...(series != null ? { series } : {}),
    view: "all",
    enabled: !grouped,
  });
  // Searching lists standalone matches directly instead of behind a group.
  const flattenStandalone = grouped && groupBy === "series" && Boolean(query);
  const standalone = useLibraryCatalog({
    ...request,
    series: "",
    view: "all",
    enabled: flattenStandalone,
  });
  const active = grouped ? groups : catalog;
  const groupItems = (
    groups.data?.pages.flatMap((page) => page.items) || []
  ).filter((item) => !flattenStandalone || item.name != null);
  const bookItems = catalog.data?.pages.flatMap((page) => page.items) || [];
  const standaloneItems = flattenStandalone
    ? standalone.data?.pages.flatMap((page) => page.items) || []
    : [];
  const items = grouped ? groupItems : bookItems;
  const facets = active.data?.pages[0]?.facets;
  const groupTotal = active.data?.pages[0]?.total_count;
  // The paged group total still counts the hidden standalone group.
  const hasStandaloneGroup = Boolean(
    groups.data?.pages.some((page) => page.items.some((g) => g.name == null)),
  );
  const total =
    groupTotal != null && flattenStandalone && hasStandaloneGroup
      ? groupTotal - 1
      : groupTotal;
  const standaloneTotal = standalone.data?.pages[0]?.total_count;
  const allSeries = useQuery({
    queryKey: queryKeys.series,
    queryFn: getSeries,
    enabled: assigningSeries,
  });
  const webChecks = useQuery({
    queryKey: queryKeys.webChecks,
    queryFn: getWebChecks,
    staleTime: 60000,
  });
  const recentUpdates = new Map(
    (webChecks.data || [])
      .filter((check) => isRecentUpdate(check))
      .map((check) => [check.book_id, check]),
  );
  const updateStatus = (bookId: number) => {
    const label = lastUpdateLabel(recentUpdates.get(bookId));
    return label ? { tone: "success", label } : null;
  };
  const loading =
    active.isLoading || (flattenStandalone && standalone.isLoading);
  useEffect(() => {
    if (!loading) onReady?.();
  }, [loading, onReady]);
  const base = {
    group,
    ...(universe != null ? { universe, universeName } : {}),
  };
  const filters = {
    ...(source ? { source } : {}),
    ...(q ? { q } : {}),
    ...(genre ? { genre } : {}),
    ...(audiobook ? { audiobook } : {}),
    ...(review ? { review } : {}),
    ...(sort !== defaultSort ? { sort } : {}),
    ...(order !== "asc" ? { order } : {}),
  };
  const current = {
    ...base,
    ...(series != null ? { series } : {}),
    ...filters,
  };
  const change = (next: LibraryValues) =>
    onNavigate(libraryPath({ ...current, ...next }));
  const openBook: OpenBook = (book) => onEdit(book, libraryPath(current));
  const filteredSeries = Boolean(
    source || query || genre || audiobook || review,
  );
  const title =
    series != null
      ? series || "Standalone books"
      : universe != null
        ? universeName
        : "Library";
  return (
    <section className="library-workspace">
      {(series != null || universe != null) && (
        <nav className="breadcrumbs" aria-label="Library location">
          <a
            href={libraryPath({
              group,
              ...filters,
              sort: sort === "series_index" ? null : filters.sort,
            })}
          >
            Library
          </a>
          {universe != null && (
            <>
              <span>/</span>
              <a
                href={libraryPath({
                  ...base,
                  group: "universe",
                  ...filters,
                  sort: sort === "series_index" ? null : filters.sort,
                })}
              >
                {universeName}
              </a>
            </>
          )}
          {series != null && (
            <>
              <span>/</span>
              <span>{series || "Standalone books"}</span>
            </>
          )}
        </nav>
      )}
      <div className="workspace-heading">
        <div>
          <h2>{title}</h2>
          {series && sort === "series_index" && (
            <p className="hint">Books in series order</p>
          )}
        </div>
        <a className="btn-primary" href="/import">
          <Icon name="plus" size={17} />
          Add books
        </a>
      </div>
      {series == null && universe == null && recentUpdates.size > 0 && (
        <p className="hint library-updates-hint">
          {recentUpdates.size}{" "}
          {recentUpdates.size === 1 ? "story has" : "stories have"} new chapters
          from the last {RECENT_UPDATE_DAYS} days.{" "}
          <a href="/updates?show=recent">See what changed</a>
        </p>
      )}
      <LibraryToolbar
        filtersOpen={filtersOpen}
        onFiltersToggle={onFiltersToggle}
        values={{ ...current, sort, order }}
        q={q}
        setQ={setQ}
        change={change}
        genres={facets?.genres ?? []}
        inSeries={Boolean(series)}
      />
      {source === "audiobook" && (
        <p className="hint">
          Books missing an EPUB. Upload matching EPUBs to add text to these
          audiobooks automatically.
        </p>
      )}
      {loading && <p role="status">Loading library…</p>}
      {active.error && (
        <div className="error" role="alert">
          {active.error.message}
          <button
            onClick={() => {
              void (active.isFetchNextPageError
                ? active.fetchNextPage()
                : active.refetch());
            }}
          >
            Try again
          </button>
        </div>
      )}
      <div className="library-status-row">
        {!loading && total != null && (
          <p role="status">
            Showing {items.length} of {total}{" "}
            {grouped ? (flattenStandalone ? "series" : "groups") : "books"}
            {flattenStandalone && Boolean(standaloneTotal) && (
              <>
                {" "}
                and {standaloneItems.length} of {standaloneTotal} standalone{" "}
                {standaloneTotal === 1 ? "book" : "books"}
              </>
            )}
          </p>
        )}
        <SavedLibraryViews
          path={libraryPath(current)}
          onNavigate={onNavigate}
        />
      </div>
      {!loading && grouped && (
        <LibraryGroups
          items={groupItems}
          groupBy={groupBy}
          base={base}
          filters={filters}
          hideEmpty={standaloneItems.length > 0}
        />
      )}
      {!loading && grouped && active.hasNextPage && (
        <button
          className="load-more"
          disabled={active.isFetchingNextPage}
          onClick={() => {
            void active.fetchNextPage();
          }}
        >
          {active.isFetchingNextPage ? "Loading…" : "Load more groups"}
        </button>
      )}
      {!loading && standaloneItems.length > 0 && (
        <div className="library-book-list">
          {standaloneItems.map((book) => (
            <BookRow
              key={book.id}
              book={book}
              onEdit={openBook}
              status={updateStatus(book.id)}
            />
          ))}
        </div>
      )}
      {!loading && flattenStandalone && standalone.error && (
        <div className="error" role="alert">
          {standalone.error.message}
          <button
            onClick={() => {
              void (standalone.isFetchNextPageError
                ? standalone.fetchNextPage()
                : standalone.refetch());
            }}
          >
            Try again
          </button>
        </div>
      )}
      {!loading && flattenStandalone && standalone.hasNextPage && (
        <button
          className="load-more"
          disabled={standalone.isFetchingNextPage}
          onClick={() => {
            void standalone.fetchNextPage();
          }}
        >
          {standalone.isFetchingNextPage ? "Loading…" : "Load more books"}
        </button>
      )}
      {!loading && !grouped && (
        <>
          {series && !filteredSeries && (
            <details
              className="workspace-disclosure"
              onToggle={(event) => setOrganizing(event.currentTarget.open)}
            >
              <summary>Organize this series</summary>
              {organizing && (
                <SeriesOrganizer
                  key={series}
                  series={series}
                  onEdit={openBook}
                  onSeriesChange={(name) => change({ series: name })}
                />
              )}
            </details>
          )}
          {series === "" && (
            <button onClick={() => setAssigningSeries((value) => !value)}>
              {assigningSeries ? "Done assigning" : "Assign series"}
            </button>
          )}
          {allSeries.error && assigningSeries && (
            <p role="alert">Could not load series: {allSeries.error.message}</p>
          )}
          <div className="library-book-list">
            {bookItems.map((book) => (
              <BookRow
                key={book.id}
                book={book}
                onEdit={openBook}
                status={updateStatus(book.id)}
                actions={
                  assigningSeries && allSeries.data ? (
                    <StandaloneTagAction
                      book={book}
                      seriesOptions={allSeries.data}
                    />
                  ) : null
                }
                subtitle={
                  book.series
                    ? `${book.series}${book.series_index != null ? ` · Book ${book.series_index}` : ""}`
                    : null
                }
              />
            ))}
            {!items.length && !active.error && (
              <p className="empty-state">
                No books found. Try another search or add a book.
              </p>
            )}
          </div>
        </>
      )}
      {!grouped && active.hasNextPage && (
        <button
          className="load-more"
          disabled={active.isFetchingNextPage}
          onClick={() => {
            void active.fetchNextPage();
          }}
        >
          {active.isFetchingNextPage ? "Loading…" : "Load more books"}
        </button>
      )}
    </section>
  );
}
