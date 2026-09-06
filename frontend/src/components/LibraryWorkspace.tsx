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
import { getLibraryGroups } from "../api/library";
import { libraryPath } from "../lib/library";
import useLibraryCatalog from "../hooks/useLibraryCatalog";
import useDebouncedValue from "../hooks/useDebouncedValue";
import { BookRow } from "./book-list/BookCards";
import StandaloneTagAction from "./book-list/StandaloneTagAction";
import LibraryGroups from "./library/LibraryGroups";
import LibraryToolbar from "./library/LibraryToolbar";
import SavedLibraryViews from "./library/SavedLibraryViews";
import SeriesOrganizer from "./library/SeriesOrganizer";

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
    universe,
    source,
    genre,
    audiobook,
    review,
    sortBy: sort,
    sortOrder: order,
  };
  const groups = useInfiniteQuery({
    queryKey: ["library-groups", { groupBy, ...request }],
    queryFn: ({ pageParam }) =>
      getLibraryGroups({
        groupBy,
        ...request,
        sortBy:
          sort === "series_index" || sort === "audiobook_enabled"
            ? "title"
            : sort,
        cursor: pageParam,
      }),
    initialPageParam: "",
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: grouped,
  });
  const catalog = useLibraryCatalog({
    ...request,
    series,
    view: "all",
    enabled: !grouped,
  });
  const active = grouped ? groups : catalog;
  const groupItems = groups.data?.pages.flatMap((page) => page.items) || [];
  const bookItems = catalog.data?.pages.flatMap((page) => page.items) || [];
  const items = grouped ? groupItems : bookItems;
  const facets = active.data?.pages[0]?.facets;
  const total = active.data?.pages[0]?.total_count;
  const allSeries = useQuery({
    queryKey: ["series"],
    queryFn: getSeries,
    enabled: assigningSeries,
  });
  useEffect(() => {
    if (!active.isLoading) onReady?.();
  }, [active.isLoading, onReady]);
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
          Add books
        </a>
      </div>
      <LibraryToolbar
        filtersOpen={filtersOpen}
        onFiltersToggle={onFiltersToggle}
        values={{ ...current, sort, order }}
        q={q}
        setQ={setQ}
        change={change}
        genres={facets?.genres}
        inSeries={Boolean(series)}
      />
      <SavedLibraryViews path={libraryPath(current)} onNavigate={onNavigate} />
      {source === "audiobook" && (
        <p className="hint">
          Books missing an EPUB. Upload matching EPUBs to add text to these
          audiobooks automatically.
        </p>
      )}
      {active.isLoading && <p role="status">Loading library…</p>}
      {active.error && (
        <div className="error" role="alert">
          {active.error.message}
          <button
            onClick={() =>
              active.isFetchNextPageError
                ? active.fetchNextPage()
                : active.refetch()
            }
          >
            Try again
          </button>
        </div>
      )}
      {!active.isLoading && total != null && (
        <p role="status">
          Showing {items.length} of {total} {grouped ? "groups" : "books"}
        </p>
      )}
      {!active.isLoading && grouped && (
        <LibraryGroups
          items={groupItems}
          groupBy={groupBy}
          base={base}
          filters={filters}
        />
      )}
      {!active.isLoading && !grouped && (
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
          {bookItems.map((book) => (
            <BookRow
              key={book.id}
              book={book}
              onEdit={openBook}
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
        </>
      )}
      {active.hasNextPage && (
        <button
          className="load-more"
          disabled={active.isFetchingNextPage}
          onClick={() => active.fetchNextPage()}
        >
          {active.isFetchingNextPage
            ? "Loading…"
            : grouped
              ? "Load more groups"
              : "Load more books"}
        </button>
      )}
    </section>
  );
}
