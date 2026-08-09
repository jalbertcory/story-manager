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
