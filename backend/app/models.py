from pydantic import JsonValue
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Integer,
    String,
    DateTime,
    Float,
    ForeignKey,
    Enum,
    JSON,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column
from sqlalchemy.sql import func
from .database import Base
from .lifecycle import (
    ALIGNMENT_METHOD,
    AUDIOBOOK_PIPELINE,
    AUDIOBOOK_PUBLICATION,
    CHAPTER_GENERATION,
    CHAPTER_PREVIEW,
    IMPORTED_AUDIOBOOK,
    METADATA_JOB,
    PROCESSING_JOB,
    SENTENCE,
    UPDATE_TASK,
    WEB_IMPORT,
    WEB_REFRESH,
    ChapterGenerationStatus,
    ImportedAudiobookStatus,
    MetadataJobStatus,
    ProcessingJobStatus,
    SentenceStatus,
    StateMachine,
    UpdateTaskStatus,
)
import enum
from uuid import uuid4


def _state_check(column_name: str, machine: StateMachine, name: str) -> CheckConstraint:
    values = ", ".join(f"'{value}'" for value in sorted(value for value in machine.states if value is not None))
    return CheckConstraint(f"{column_name} IN ({values})", name=name)


class SourceType(enum.Enum):
    web = "web"
    epub = "epub"
    audiobook = "audiobook"


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        _state_check("download_status", WEB_IMPORT, "ck_books_download_status"),
        _state_check("refresh_status", WEB_REFRESH, "ck_books_refresh_status"),
        _state_check("audiobook_pipeline_status", AUDIOBOOK_PIPELINE, "ck_books_audiobook_pipeline_status"),
        _state_check(
            "audiobook_publication_state",
            AUDIOBOOK_PUBLICATION,
            "ck_books_audiobook_publication_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str | None] = mapped_column(String, index=True)
    author: Mapped[str | None] = mapped_column(String, index=True)
    series: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    series_index: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    # Used for standalone books. Series membership takes precedence when set.
    universe_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("universes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    genre_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    source_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    user_genre_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Denormalized searchable text avoids repeatedly casting JSON tag arrays in
    # every catalog query. A mapper hook below keeps it in sync.
    catalog_search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_remote_ids: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_sync_source: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False, default=SourceType.epub)
    immutable_path: Mapped[str | None] = mapped_column(String, unique=True)
    current_path: Mapped[str | None] = mapped_column(String, unique=True)
    removed_chapters: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    content_selectors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    master_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Storing the cover as a path to a file. The file itself can be extracted from the EPUB.
    cover_path: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    download_status: Mapped[str | None] = mapped_column(String, nullable=True)
    # Tracks the lifecycle of a "refresh from source" job independently from the
    # initial download state. Values: None (idle), "queued", "processing", "error".
    refresh_status: Mapped[str | None] = mapped_column(String, nullable=True)
    # Audiobook generation is opt-in per book. Keep it disabled by default so
    # normal library books do not show or run the heavier pipeline.
    audiobook_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Audiobook pipeline state. Values: None (idle), "ingesting", "roster_gen",
    # "diarizing", "audio_gen", "assembling", "complete", "error", "paused".
    audiobook_pipeline_status: Mapped[str | None] = mapped_column(String, nullable=True)
    # Cooperative control state is persisted so a restart cannot turn a
    # single-stage/debug run into an unattended full-book run.
    audiobook_stop_after_phase: Mapped[str | None] = mapped_column(String, nullable=True)
    audiobook_pause_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    audiobook_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    audiobook_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    audiobook_progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    audiobook_progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    audiobook_progress_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    audiobook_pipeline_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audiobook_pipeline_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audiobook_batch_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audiobook_llm_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Once selected, every TTS request for this book is restricted to this
    # provider. Named-series books share the same lock.
    audiobook_tts_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    # Reader-facing audiobook publication state. These fields describe the
    # last atomically published modular rendition, independently of work that
    # may still be in progress in the generation pipeline.
    audiobook_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    audiobook_source_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audiobook_text_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audiobook_pending_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audiobook_publication_state: Mapped[str | None] = mapped_column(String, nullable=True)
    audiobook_text_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    audiobook_text_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    audiobook_text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    audiobook_publication_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    content_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


def _catalog_search_text(book: Book) -> str:
    values = [book.title, book.author, book.series]
    tags = [*(book.genre_tags or []), *(book.user_genre_tags or [])]
    parts = [str(value).strip().casefold() for value in values if value and str(value).strip()]
    parts.extend(f"tag:{str(tag).strip().casefold()}" for tag in tags if tag and str(tag).strip())
    return "\n".join(parts) + "\n"


@event.listens_for(Book, "before_insert")
@event.listens_for(Book, "before_update")
def _sync_catalog_search_text(_mapper: Mapper[Book], _connection: Connection, book: Book) -> None:
    book.catalog_search_text = _catalog_search_text(book)


class Universe(Base):
    __tablename__ = "universes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)


class UniverseSeries(Base):
    __tablename__ = "universe_series"

    series_key: Mapped[str] = mapped_column(String, primary_key=True)
    universe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("universes.id", ondelete="CASCADE"), nullable=False, index=True
    )


