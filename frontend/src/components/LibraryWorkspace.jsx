import StandaloneTagAction from "./book-list/StandaloneTagAction";
import { compareSeriesBooks } from "../lib/catalogGrouping";
import { libraryPath } from "../lib/library";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getAllBookCatalog } from "../api/books";
import { getSeries } from "../api/series";
import { getLibraryGroups } from "../api/library";
import { getApiCoverUrl } from "../api/covers";
import useLibraryCatalog from "../hooks/useLibraryCatalog";
import useDebouncedValue from "../hooks/useDebouncedValue";
import { BookRow } from "./book-list/BookCards";
import SeriesSummaryRow from "./book-list/SeriesSummaryRow";
import UniverseMembership from "./UniverseMembership";

export default function LibraryWorkspace({
  search,
  hash,
  onNavigate,
  onEdit,
  onReady,
}) {
  const params = new URLSearchParams(search);
  const legacy = hash?.slice(1);
  const requestedGroup =
    params.get("group") ||
    (legacy === "standalone" || legacy === "web" ? "none" : "series");
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
  const source = params.get("source") || (legacy === "web" ? "web" : "");
  const [assigningSeries, setAssigningSeries] = useState(false);
  const [q, setQ] = useState(params.get("q") || "");
  const query = useDebouncedValue(q.trim(), 250);
  const grouped = series == null && group !== "none";
  const groupBy = universe != null ? "series" : group;
  const groups = useQuery({
    queryKey: ["library-groups", { groupBy, q: query, universe, source }],
    queryFn: () => getLibraryGroups({ groupBy, q: query, universe, source }),
    enabled: grouped,
  });
  const catalog = useLibraryCatalog({
    q: query,
    view: "all",
    series,
    universe,
    source,
    sortBy: "title",
    sortOrder: "asc",
    enabled: !grouped && !series,
  });
  // A series must load completely before its reorder action is available.
  const seriesBooks = useQuery({
    queryKey: ["series-books", series],
    queryFn: async () =>
      (await getAllBookCatalog({ series })).sort(compareSeriesBooks),
    enabled: Boolean(series),
  });
  const { data: allSeries = [] } = useQuery({
    queryKey: ["series"],
    queryFn: getSeries,
  });
  const books = series
    ? seriesBooks.data || []
    : catalog.data?.pages.flatMap((page) => page.items) || [];
  const loading = grouped
    ? groups.isLoading
    : series
      ? seriesBooks.isLoading
      : catalog.isLoading;
  useEffect(() => {
    if (!loading) onReady?.();
  }, [loading, onReady]);
  const error = grouped
    ? groups.error
    : series
      ? seriesBooks.error
      : catalog.error;
  const universeName = params.get("universeName") || "No universe";
  const title =
    series != null
      ? series || "Standalone books"
      : universe != null
        ? universeName
        : "Library";
  const base = {
    group,
    ...(universe != null ? { universe, universeName } : {}),
  };
  const change = (next) =>
    onNavigate(
      libraryPath({
        ...base,
        ...(source ? { source } : {}),
        ...(q ? { q } : {}),
        ...next,
      }),
    );
  const openBook = (book) => {
    // Save the current search in the return URL, including text still being typed.
    const returnTo = libraryPath({
      ...base,
      ...(series != null ? { series } : {}),
      ...(source ? { source } : {}),
      ...(q ? { q } : {}),
    });
    onEdit(book, returnTo);
  };
  return (
    <section className="library-workspace">
      {(series != null || universe != null) && (
        <nav className="breadcrumbs" aria-label="Library location">
          <a href={libraryPath({ group })}>Library</a>
          {universe != null && (
            <>
              <span>/</span>
              <a
                href={libraryPath({
                  group: "universe",
                  universe,
                  universeName,
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
          {series && <p className="hint">Books in series order</p>}
        </div>
        <a className="btn-primary" href="/import">
          Add books
        </a>
      </div>
      {!series && (
        <div className="library-toolbar">
          <input
            aria-label="Search library"
            placeholder="Search title, author, series, universe, or tag"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          {universe == null && (
            <label>
              Group by
              <select
                aria-label="Group library by"
                value={group}
                onChange={(e) =>
                  change({ group: e.target.value, series: null })
                }
              >
                <option value="series">Series</option>
                <option value="universe">Universe</option>
                <option value="none">None</option>
              </select>
            </label>
          )}
          <label>
            Source
            <select
              aria-label="Library source"
              value={source}
              onChange={(e) =>
                change({ source: e.target.value || null, series: null })
              }
            >
              <option value="">All sources</option>
              <option value="epub">Book files</option>
              <option value="web">Web novels</option>
            </select>
          </label>
        </div>
      )}
      {loading && <p role="status">Loading library…</p>}
      {error && (
        <p className="error" role="alert">
          {error.message}
        </p>
      )}
      {!loading && !error && grouped && (
        <div className="library-groups">
          {(groups.data || []).map((item) => (
            <a
              className="library-group-row"
              key={item.name || "ungrouped"}
              href={libraryPath(
                groupBy === "universe"
                  ? {
                      group: "universe",
                      universe: item.universe_id || 0,
                      universeName: item.name || "No universe",
                      source: source || null,
                    }
                  : {
                      ...base,
                      series: item.name || "",
                      source: source || null,
                    },
              )}
            >
              <div className="group-covers">
                {item.cover_ids.length ? (
                  item.cover_ids.map((id, i) => (
                    <img
                      key={id}
                      src={getApiCoverUrl(id)}
                      alt={
                        i === 0
                          ? `${item.name || "Standalone books"} cover`
                          : ""
                      }
                      style={{ "--stack-i": i }}
                      loading="lazy"
                    />
                  ))
                ) : (
                  <span className="cover-placeholder">No cover</span>
                )}
              </div>
              <div>
                <h3>
                  {item.name ||
                    (groupBy === "universe"
                      ? "No universe"
                      : "Standalone books")}
                </h3>
                <p>
                  {item.author_count === 1
                    ? item.author
                    : `${item.author_count} authors`}
                </p>
                <div className="group-formats">
                  <span>
                    {item.book_count} {item.book_count === 1 ? "book" : "books"}
                  </span>
                  {item.audio_count > 0 && (
                    <span>{item.audio_count} with audio</span>
                  )}
                </div>
              </div>
              <span className="group-chevron" aria-hidden="true">
                ›
              </span>
            </a>
          ))}
          {!groups.data?.length && (
            <p className="empty-state">
              No matching groups. Try another search or source.
            </p>
          )}
        </div>
      )}
      {series && !loading && !error && (
        <>
          <details className="workspace-disclosure">
            <summary>Organize this series</summary>
            <UniverseMembership
              key={`${series}-${books[0]?.universe_name}`}
              series={series}
              currentName={books[0]?.universe_name}
            />
          </details>
          <SeriesSummaryRow
            key={series}
            series={series}
            books={books}
            onEdit={openBook}
            allSeries={allSeries}
            defaultExpanded
            hideHeading
            onSeriesChange={(name) =>
              onNavigate(libraryPath({ ...base, series: name }))
            }
          />
        </>
      )}
      {!grouped && !series && !loading && !error && (
        <>
          {series === "" && (
            <button onClick={() => setAssigningSeries((value) => !value)}>
              {assigningSeries ? "Done assigning" : "Assign series"}
            </button>
          )}
          {books.map((book) => (
            <BookRow
              key={book.id}
              book={book}
              onEdit={openBook}
              actions={
                assigningSeries ? (
                  <StandaloneTagAction book={book} seriesOptions={allSeries} />
                ) : null
              }
              subtitle={
                book.series
                  ? `${book.series}${book.series_index != null ? ` · Book ${book.series_index}` : ""}`
                  : null
              }
            />
          ))}
          {!books.length && (
            <p className="empty-state">
              No books found. Try another search or add a book.
            </p>
          )}
          {catalog.hasNextPage && (
            <button
              className="load-more"
              disabled={catalog.isFetchingNextPage}
              onClick={() => catalog.fetchNextPage()}
            >
              {catalog.isFetchingNextPage ? "Loading…" : "Load more books"}
            </button>
          )}
        </>
      )}
    </section>
  );
}
