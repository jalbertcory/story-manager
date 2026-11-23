# Metadata matching

Metadata sync searches Open Library and Google Books, ranks all provider candidates together, and merges records
that agree on ISBN or strong title/author evidence. Google Books works without a key for light use; set
`GOOGLE_BOOKS_API_KEY` for your own quota. EPUB package metadata and a bounded sample of the opening pages supply
additional title, byline, series, and ISBN evidence. If the stored record conflicts with that evidence and an LLM is
configured under **Audio & AI Configuration**, the existing LLM endpoint pool resolves the identity before search.
The opening sample is not sent to an LLM for already-consistent records.

Series name and position are matching evidence, not just display metadata. Structured provider data and common title
patterns (such as `Book 3`, `Vol. 3`, or `#3`) are compared with the local series assignment. Position conflicts,
series-name conflicts, reused remote IDs, and corrections to an already-approved record are sent to the metadata
inbox with an explanation. Approving a correction replaces stale provider identifiers while retaining unrelated
local identifiers.

For unattended matching, decorated library titles are reduced to provider-facing title variants, missing series
positions are inferred, and candidates are allocated one-to-one across nearby books in the same job. Agreement from
two independent providers produces a near-perfect match. Only unresolved close candidates use the configured LLM:
it judges the bounded candidate list against opening-page evidence and may issue one refined search retry when every
provider search misses. Hard series conflicts and duplicate remote assignments always remain reviewable rather than
being overridden by the LLM.

Amazon has no comparable public book-search API. Its collector is therefore disabled by default and isolated from
the reliable providers: enable it with `AMAZON_METADATA_ENABLED=true`, and optionally choose a storefront with
`AMAZON_METADATA_DOMAIN` (for example `com`, `co.uk`, or `de`). Amazon blocking or markup changes do not fail the
metadata job. Docker Compose passes these variables through from the project `.env` file.

Apple Books is a keyless gap-filler. Apple's search API allows only about twenty requests a minute, so it is asked
only about books that Open Library, Google Books, and Amazon all missed, or books pinned to an `apple_books_id`
remote identifier. Matches contribute a description, publication date, genres, and a high-resolution cover address.
Disable it with `APPLE_BOOKS_METADATA_ENABLED=false`, or choose a storefront with `APPLE_BOOKS_COUNTRY` (a
two-letter code such as `us`, `gb`, or `de`).

## Covers

A cover comes from the first source that has one:

1. The cover embedded in the EPUB.
2. The story's source page, for web novels: dedicated Royal Road and ScribbleHub collectors, then the page's
   share image (`og:image` / `twitter:image`) for every other site. Images that look like site branding are skipped.
3. Matched metadata, when **Re-extract Cover** is used: the provider's cover address stored with the match, then
   Open Library's cover service by ISBN or edition key.

All downloads go through the same public-address and image-format checks as a manually supplied cover URL.
