import { useEffect, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
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
  const source = params.get("source") || (legacy === "web" ? "web" : "");
  const genre = params.get("genre") || "";
  const audiobook = params.get("audiobook") || "";
  const review = params.get("review") || "";
  const defaultSort = series ? "series_index" : "title";
  const allowedSorts = [
    "title",
    "author",
    "word_count",
    "updated_at",
    ...(series ? ["series_index"] : []),
  ];
  const sort = allowedSorts.includes(params.get("sort"))
    ? params.get("sort")
    : defaultSort;
  const order = params.get("order") === "desc" ? "desc" : "asc";
  const [q, setQ] = useState(params.get("q") || "");
  const [assigningSeries, setAssigningSeries] = useState(false);
  const [organizing, setOrganizing] = useState(false);
  useEffect(() => {
    setQ(new URLSearchParams(search).get("q") || "");
    setOrganizing(false);
  }, [search]);
  const query = useDebouncedValue(q.trim(), 250);
  const grouped = series == null && group !== "none";
  const groupBy = universe != null ? "series" : group;
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
      getLibraryGroups({ groupBy, ...request, cursor: pageParam }),
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
  const items = active.data?.pages.flatMap((page) => page.items) || [];
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
  const change = (next) => onNavigate(libraryPath({ ...current, ...next }));
  const openBook = (book) => onEdit(book, libraryPath(current));
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
          items={items}
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
          {items.map((book) => (
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