class BookRevision(Base):
    """A restorable snapshot taken before a user-visible book change."""

    __tablename__ = "book_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    __table_args__ = (Index("ix_book_revisions_book_created", "book_id", "created_at"),)


class ProcessingJob(Base):
    """Durable ledger entry for user-visible background work."""

    __tablename__ = "processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ProcessingJobStatus.QUEUED.value,
        server_default=ProcessingJobStatus.QUEUED.value,
        index=True,
    )
    resource_lane: Mapped[str] = mapped_column(
        String, nullable=False, default="maintenance", server_default="maintenance", index=True
    )
    book_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=True, index=True)
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, default=lambda: uuid4().hex[:12], index=True)
    payload: Mapped[dict[str, JsonValue] | None] = mapped_column(JSON, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    progress_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    __table_args__ = (
        _state_check("status", PROCESSING_JOB, "ck_processing_jobs_status"),
        Index(
            "uq_processing_jobs_active_dedupe",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
            sqlite_where=text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
        ),
    )


class SeriesMetadata(Base):
    __tablename__ = "series_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    series_name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    user_genre_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class BookLog(Base):
    __tablename__ = "book_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    entry_type: Mapped[str] = mapped_column(String, nullable=False)  # e.g., "added", "updated"
    previous_chapter_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_chapter_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    words_added: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UpdateTask(Base):
    __tablename__ = "update_tasks"
    __table_args__ = (_state_check("status", UPDATE_TASK, "ck_update_tasks_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    total_books: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_books: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default=UpdateTaskStatus.RUNNING.value)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MetadataSyncJob(Base):
    __tablename__ = "metadata_sync_jobs"
    __table_args__ = (_state_check("status", METADATA_JOB, "ck_metadata_sync_jobs_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    trigger: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default=MetadataJobStatus.QUEUED.value)
    total_books: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_books: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_books: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposed_books: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applied_books: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BookMetadataMatch(Base):
    __tablename__ = "book_metadata_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    match_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    remote_title: Mapped[str | None] = mapped_column(String, nullable=True)
    remote_author: Mapped[str | None] = mapped_column(String, nullable=True)
    remote_url: Mapped[str | None] = mapped_column(String, nullable=True)
    remote_ids: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    remote_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    proposed_genre_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    possible_missing_series_books: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    match_issues: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class MetadataProposal(Base):
    __tablename__ = "metadata_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    match_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("book_metadata_matches.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    proposed_genre_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    possible_missing_series_books: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CleaningConfig(Base):
    __tablename__ = "cleaning_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    url_pattern: Mapped[str] = mapped_column(String, nullable=False)
    chapter_selectors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    content_selectors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class SchedulerSettings(Base):
    __tablename__ = "scheduler_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    web_novel_schedule_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    web_novel_schedule_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    web_novel_schedule_timezone: Mapped[str | None] = mapped_column(String, nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    token_prefix: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AudiobookSettings(Base):
    __tablename__ = "audiobook_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    llm_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_model: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_default_voice: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_max_block_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=500, server_default="500")
    tts_voice_similarity_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.45, server_default="0.45")
    tts_quality_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    transcription_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    transcription_api_key: Mapped[str | None] = mapped_column(String, nullable=True)
    transcription_base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    transcription_model: Mapped[str | None] = mapped_column(String, nullable=True)
    transcription_language: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_endpoints: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    tts_endpoints: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    transcription_endpoints: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    roster_prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    diarization_prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)


class AiEndpointRequestMetric(Base):
    """One completed attempt against a configured AI endpoint."""

    __tablename__ = "ai_endpoint_request_metrics"
    __table_args__ = (
        Index(
            "ix_ai_endpoint_metrics_settings_capability_endpoint_created",
            "settings_id",
            "capability",
            "endpoint_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    settings_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("audiobook_settings.id", ondelete="CASCADE"),
        nullable=False,
    )
    capability: Mapped[str] = mapped_column(String, nullable=False)
    endpoint_id: Mapped[str] = mapped_column(String, nullable=False)
    endpoint_name: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AudiobookChapter(Base):
    __tablename__ = "audiobook_chapters"
    __table_args__ = (
        UniqueConstraint("book_id", "stable_chapter_key", name="uq_audiobook_chapter_stable_key"),
        Index("ix_audiobook_chapters_book_logical_key", "book_id", "logical_chapter_key"),
        _state_check("preview_status", CHAPTER_PREVIEW, "ck_audiobook_chapters_preview_status"),
        _state_check("generation_state", CHAPTER_GENERATION, "ck_audiobook_chapters_generation_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    smil_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    needs_reassembly: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Manual chapter previews are independent of the full-book pipeline.
    # Values: None, queued, generating, ready, error.
    preview_status: Mapped[str | None] = mapped_column(String, nullable=True)
    preview_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stable_chapter_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # Physical EPUB spine items may be fragments of one reader-visible chapter.
    # Group them without rewriting the user's EPUB or losing per-file anchors.
    logical_chapter_key: Mapped[str | None] = mapped_column(String, nullable=True)
    logical_part_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_href: Mapped[str | None] = mapped_column(String, nullable=True)
    source_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    spine_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_state: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ChapterGenerationStatus.PENDING.value,
        server_default=ChapterGenerationStatus.PENDING.value,
    )
    audio_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reader_audio_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    reader_smil_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    audio_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    smil_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    smil_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class AudiobookSeriesCharacter(Base):
    __tablename__ = "audiobook_series_characters"
    __table_args__ = (UniqueConstraint("series_name", "canonical_name", name="uq_audiobook_series_character"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    series_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_prompt: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_voice_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_voice_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_narrator: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    aliases: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class AudiobookCharacter(Base):
    __tablename__ = "audiobook_characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    series_character_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("audiobook_series_characters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_prompt: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_voice_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_voice_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    tts_seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_narrator: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    aliases: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class AudiobookSentence(Base):
    __tablename__ = "audiobook_sentences"
    __table_args__ = (_state_check("status", SENTENCE, "ck_audiobook_sentences_status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    chapter_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("audiobook_chapters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    character_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("audiobook_characters.id", ondelete="SET NULL"), nullable=True
    )
    html_element_id: Mapped[str] = mapped_column(String, nullable=False)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    tagged_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    audio_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    voice_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    tts_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speaker_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Values and transitions are defined by lifecycle.SENTENCE.
    status: Mapped[str] = mapped_column(String, nullable=False, server_default=SentenceStatus.PENDING_DIARIZATION.value)


class ImportedAudiobook(Base):
    """A human-narrated audiobook edition attached to a library book."""

    __tablename__ = "imported_audiobooks"
    __table_args__ = (
        _state_check("status", IMPORTED_AUDIOBOOK, "ck_imported_audiobooks_status"),
        _state_check("alignment_method", ALIGNMENT_METHOD, "ck_imported_audiobooks_alignment_method"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False, default="upload", server_default="upload")
    asin: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # Values and transitions are defined by lifecycle.IMPORTED_AUDIOBOOK.
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=ImportedAudiobookStatus.QUEUED.value,
        server_default=ImportedAudiobookStatus.QUEUED.value,
        index=True,
    )
    alignment_method: Mapped[str | None] = mapped_column(String, nullable=True)
    original_filenames: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    progress_detail: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    alignment_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_manifest_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_manifest_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    derived_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    derived_format_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Version of the complete human-audiobook rebuild pipeline last applied.
    pipeline_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class ImportedAudiobookTrack(Base):
    """A chapter-like time range in an imported audiobook source file."""

    __tablename__ = "imported_audiobook_tracks"
    __table_args__ = (UniqueConstraint("imported_audiobook_id", "sequence_order", name="uq_imported_audiobook_track_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    imported_audiobook_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("imported_audiobooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matched_chapter_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("audiobook_chapters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # ``None`` means legacy/unknown and is preserved conservatively by rebuilds.
    match_method: Mapped[str | None] = mapped_column(String, nullable=True)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    audio_file_path: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    source_audio_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_clip_begin_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_clip_end_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    source_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transcript_file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    alignment_score: Mapped[float | None] = mapped_column(Float, nullable=True)


class ImportedAudiobookCue(Base):
    """Sentence-level media-overlay timing for an imported track."""

    __tablename__ = "imported_audiobook_cues"
    __table_args__ = (UniqueConstraint("track_id", "sentence_id", name="uq_imported_audiobook_cue_sentence"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    track_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("imported_audiobook_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sentence_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("audiobook_sentences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False)
    clip_begin_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    clip_end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str] = mapped_column(String, nullable=False, default="estimated", server_default="estimated")
