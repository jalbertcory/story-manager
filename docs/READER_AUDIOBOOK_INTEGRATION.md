# Reader Audiobook Integration Contract

This document specifies the Story Manager work required by the Android reader's
optional generated-audio feature. The existing self-contained `audiobook.epub`
remains the admin/export artifact. Reader clients use a small text rendition and
independently cacheable chapter audio/SMIL assets.

## Observed local integration blocker (book 839)

As of 2026-07-20, local book 839 (`Old Man's War`) is a concrete acceptance
fixture for this contract:

- the admin API reports `audiobook_enabled: true` and
  `audiobook_pipeline_status: "complete"`;
- `library/audiobooks/839/audiobook.epub`, `working.epub`, chapter MP3 files,
  and chapter SMIL files exist;
- the running Reader OpenAPI advertises none of the audiobook routes below;
- the current `ReaderBook` schema and `_reader_book_payload` omit `audiobook`.

Consequently, the Android app correctly displays **Unavailable**. The admin
generation status and self-contained export EPUB are not Reader API capability
signals. The first backend integration milestone is complete only when an
authenticated `GET /reader/books/839` includes the optional `audiobook` object
and its `manifest_url` returns a valid modular manifest. This should be verified
before debugging Android playback or cache behavior.

## Compatibility and authentication

- All new fields are optional and all new routes use the same reader-key
  authentication and authorization rules as the existing `/reader` API.
- Existing reader responses remain valid. A book without generated audio omits
  `audiobook` or returns it as `null`.
- The reader never changes generation state. These endpoints are read-only.
- Reader asset URLs may be relative or absolute, but must remain under the
  configured Story Manager origin.

## ReaderBook capability

Add an optional `audiobook` object to every endpoint that returns `ReaderBook`,
including `/reader/books/all`, series/standalone lists, and `/reader/updates`.

```json
{
  "audiobook": {
    "status": "partial",
    "revision": 7,
    "source_content_version": 14,
    "text_content_version": 14,
    "ready_chapter_count": 11,
    "total_chapter_count": 18,
    "ready_audio_bytes": 82944000,
    "manifest_url": "/reader/books/941/audiobook/manifest"
  }
}
```

`status` is one of `processing`, `partial`, `complete`, or `error`. `revision`
is monotonically increasing and changes only after the manifest and referenced
asset state have committed. `text_content_version` identifies the normal EPUB
content version to which the span-anchored text rendition corresponds.

## Reader endpoints

Add:

- `GET /reader/books/{id}/audiobook/manifest`
- `GET /reader/books/{id}/audiobook/text`
- `GET /reader/books/{id}/audiobook/chapters/{chapter_key}/audio?version=N`
- `GET /reader/books/{id}/audiobook/chapters/{chapter_key}/smil?version=N`

Return `404` when the book has no audiobook capability. Return `409 Conflict`
for a chapter-version request that is no longer current, with a machine-readable
response instructing the client to refresh the manifest:

```json
{
  "error": "stale_audiobook_revision",
  "message": "Refresh the audiobook manifest before downloading this chapter.",
  "current_revision": 8
}
```

The text and chapter asset endpoints must:

- provide `Content-Length`, `ETag`, and a useful content type;
- honor `If-None-Match`;
- support byte ranges for MP3 responses, including `Accept-Ranges`,
  `Content-Range`, `206`, and `416`;
- expose only completely written files by publishing through atomic rename;
- keep an old version readable until the new manifest revision commits, or
  return the explicit stale-version conflict above.

## Manifest

Example:

