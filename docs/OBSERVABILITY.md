# Observability

Story Manager includes local diagnostics designed for a small self-hosted installation. No external monitoring service is required.

## Health endpoints

- `GET /health/live` checks only that the API process can respond.
- `GET /health/ready` checks the database, processing workers, and writable storage capacity. It returns `503` when a required dependency is unavailable.
- `GET /api/observability/health` returns the complete operator view, including optional LLM, text-to-speech, and transcription configuration status.
- `GET /health` remains available for compatibility with existing database-only health checks.

The storage check is considered unavailable below 5 percent free space or 1 GiB free, whichever is reached first. Set `STORY_MANAGER_MIN_FREE_BYTES` to change the byte threshold.

## Correlation and logs

Every API response includes `X-Request-ID`. A caller may provide a safe identifier with the same header; otherwise Story Manager generates one. Processing jobs retain the request ID that created them, so their API details and worker logs can be correlated later.

Application logs are stored as redacted JSON lines in `logs/story-manager.jsonl` by default. They rotate at 5 MiB with three backups and survive normal restarts. These settings are configurable:

- `STORY_MANAGER_LOG_DIR`
- `STORY_MANAGER_LOG_MAX_BYTES`
- `STORY_MANAGER_LOG_BACKUP_COUNT`
- `LOG_FORMAT=json` for structured container output

The Logs screen and `GET /api/logs` read this persisted history. Successful high-frequency polling requests are hidden by default so they do not overwhelm useful records; pass `include_polling=true` to include them. The API also accepts `level`, `request_id`, `job_id`, and `limit` filters.

## Job metrics

`GET /api/observability/job-metrics?window_hours=24` groups processing outcomes by job type. It reports queue delay, execution duration, retries, failures, and cancellations. The window can range from one hour to 90 days.

## Diagnostic bundle

The Logs screen can download a ZIP bundle containing health, job metrics, recent redacted logs, and an explicit allowlist of non-secret configuration. The export never includes environment dumps, API keys, session secrets, library files, book contents, or generated audio.

Redaction is defense in depth: application code should still avoid logging credentials, request bodies, book contents, or audio data in the first place.
