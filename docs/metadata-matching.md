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