```json
{
  "revision": 7,
  "source_content_version": 14,
  "text": {
    "content_version": 14,
    "size_bytes": 482301,
    "sha256": "9ab1...",
    "url": "/reader/books/941/audiobook/text"
  },
  "chapters": [
    {
      "key": "src-4d58c7",
      "title": "Chapter 12",
      "href": "Text/chapter-12.xhtml",
      "state": "ready",
      "audio_version": 3,
      "duration_ms": 844312,
      "audio_size_bytes": 12664680,
      "audio_sha256": "c07e...",
      "smil_size_bytes": 22104,
      "smil_sha256": "9cd2...",
      "audio_url": "/reader/books/941/audiobook/chapters/src-4d58c7/audio?version=3",
      "smil_url": "/reader/books/941/audiobook/chapters/src-4d58c7/smil?version=3"
    }
  ]
}
```

Requirements:

- `chapters` is in spine order.
- `key` is opaque, stable across web-story refreshes, and URL safe.
- `href` is the normalized XHTML resource href in the text rendition.
- `state` is `pending`, `processing`, `ready`, or `error`.
- Asset URLs, versions, sizes, and hashes are required for `ready` chapters and
  may be null otherwise.
- Hashes are lowercase SHA-256 hex strings over the response body.
- SMIL text references resolve to stable fragment IDs in the text rendition;
  audio references resolve to the chapter audio response.

## Durable data model and migration

Use an Alembic migration with a complete downgrade and test it against
PostgreSQL with representative existing audiobook data. Add durable storage for:

- a stable chapter source identity;
- normalized source/spine href and source-content hash;
- title and spine order;
- chapter audio revision and generation state;
- MP3/SMIL path, size, hash, and duration;
- book-level audiobook revision, source-content version, text-content version,
  pending-content version, enabled flag, state, text path/size/hash, and errors.

The migration must not assume any table is empty or that audiobook tables were
created by a previous Alembic migration. Preserve existing generated chapters
and final EPUB records whenever they can be associated safely.

Recommended invariants:

- `(book_id, stable_chapter_key)` is unique.
- A ready chapter has committed MP3 and SMIL metadata for the same
  `audio_revision`.
- A published manifest never points at a temporary or partial file.
- The reader-visible book revision increments in the same transaction that
  commits its visible chapter/text metadata.

## Incremental web-story ingestion

Replace destructive audiobook re-ingestion for refreshed web stories with a
diff:

1. Parse the refreshed EPUB and compute a normalized href and normalized content
   hash for each reading-order resource.
2. Match prior chapters by normalized spine href first. If the source moved,
   match an otherwise-unmatched chapter by unchanged content hash.
3. Preserve the stable key, character assignments, sentence analysis, generated
   audio, hashes, and audio revision for unchanged chapters.
4. Invalidate only changed chapters, create new chapter records, and remove
   deleted chapters and their unreferenced assets.
5. Generate XHTML span IDs from the stable chapter key plus stable sentence
   identity, not mutable spine position.
6. Publish the refreshed span-anchored text EPUB immediately after ingestion.
   New and changed chapters appear in the manifest as pending while unchanged
   chapters remain ready.
7. When `audiobook_enabled` is true, enqueue only new or changed chapters.
8. If a refresh lands during active generation, persist `pending_content_version`
   and process it at the next durable chapter/job boundary. Do not lose either
   refresh or completed work.
9. Increment the reader-visible audiobook revision only after all visible
   manifest and asset metadata has committed.

The generated text EPUB should preserve reading-order hrefs wherever possible so
the Android reader can carry rendition-neutral locators between the normal and
span-anchored renditions.

## Backend tests

Add tests for:

- legacy and audiobook-capable `ReaderBook` payloads on every reader listing;
- reader-key authentication and book authorization for every new route;
- processing, partial, complete, and error manifests;
- ETag/`304`, valid and invalid MP3 ranges, `Content-Length`, and stale versions;
- PostgreSQL upgrade/downgrade with existing audiobook rows;
- append-one-chapter preserving every previous audio revision and file;
- edit-one-chapter invalidating only that chapter;
- chapter removal cleaning unreferenced assets;
- a web refresh arriving during generation and resuming from the pending version;
- atomic publication: no manifest can reference an incomplete text, MP3, or SMIL
  file.
