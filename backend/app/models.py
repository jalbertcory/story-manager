from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
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

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    author = Column(String, index=True)
    series = Column(String, nullable=True, index=True)
    series_index = Column(Numeric(6, 2), nullable=True)
    genre_tags = Column(JSON, nullable=True)
    source_tags = Column(JSON, nullable=True)
    user_genre_tags = Column(JSON, nullable=True)
    # Denormalized searchable text avoids repeatedly casting JSON tag arrays in
    # every catalog query. A mapper hook below keeps it in sync.
    catalog_search_text = Column(Text, nullable=True)
    metadata_remote_ids = Column(JSON, nullable=True)
    metadata_details = Column(JSON, nullable=True)
    metadata_sync_source = Column(String, nullable=True)
    metadata_synced_at = Column(DateTime(timezone=True), nullable=True)
    source_url = Column(String, unique=True, index=True, nullable=True)
    source_type = Column(Enum(SourceType), nullable=False, default=SourceType.epub)
    immutable_path = Column(String, unique=True)
    current_path = Column(String, unique=True)
    removed_chapters = Column(JSON, nullable=True)
    content_selectors = Column(JSON, nullable=True)
    master_word_count = Column(Integer, nullable=True)
    current_word_count = Column(Integer, nullable=True)
    # Storing the cover as a path to a file. The file itself can be extracted from the EPUB.
    cover_path = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    download_status = Column(String, nullable=True)
    # Tracks the lifecycle of a "refresh from source" job independently from the
    # initial download state. Values: None (idle), "queued", "processing", "error".
    refresh_status = Column(String, nullable=True)
    # Audiobook generation is opt-in per book. Keep it disabled by default so
    # normal library books do not show or run the heavier pipeline.
    audiobook_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    # Audiobook pipeline state. Values: None (idle), "ingesting", "roster_gen",
    # "diarizing", "audio_gen", "assembling", "complete", "error", "paused".
    audiobook_pipeline_status = Column(String, nullable=True)
    # Cooperative control state is persisted so a restart cannot turn a
    # single-stage/debug run into an unattended full-book run.
    audiobook_stop_after_phase = Column(String, nullable=True)
    audiobook_pause_requested = Column(Boolean, nullable=False, default=False, server_default="false")
    audiobook_last_error = Column(Text, nullable=True)
    audiobook_summary = Column(Text, nullable=True)
    audiobook_progress_current = Column(Integer, nullable=False, default=0, server_default="0")
    audiobook_progress_total = Column(Integer, nullable=False, default=0, server_default="0")
    audiobook_progress_detail = Column(String, nullable=True)
    audiobook_pipeline_started_at = Column(DateTime(timezone=True), nullable=True)
    audiobook_pipeline_updated_at = Column(DateTime(timezone=True), nullable=True)
    audiobook_batch_limit = Column(Integer, nullable=True)
    audiobook_llm_requests = Column(Integer, nullable=False, default=0, server_default="0")
    # Once selected, every TTS request for this book is restricted to this
    # provider. Named-series books share the same lock.
    audiobook_tts_provider = Column(String, nullable=True)
    # Reader-facing audiobook publication state. These fields describe the
    # last atomically published modular rendition, independently of work that
    # may still be in progress in the generation pipeline.
    audiobook_revision = Column(Integer, nullable=False, default=0, server_default="0")
    audiobook_source_content_version = Column(Integer, nullable=True)
    audiobook_text_content_version = Column(Integer, nullable=True)
    audiobook_pending_content_version = Column(Integer, nullable=True)
    audiobook_publication_state = Column(String, nullable=True)
    audiobook_text_file_path = Column(String, nullable=True)
    audiobook_text_size_bytes = Column(BigInteger, nullable=True)
    audiobook_text_sha256 = Column(String(64), nullable=True)
    audiobook_publication_error = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    content_updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    content_version = Column(Integer, nullable=False, server_default="1")
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    purge_after = Column(DateTime(timezone=True), nullable=True, index=True)


