# Story Manager Improvement Roadmap

This roadmap captures the next major product and technical improvements for Story Manager. Work is intentionally ordered so that user-facing consolidation comes first, followed by the technical changes needed to support larger libraries and more reliable background processing.

## Delivery rules

- Complete one roadmap item per pull request.
- Keep each pull request independently deployable and reversible.
- Include focused unit or integration tests and update end-to-end coverage when a user workflow changes.
- Do not combine opportunistic refactors with a roadmap item unless they are required to deliver it safely.
- Mark an item complete here only after its pull request has been merged.

## Sequence

1. [Needs Attention dashboard](#1-needs-attention-dashboard)
2. [Simplified navigation](#2-simplified-navigation)
3. [Unified import workflow](#3-unified-import-workflow)
4. [Recoverable destructive changes](#4-recoverable-destructive-changes)
5. [Server-side catalog pagination and filtering](#5-server-side-catalog-pagination-and-filtering)
6. [Consolidated background execution](#6-consolidated-background-execution)
7. [Centralized state-machine definitions](#7-centralized-state-machine-definitions)
8. [Stronger observability](#8-stronger-observability)
9. [Backup and disaster recovery](#9-backup-and-disaster-recovery)

## 1. Needs Attention dashboard

**Status:** Complete

Give users one actionable view of problems and pending decisions across the library. The first version should summarize failed processing jobs, failed web refreshes, stale audiobooks, open metadata proposals, broken library files, and missing covers.

The dashboard should favor resolution over raw diagnostics. Every category should explain why it matters and link to the page where the user can act. A healthy library should have a clear empty state rather than a blank screen.

### Acceptance criteria

- A single API response aggregates attention counts and representative recent items.
- The UI displays each supported category with a count, explanation, and action link.
- Broken paths and missing covers reuse one library-health implementation rather than duplicating storage-audit rules.
- Failed jobs and refreshes identify the affected book when possible.
- A failed job clears automatically when a newer equivalent operation succeeds.
- The dashboard refreshes while relevant background work is active.
- Backend and frontend tests cover populated and healthy states.

## 2. Simplified navigation

**Status:** Complete

Replace the current tool-oriented top-level navigation with three user-oriented destinations: **Library**, **Activity**, and **Settings**. The Needs Attention dashboard should become the default overview within this structure.

Activity will own processing jobs, failures, scheduled runs, and history. Settings will own cleaning rules, reader access, audio and AI providers, storage utilities, and application logs. Existing deep links should redirect or continue to resolve.

### Acceptance criteria

- The primary navigation contains only Library, Activity, and Settings.
- Existing pages remain reachable and are grouped under the appropriate destination.
- Active-job and attention counts remain visible from anywhere in the app.
- Browser back/forward behavior and direct links work for every nested section.
- Mobile and keyboard navigation are covered by tests.

## 3. Unified import workflow

**Status:** Complete

Create one guided **Add to library** workflow for EPUB files, ZIP archives, folders, web-novel URLs, human audiobook files, and Libation backups. The workflow should separate selection, inspection, conflict resolution, execution, and results.

Preflight inspection should show detected metadata, likely duplicates, audiobook-to-book matches, applicable cleaning rules, and any unsupported input before work begins.

### Acceptance criteria

- All current import entry points are available through one workflow.
- Inputs are inspected before durable work is queued.
- Duplicate books and ambiguous audiobook matches require an explicit decision.
- The results view distinguishes succeeded, skipped, queued, and failed items.
- Long-running work remains visible after leaving or reloading the page.
- Existing focused import APIs remain backward compatible during migration.

## 4. Recoverable destructive changes

**Status:** Complete

Make deletion and content-changing operations recoverable. Build on the existing immutable EPUB copy to support restoring original content, reviewing cleaning changes, and recovering accidentally deleted records where practical.

The design should cover book deletion, bulk deletion, chapter removal, cleaning-rule application, series changes, and metadata replacement. Recovery guarantees must be explicit; a recycle bin should not imply that externally deleted source files can always be restored.

### Acceptance criteria

- Destructive actions use an application confirmation experience that states exactly what will change.
- Eligible deleted books enter a recycle bin for a configurable retention period.
- Users can restore the original EPUB after cleaning or chapter edits.
- Metadata and series changes record enough history to explain or revert them.
- Permanent deletion remains available and clearly distinguished from recoverable removal.
- Cleanup jobs do not remove files still required for recovery.

## 5. Server-side catalog pagination and filtering

**Status:** Complete

Stop loading the entire library for every catalog view. Introduce cursor-based pagination, server-side filtering, stable sorting, and aggregate facet counts while preserving the current series-oriented presentation.

Search should use PostgreSQL indexes suited to title, author, series, and tag lookup rather than casting JSON fields to text for every query.

### Acceptance criteria

- Catalog responses are paginated and include a continuation cursor.
- Search, sorting, and all visible filters execute on the server.
- Series, standalone, web, audiobook, status, and genre counts remain accurate without loading every book.
- Scrolling does not duplicate or omit books when records change between requests.
- Query plans and a representative large-library benchmark are documented.
- Reader API behavior remains backward compatible.

## 6. Consolidated background execution

**Status:** Complete

Complete the transition from specialized in-memory queues to the durable processing-job ledger. The API process should enqueue work, while a unified worker claims and executes jobs using explicit resource lanes.

The first deployment can retain a single-container experience, but job ownership must no longer depend on application-local queue memory.

### Acceptance criteria

- All user-visible background operations are represented by processing jobs.
- Workers claim jobs atomically from PostgreSQL with leases and heartbeats.
- Abandoned jobs are recoverable after crashes or restarts.
- Retry limits, backoff, cancellation, idempotency, and deduplication are defined consistently.
- CPU, maintenance, LLM, TTS, and transcription concurrency can be configured independently.
- The existing single-container deployment remains supported.

## 7. Centralized state-machine definitions

**Status:** Complete

Replace scattered lifecycle strings and implicit transitions with centralized state definitions for processing jobs, web imports and refreshes, metadata jobs, generated audiobooks, imported audiobooks, alignment, and publication.

The lifecycle vocabulary and recovery contract are documented in [Application lifecycles](LIFECYCLES.md).

State machines should define valid transitions, terminal states, retry behavior, and how parent and child operations interact. Database constraints should reject impossible values.

### Acceptance criteria

- Each lifecycle has one authoritative state definition.
- Services transition state through shared helpers rather than assigning strings directly.
- Alembic migrations add safe database constraints for existing populated databases.
- Invalid transitions fail with actionable errors and are tested.
- Frontend labels and status groupings derive from the same documented vocabulary.
- Recovery behavior for every non-terminal state is documented.

## 8. Stronger observability

**Status:** Complete

Make failures diagnosable without reading raw container output. Connect request IDs to log records, expose worker and dependency health, measure job behavior, and provide a user-downloadable diagnostic bundle with secrets removed.

Observability should remain useful for a small self-hosted deployment and should not require an external monitoring stack.

### Acceptance criteria

- Request IDs appear in API responses, structured logs, and related failure details.
- Health endpoints distinguish liveness, database readiness, worker availability, storage capacity, and optional provider status.
- Job duration, queue delay, retry, cancellation, and failure metrics are available by job type.
- Logs required for recent diagnostics survive ordinary application restarts.
- Users can download a redacted diagnostic bundle from the UI.
- Metrics and logs never expose API keys, session secrets, book contents, or generated audio.

## 9. Backup and disaster recovery

**Status:** In progress

Protect a self-hosted library from database loss, disk failure, and failed host migrations. Backups should be
portable, independently verifiable, and stored outside the library tree so one archive never includes another.
Restores must be an explicit offline operation rather than a browser action against a running service.

### Acceptance criteria

- Users can queue a complete database-and-library backup from Library Tools and follow its durable job progress.
- New writes pause during snapshot creation, and a backup refuses to run alongside active processing work.
- Every archive contains a versioned manifest, full file inventory, sizes, and SHA-256 checksums.
- An archive is checksum-verified before it appears in backup history or becomes downloadable.
- Backup history enforces a configurable retention count, with zero available for manual retention.
- Existing backups can be downloaded, re-verified, and deliberately deleted from the UI.
- The bundled offline restore command validates the archive before replacing data and rolls library files back if
  PostgreSQL restore fails.
- Docker Compose persists backups separately from both the library and PostgreSQL data directories.
- Tests cover archive tampering, unsafe paths, API behavior, successful restore, and restore rollback.
