# Catalog pagination and query notes

## API contract

`GET /api/books/catalog` returns a page object with `items`, `next_cursor`,
`total_count`, and `facets`. The catalog accepts these query parameters:

- `view`: `series`, `standalone`, `web`, or `all`
- `q`: case-insensitive title, author, series, and book-tag search
- `review`: `missing-series`, `refreshing`, or `refresh-error`
- `audiobook`: `available` or `none`
- `genre`: an exact book genre tag
- `sort_by`: `title`, `author`, `word_count`, `updated_at`, or
  `audiobook_enabled`
- `sort_order`: `asc` or `desc`
- `limit`: 1–100 view units; defaults to 30
- `cursor`: the opaque continuation value from the preceding response

A view unit is one complete series in the series view and one book in the
other views. A series page therefore may contain more than `limit` book
entries, but never splits a matching series across pages. This preserves the
existing expandable series row and its reorder operation.

The first page fixes an upper book-ID watermark in the cursor. Later inserts
are excluded from that traversal, while keyset ordering avoids offset shifts.
The cursor also contains a fingerprint of every query option and is rejected
if reused with different search, filter, sort, view, or page-size parameters.

Facet counts are computed independently of the selected view, after applying
the current search and visible filters. Series counts use distinct series;
genre values are expanded and aggregated in SQL. Human-narrated editions are
included in both audiobook filtering and audiobook counts.

The reader endpoints are separate from the admin catalog endpoint and retain
their existing response shapes.

## Search and seek indexes

Migration `0031` backfills a denormalized `catalog_search_text` column and
keeps it synchronized through SQLAlchemy mapper events. Tags are stored as
explicit `tag:` records in that document, allowing exact genre filters while
ordinary search remains substring-friendly. PostgreSQL uses `pg_trgm` with a
GIN index for search plus partial expression indexes for title, author, word
count, and update-time keyset seeks. No catalog query casts JSON arrays to
text.

On PostgreSQL 16 with 10,001 representative books, `EXPLAIN (ANALYZE,
BUFFERS)` showed:

- an all-books title page using `ix_books_catalog_title_seek`, returning 31
  rows in 0.028 ms;
- a selective text search using `ix_books_catalog_search_trgm`, returning its
  match in 0.030 ms.

Both plans were collected after `ANALYZE books`; the title plan was an index
scan and the search plan was a bitmap index/heap scan.

## Representative API benchmark

The benchmark fixture contained 10,000 generated books plus one pre-existing
book, 500 series, 250 authors, two alternating genre families, 10% web
sources, and generated-audiobook flags on every seventh book. Measurements
were taken against a local PostgreSQL 16 container and a local Uvicorn process
after one warm-up request.

| Request | Warm response time | Payload |
| --- | ---: | ---: |
| Standalone, 30 books | 53–55 ms | 13.8 KiB |
| Series, 30 complete series | 78–80 ms | 275 KiB |
| Selective text search | 6–7 ms | 260 B |
| Fantasy filter, 30 books | 22–24 ms | 13.5 KiB |

The series fixture intentionally produces about 15 books per selected series,
so its payload represents 450 complete book summaries rather than 30 raw
books. The response remains bounded by the number and size of the selected
series instead of the size of the full library.

## Library workspace filters and organization

The main Library keeps search visible and hides the other controls behind **Filters**
initially. The toggle shows the number of active source, genre, audio, and review
filters. Collapsing the panel preserves your selections; it stays open while you
change filters and navigate, and starts collapsed after a reload.

The main Library supports source, genre, audio, and review filters alongside search,
grouping, and ascending/descending sorting. Filters carry through group drill-down,
book navigation, and the return to the library. “Ready to listen” checks for playable
media; “Audio imported or enabled” also includes unfinished imports and enabled AI
pipelines. Genre choices show counts from the current scope, without applying the
selected genre to those counts.

Expand **Saved views** to name the current search, filters, grouping, and sort order.
Views are stored in the current browser. Saving an existing name replaces that view;
deleting a saved view does not affect books.

Both group summaries and individual series load 30 entries at a time. **Load more
groups/books** requests the next cursor page. Series order supports fractional indices
and uses title and book ID to break ties. In ascending series order, unnumbered books
appear last. Open **Organize this series** to fetch the complete, unfiltered series
before renaming, merging, editing genres, or reordering. Organization is hidden while
filters limit the series, so an incomplete selection cannot replace its full order.

`GET /api/library/groups` accepts `genre`, `audiobook`, `review`, `sort_by`,
`sort_order`, `limit`, and `cursor` alongside its existing parameters. Supplying
`limit` returns `{items, next_cursor, total_count, facets}`; omitting it preserves
the original array response. Cursors bind to the filters and ordering and exclude
books added after the first page. As with the book catalog, they are not a database
snapshot: edits to existing sort keys or membership can change a traversal.

Catalog SQL lives in `backend/app/crud/catalog.py`; group summaries live in
`backend/app/services/library_groups.py`. Both use the shared cursor utilities in
`backend/app/catalog_pagination.py`. Library controls, saved views, group cards, and
the complete-series organizer have separate frontend components.