def _catalog_search_text(book: Book) -> str:
    values = [book.title, book.author, book.series]
    tags = [*(book.genre_tags or []), *(book.user_genre_tags or [])]
    parts = [str(value).strip().casefold() for value in values if value and str(value).strip()]
    parts.extend(f"tag:{str(tag).strip().casefold()}" for tag in tags if tag and str(tag).strip())
    return "\n".join(parts) + "\n"


@event.listens_for(Book, "before_insert")
@event.listens_for(Book, "before_update")
def _sync_catalog_search_text(_mapper, _connection, book: Book) -> None:
    book.catalog_search_text = _catalog_search_text(book)


class BookRevision(Base):
    """A restorable snapshot taken before a user-visible book change."""

    __tablename__ = "book_revisions"

    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String, nullable=False)
    summary = Column(String, nullable=False)
    snapshot = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    __table_args__ = (Index("ix_book_revisions_book_created", "book_id", "created_at"),)


class ProcessingJob(Base):
    """Durable ledger entry for user-visible background work."""

    __tablename__ = "processing_jobs"

    id = Column(Integer, primary_key=True)
    job_type = Column(String, nullable=False, index=True)
    status = Column(
        String,
        nullable=False,
        default=ProcessingJobStatus.QUEUED.value,
        server_default=ProcessingJobStatus.QUEUED.value,
        index=True,
    )
    resource_lane = Column(String, nullable=False, default="maintenance", server_default="maintenance", index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=True, index=True)
    target_type = Column(String, nullable=True)
    target_id = Column(Integer, nullable=True)
    target_content_version = Column(Integer, nullable=True)
    parent_job_id = Column(Integer, ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True)
    request_id = Column(String(64), nullable=False, default=lambda: uuid4().hex[:12], index=True)
    payload = Column(JSON, nullable=True)
    dedupe_key = Column(String, nullable=True, index=True)
    progress_current = Column(Integer, nullable=False, default=0, server_default="0")
    progress_total = Column(Integer, nullable=False, default=0, server_default="0")
    progress_detail = Column(String, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    available_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    lease_owner = Column(String, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False, server_default="false")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

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

    id = Column(Integer, primary_key=True, index=True)
    series_name = Column(String, unique=True, nullable=False, index=True)
    user_genre_tags = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class BookLog(Base):
    __tablename__ = "book_logs"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    entry_type = Column(String, nullable=False)  # e.g., "added", "updated"
    previous_chapter_count = Column(Integer, nullable=True)
    new_chapter_count = Column(Integer, nullable=True)
    words_added = Column(Integer, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class UpdateTask(Base):
    __tablename__ = "update_tasks"
    __table_args__ = (_state_check("status", UPDATE_TASK, "ck_update_tasks_status"),)

    id = Column(Integer, primary_key=True, index=True)
    total_books = Column(Integer, nullable=False)
    completed_books = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default=UpdateTaskStatus.RUNNING.value)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class MetadataSyncJob(Base):
    __tablename__ = "metadata_sync_jobs"
    __table_args__ = (_state_check("status", METADATA_JOB, "ck_metadata_sync_jobs_status"),)

    id = Column(Integer, primary_key=True, index=True)
    trigger = Column(String, nullable=False)
    status = Column(String, nullable=False, default=MetadataJobStatus.QUEUED.value)
    total_books = Column(Integer, nullable=False, default=0)
    processed_books = Column(Integer, nullable=False, default=0)
    matched_books = Column(Integer, nullable=False, default=0)
    proposed_books = Column(Integer, nullable=False, default=0)
    applied_books = Column(Integer, nullable=False, default=0)
    scope = Column(JSON, nullable=True)
    error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class BookMetadataMatch(Base):
    __tablename__ = "book_metadata_matches"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, nullable=False, default="pending")
    source = Column(String, nullable=True)
    match_confidence = Column(Numeric(5, 4), nullable=True)
    remote_title = Column(String, nullable=True)
    remote_author = Column(String, nullable=True)
    remote_url = Column(String, nullable=True)
    remote_ids = Column(JSON, nullable=True)
    remote_metadata = Column(JSON, nullable=True)
    proposed_genre_tags = Column(JSON, nullable=True)
    possible_missing_series_books = Column(JSON, nullable=True)
    match_issues = Column(JSON, nullable=True)
    note = Column(Text, nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class MetadataProposal(Base):
    __tablename__ = "metadata_proposals"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    match_id = Column(Integer, ForeignKey("book_metadata_matches.id", ondelete="SET NULL"), nullable=True)
    status = Column(String, nullable=False, default="open")
    proposed_genre_tags = Column(JSON, nullable=True)
    possible_missing_series_books = Column(JSON, nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)


class CleaningConfig(Base):
    __tablename__ = "cleaning_configs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    url_pattern = Column(String, nullable=False)
    chapter_selectors = Column(JSON, nullable=True)
    content_selectors = Column(JSON, nullable=True)


class SchedulerSettings(Base):
    __tablename__ = "scheduler_settings"

    id = Column(Integer, primary_key=True, index=True)
    web_novel_schedule_hour = Column(Integer, nullable=True)
    web_novel_schedule_minute = Column(Integer, nullable=True)
    web_novel_schedule_timezone = Column(String, nullable=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, nullable=False)
    token_prefix = Column(String, unique=True, nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)


class AudiobookSettings(Base):
    __tablename__ = "audiobook_settings"

    id = Column(Integer, primary_key=True, index=True)
    llm_provider = Column(String, nullable=True)
    llm_api_key = Column(String, nullable=True)
    llm_base_url = Column(String, nullable=True)
    llm_model = Column(String, nullable=True)
    tts_provider = Column(String, nullable=True)
    tts_api_key = Column(String, nullable=True)
    tts_base_url = Column(String, nullable=True)
    tts_model = Column(String, nullable=True)
    tts_default_voice = Column(String, nullable=True)
    tts_max_block_chars = Column(Integer, nullable=False, default=500, server_default="500")
    tts_voice_similarity_threshold = Column(Float, nullable=False, default=0.45, server_default="0.45")
    tts_quality_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    transcription_provider = Column(String, nullable=True)
    transcription_api_key = Column(String, nullable=True)
    transcription_base_url = Column(String, nullable=True)
    transcription_model = Column(String, nullable=True)
    transcription_language = Column(String, nullable=True)
    llm_endpoints = Column(JSON, nullable=True)
    tts_endpoints = Column(JSON, nullable=True)
    transcription_endpoints = Column(JSON, nullable=True)
    roster_prompt_template = Column(Text, nullable=True)
    diarization_prompt_template = Column(Text, nullable=True)


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

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    settings_id = Column(
        Integer,
        ForeignKey("audiobook_settings.id", ondelete="CASCADE"),
        nullable=False,
    )
    capability = Column(String, nullable=False)
    endpoint_id = Column(String, nullable=False)
    endpoint_name = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=True)
    success = Column(Boolean, nullable=False, index=True)
    duration_ms = Column(Float, nullable=False)
    error_type = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AudiobookChapter(Base):
    __tablename__ = "audiobook_chapters"
    __table_args__ = (
        UniqueConstraint("book_id", "stable_chapter_key", name="uq_audiobook_chapter_stable_key"),
        Index("ix_audiobook_chapters_book_logical_key", "book_id", "logical_chapter_key"),
        _state_check("preview_status", CHAPTER_PREVIEW, "ck_audiobook_chapters_preview_status"),
        _state_check("generation_state", CHAPTER_GENERATION, "ck_audiobook_chapters_generation_state"),
    )

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_number = Column(Integer, nullable=False)
    content_file_name = Column(String, nullable=True)
    smil_file_path = Column(String, nullable=True)
    audio_file_path = Column(String, nullable=True)
    needs_reassembly = Column(Boolean, nullable=False, server_default="false")
    summary = Column(Text, nullable=True)
    summary_updated_at = Column(DateTime(timezone=True), nullable=True)
    # Manual chapter previews are independent of the full-book pipeline.
    # Values: None, queued, generating, ready, error.
    preview_status = Column(String, nullable=True)
    preview_error = Column(Text, nullable=True)
    stable_chapter_key = Column(String, nullable=True)
    # Physical EPUB spine items may be fragments of one reader-visible chapter.
    # Group them without rewriting the user's EPUB or losing per-file anchors.
    logical_chapter_key = Column(String, nullable=True)
    logical_part_order = Column(Integer, nullable=True)
    source_href = Column(String, nullable=True)
    source_content_hash = Column(String(64), nullable=True)
    title = Column(String, nullable=True)
    spine_order = Column(Integer, nullable=True)
    generation_state = Column(
        String,
        nullable=False,
        default=ChapterGenerationStatus.PENDING.value,
        server_default=ChapterGenerationStatus.PENDING.value,
    )
    audio_revision = Column(Integer, nullable=False, default=0, server_default="0")
    reader_audio_file_path = Column(String, nullable=True)
    reader_smil_file_path = Column(String, nullable=True)
    audio_size_bytes = Column(BigInteger, nullable=True)
    audio_sha256 = Column(String(64), nullable=True)
    smil_size_bytes = Column(BigInteger, nullable=True)
    smil_sha256 = Column(String(64), nullable=True)
    duration_ms = Column(BigInteger, nullable=True)


