"""Success payload contracts for API operations that return lightweight records.

Optional TypedDict keys preserve the existing distinction between absent values
and explicit JSON nulls during FastAPI response validation and serialization.
"""

from datetime import datetime
from typing import Any, Literal
from typing_extensions import NotRequired, TypedDict

from .services.library_health import LibraryFileIssue
from .services.processing_queue import WorkerHealth


class StatusResponse(TypedDict):
    status: str


class DatabaseHealth(StatusResponse):
    database: str


class MessageResponse(TypedDict):
    message: str


class ReprocessStatus(TypedDict):
    running: bool
    job_id: NotRequired[int]
    status: NotRequired[str]
    total: NotRequired[int]
    processed: NotRequired[int]
    error: NotRequired[str]


class UniverseSummary(TypedDict):
    id: int
    name: str


class UniverseMembershipResult(TypedDict):
    universe_id: int | None
    universe_name: str | None


class WebCheck(TypedDict):
    book_id: int
    entry_type: str
    timestamp: datetime | None
    previous_chapter_count: int | None
    new_chapter_count: int | None
    words_added: int | None


class SeriesRenamed(TypedDict):
    updated: int
    old_name: str
    new_name: str


class SeriesMerged(TypedDict):
    merged: int
    source: str
    target: str


class SeriesReordered(TypedDict):
    updated: int
    series: str


class BookCount(TypedDict):
    total: int


class PurgedBooks(TypedDict):
    purged: int


class SeriesDetected(TypedDict):
    updated: int
    series_detected: list[str]


class SchedulerTriggered(MessageResponse):
    processing_job_id: int


class OkResponse(TypedDict):
    ok: bool


class LogEntry(TypedDict):
    timestamp: str
    level: str
    logger: str
    message: str
    exception: NotRequired[str]
    request_id: NotRequired[str]
    job_id: NotRequired[int]


class FileSize(TypedDict):
    path: str
    size_bytes: int


class LibraryValidation(TypedDict):
    total_books: int
    issues_count: int
    issues: list[LibraryFileIssue]


class StorageCleanup(TypedDict):
    dry_run: bool
    files: list[FileSize]
    books: list[LibraryFileIssue]
    total_bytes: int
    skipped_reason: NotRequired[str]


class BookRemovalPreview(TypedDict):
    id: int
    title: str | None
    author: str | None
    files: list[FileSize]
    log_entries: int


class RemoveAllBooks(TypedDict):
    dry_run: bool
    book_count: int
    file_count: int
    total_bytes: int
    log_count: int
    books: list[BookRemovalPreview]
    paths: list[str]
    recoverable: bool
    retention_days: int


class QueuedImports(TypedDict):
    queued_count: int
    skipped_count: int


class RebuiltImports(QueuedImports):
    pipeline_version: int


class PipelineQueued(TypedDict):
    status: str | None
    queued: bool
    stop_after_phase: NotRequired[str]
    batch_limit: NotRequired[int]


class PipelinePaused(TypedDict):
    status: str | None
    pause_requested: bool


class SentenceQueued(PipelineQueued):
    sentence_id: int


class ChapterPreviewQueued(PipelineQueued):
    chapter_id: NotRequired[int]


class TTSProviderChanged(TypedDict):
    provider: str
    scope: Literal["series", "book"]
    affected_book_ids: list[int]


class RosterShared(TypedDict):
    series: str
    profiles: int
    books_updated: int


class EndpointProbe(TypedDict):
    endpoint_id: str | None
    endpoint: str | None
    priority: int
    provider: str | None
    model: str | None
    status: Literal["ready", "error"]
    duration_ms: float
    error: str | None
    # Upstream health/model JSON is intentionally extensible.
    response: NotRequired[dict[str, Any]]
    audio_bytes: NotRequired[int]
    service_status: NotRequired[str | None]
    device: NotRequired[str | None]
    loaded_model: NotRequired[str | None]


class EndpointTest(TypedDict):
    status: Literal["ready", "partial", "failed"]
    provider: str | None
    model: str | None
    endpoint: NotRequired[str | None]
    results: NotRequired[list[EndpointProbe]]


class LLMTest(EndpointTest):
    response: dict[str, Any] | str | None


class TTSTest(EndpointTest):
    audio_bytes: int


class TranscriptionTest(EndpointTest):
    device: str | None


class LifecycleState(TypedDict):
    value: str | None
    label: str


class LifecycleDefinition(TypedDict):
    name: str
    states: list[LifecycleState]
    active_states: list[str | None]
    terminal_states: list[str | None]
    failure_states: list[str | None]
    retryable_states: list[str | None]
    recovery: dict[str, str | None]
    groups: dict[str, list[str | None]]


class StorageHealth(TypedDict):
    status: str
    writable: bool
    total_bytes: NotRequired[int]
    free_bytes: NotRequired[int]
    percent_free: NotRequired[float]
    minimum_free_bytes: NotRequired[int]


class ProviderHealth(TypedDict):
    capability: str
    status: str
    configured_endpoints: int


class HealthReport(TypedDict):
    status: str
    generated_at: str
    liveness: StatusResponse
    database: StatusResponse
    workers: WorkerHealth
    storage: StorageHealth
    providers: list[ProviderHealth]


class JobMetricSummary(TypedDict):
    total: int
    queued: int
    running: int
    completed: int
    failed: int
    canceled: int
    retries: int
    average_queue_delay_ms: float | None
    average_duration_ms: float | None


class JobMetrics(TypedDict):
    generated_at: str
    window_hours: int
    aggregate: JobMetricSummary
    by_job_type: dict[str, JobMetricSummary]


def media_responses(media_type: str, *, binary: bool = True) -> dict[int | str, dict[str, Any]]:
    """Describe native response bodies without advertising an empty JSON object."""
    schema = {"type": "string", **({"format": "binary"} if binary else {})}
    return {200: {"content": {media_type: {"schema": schema}}}}