class AudiobookSeriesCharacter(Base):
    __tablename__ = "audiobook_series_characters"
    __table_args__ = (UniqueConstraint("series_name", "canonical_name", name="uq_audiobook_series_character"),)

    id = Column(Integer, primary_key=True, index=True)
    series_name = Column(String, nullable=False, index=True)
    canonical_name = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    voice_prompt = Column(String, nullable=True)
    tts_voice_id = Column(String, nullable=True)
    tts_voice_provider = Column(String, nullable=True)
    tts_seed = Column(Integer, nullable=True)
    is_narrator = Column(Boolean, nullable=False, server_default="false")
    aliases = Column(JSON, nullable=True)
    evidence = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class AudiobookCharacter(Base):
    __tablename__ = "audiobook_characters"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    series_character_id = Column(
        Integer,
        ForeignKey("audiobook_series_characters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    voice_prompt = Column(String, nullable=True)
    tts_voice_id = Column(String, nullable=True)
    tts_voice_provider = Column(String, nullable=True)
    tts_seed = Column(Integer, nullable=True)
    is_narrator = Column(Boolean, nullable=False, server_default="false")
    aliases = Column(JSON, nullable=True)
    evidence = Column(JSON, nullable=True)


class AudiobookSentence(Base):
    __tablename__ = "audiobook_sentences"
    __table_args__ = (_state_check("status", SENTENCE, "ck_audiobook_sentences_status"),)

    id = Column(Integer, primary_key=True, index=True)
    chapter_id = Column(Integer, ForeignKey("audiobook_chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    character_id = Column(Integer, ForeignKey("audiobook_characters.id", ondelete="SET NULL"), nullable=True)
    html_element_id = Column(String, nullable=False)
    sequence_order = Column(Integer, nullable=False)
    original_text = Column(Text, nullable=False)
    tagged_text = Column(Text, nullable=True)
    audio_file_path = Column(String, nullable=True)
    audio_duration_ms = Column(Integer, nullable=True)
    generation_group_id = Column(String(64), nullable=True, index=True)
    voice_similarity = Column(Float, nullable=True)
    tts_attempts = Column(Integer, nullable=True)
    speaker_confidence = Column(Float, nullable=True)
    speaker_reason = Column(Text, nullable=True)
    # Values and transitions are defined by lifecycle.SENTENCE.
    status = Column(String, nullable=False, server_default=SentenceStatus.PENDING_DIARIZATION.value)


class ImportedAudiobook(Base):
    """A human-narrated audiobook edition attached to a library book."""

    __tablename__ = "imported_audiobooks"
    __table_args__ = (
        _state_check("status", IMPORTED_AUDIOBOOK, "ck_imported_audiobooks_status"),
        _state_check("alignment_method", ALIGNMENT_METHOD, "ck_imported_audiobooks_alignment_method"),
    )

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    source_type = Column(String, nullable=False, default="upload", server_default="upload")
    asin = Column(String, nullable=True, index=True)
    # Values and transitions are defined by lifecycle.IMPORTED_AUDIOBOOK.
    status = Column(
        String,
        nullable=False,
        default=ImportedAudiobookStatus.QUEUED.value,
        server_default=ImportedAudiobookStatus.QUEUED.value,
        index=True,
    )
    alignment_method = Column(String, nullable=True)
    original_filenames = Column(JSON, nullable=True)
    duration_ms = Column(BigInteger, nullable=True)
    progress_current = Column(Integer, nullable=False, default=0, server_default="0")
    progress_total = Column(Integer, nullable=False, default=0, server_default="0")
    progress_detail = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    alignment_error = Column(Text, nullable=True)
    matched_content_version = Column(Integer, nullable=True)
    source_manifest_file_path = Column(String, nullable=True)
    source_manifest_sha256 = Column(String(64), nullable=True)
    source_size_bytes = Column(BigInteger, nullable=True)
    derived_revision = Column(Integer, nullable=False, default=0, server_default="0")
    derived_format_version = Column(Integer, nullable=False, default=0, server_default="0")
    # Version of the complete human-audiobook rebuild pipeline last applied.
    pipeline_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class ImportedAudiobookTrack(Base):
    """A chapter-like time range in an imported audiobook source file."""

    __tablename__ = "imported_audiobook_tracks"
    __table_args__ = (UniqueConstraint("imported_audiobook_id", "sequence_order", name="uq_imported_audiobook_track_order"),)

    id = Column(Integer, primary_key=True, index=True)
    imported_audiobook_id = Column(
        Integer,
        ForeignKey("imported_audiobooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matched_chapter_id = Column(
        Integer,
        ForeignKey("audiobook_chapters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # ``None`` means legacy/unknown and is preserved conservatively by rebuilds.
    match_method = Column(String, nullable=True)
    sequence_order = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    audio_file_path = Column(String, nullable=False)
    media_type = Column(String, nullable=False)
    source_audio_file_path = Column(String, nullable=True)
    source_clip_begin_ms = Column(BigInteger, nullable=True)
    source_clip_end_ms = Column(BigInteger, nullable=True)
    source_start_ms = Column(BigInteger, nullable=False, default=0, server_default="0")
    source_end_ms = Column(BigInteger, nullable=False)
    duration_ms = Column(BigInteger, nullable=False)
    transcript_file_path = Column(String, nullable=True)
    alignment_score = Column(Float, nullable=True)


class ImportedAudiobookCue(Base):
    """Sentence-level media-overlay timing for an imported track."""

    __tablename__ = "imported_audiobook_cues"
    __table_args__ = (UniqueConstraint("track_id", "sentence_id", name="uq_imported_audiobook_cue_sentence"),)

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(
        Integer,
        ForeignKey("imported_audiobook_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sentence_id = Column(
        Integer,
        ForeignKey("audiobook_sentences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_order = Column(Integer, nullable=False)
    clip_begin_ms = Column(BigInteger, nullable=False)
    clip_end_ms = Column(BigInteger, nullable=False)
    confidence = Column(Float, nullable=True)
    method = Column(String, nullable=False, default="estimated", server_default="estimated")
