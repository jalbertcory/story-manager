from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from datetime import datetime
from typing import Literal, Optional, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .models import SourceType

AudiobookType = Literal["ai_generated", "human_narrated"]


# Base Pydantic model for a book, defining common attributes.
class BookBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    author: str
    source_url: Optional[HttpUrl] = None
    source_type: SourceType
    immutable_path: Optional[str] = None
    current_path: Optional[str] = None
    cover_path: Optional[str] = None
    series: Optional[str] = None
    series_index: Optional[float] = None
    genre_tags: Optional[List[str]] = Field(default_factory=list)
    source_tags: Optional[List[str]] = Field(default_factory=list)
    user_genre_tags: Optional[List[str]] = Field(default_factory=list)
    metadata_remote_ids: Optional[dict] = None
    metadata_details: Optional[dict] = None
    metadata_sync_source: Optional[str] = None
    metadata_synced_at: Optional[datetime] = None
    master_word_count: Optional[int] = None
    current_word_count: Optional[int] = None
    removed_chapters: Optional[List[str]] = Field(default_factory=list)
    content_selectors: Optional[List[str]] = Field(default_factory=list)
    notes: Optional[str] = None
    download_status: Optional[str] = None
    refresh_status: Optional[str] = None
    audiobook_enabled: bool = False
    audiobook_pipeline_status: Optional[str] = None
    audiobook_tts_provider: Optional[str] = None


# Pydantic model for creating a new book.
class BookCreate(BookBase):
    pass


# Pydantic model for updating a book.
class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    series: Optional[str] = None
    series_index: Optional[float] = None
    genre_tags: Optional[List[str]] = None
    user_genre_tags: Optional[List[str]] = None
    source_tags: Optional[List[str]] = None
    metadata_remote_ids: Optional[dict] = None
    audiobook_enabled: Optional[bool] = None
    removed_chapters: Optional[List[str]] = None
    content_selectors: Optional[List[str]] = None
    notes: Optional[str] = None


# Pydantic model for reading a book (API response).
class Book(BookBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    content_updated_at: datetime
    content_version: int
    deleted_at: Optional[datetime] = None
    purge_after: Optional[datetime] = None


class RecycledBook(Book):
    recovery_files_available: bool


class RecycleBin(BaseModel):
    retention_days: int
    books: List[RecycledBook] = Field(default_factory=list)


class BookRevision(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    book_id: int
    action: str
    summary: str
    snapshot: dict
    created_at: datetime


class BookCatalogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    universe_id: Optional[int] = None
    universe_name: Optional[str] = None
    audio_playable: bool = False
    has_epub: bool = False
    id: int
    title: str
    author: str
    series: Optional[str] = None
    series_index: Optional[float] = None
    genre_tags: Optional[List[str]] = Field(default_factory=list)
    user_genre_tags: Optional[List[str]] = Field(default_factory=list)
    series_user_genre_tags: Optional[List[str]] = Field(default_factory=list)
    effective_genre_tags: Optional[List[str]] = Field(default_factory=list)
    effective_series_genre_tags: Optional[List[str]] = Field(default_factory=list)
    source_type: SourceType
    cover_path: Optional[str] = None
    current_word_count: Optional[int] = None
    updated_at: Optional[datetime] = None
    download_status: Optional[str] = None
    refresh_status: Optional[str] = None
    audiobook_enabled: bool = False
    audiobook_pipeline_status: Optional[str] = None
    audiobook_types: List[AudiobookType] = Field(default_factory=list)


class CatalogGenreFacet(BaseModel):
    name: str
    count: int


class BookCatalogFacets(BaseModel):
    series: int = 0
    standalone: int = 0
    web: int = 0
    audiobook_available: int = 0
    audiobook_missing: int = 0
    missing_series: int = 0
    refreshing: int = 0
    refresh_attention: int = 0
    genres: List[CatalogGenreFacet] = Field(default_factory=list)


class BookCatalogPage(BaseModel):
    items: List[BookCatalogEntry] = Field(default_factory=list)
    next_cursor: Optional[str] = None
    total_count: int = 0
    facets: BookCatalogFacets = Field(default_factory=BookCatalogFacets)


# Pydantic model for creating a new book log.
class BookLogCreate(BaseModel):
    book_id: int
    entry_type: str
    previous_chapter_count: Optional[int] = None
    new_chapter_count: Optional[int] = None
    words_added: Optional[int] = None


# Pydantic model for reading a book log.
class BookLog(BookLogCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime


class CleaningConfigBase(BaseModel):
    name: str
    url_pattern: str
    chapter_selectors: Optional[List[str]] = None
    content_selectors: Optional[List[str]] = None


class CleaningConfigCreate(CleaningConfigBase):
    pass


class CleaningConfig(CleaningConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: int


class CleaningConfigUpdate(BaseModel):
    name: Optional[str] = None
    url_pattern: Optional[str] = None
    chapter_selectors: Optional[List[str]] = None
    content_selectors: Optional[List[str]] = None


class UpdateTask(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    total_books: int
    completed_books: int
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None


class SchedulerJobStatus(BaseModel):
    job_id: str
    schedule: str
    schedule_mode: str = "interval"
    schedule_time_local: Optional[str] = None
    schedule_timezone: Optional[str] = None
    next_run_at: Optional[datetime] = None
    scheduler_running: bool
    run_in_progress: bool
    last_run_started_at: Optional[datetime] = None
    last_run_completed_at: Optional[datetime] = None
    last_run_status: Optional[str] = None


class SchedulerConfigUpdate(BaseModel):
    time_local: str = Field(pattern=r"^\d{2}:\d{2}$")
    timezone: str = Field(min_length=1, max_length=100)

    @field_validator("time_local")
    @classmethod
    def validate_time_local(cls, value: str) -> str:
        hour_text, minute_text = value.split(":")
        hour = int(hour_text)
        minute = int(minute_text)
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("time_local must be a valid 24-hour time")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value


class BookLogWithTitle(BookLog):
    model_config = ConfigDict(from_attributes=True)

    book_title: str


class BookChapterUpdateHistoryPoint(BaseModel):
    id: int
    timestamp: datetime
    entry_type: str
    previous_chapter_count: Optional[int] = None
    new_chapter_count: Optional[int] = None
    chapters_added: int
    words_added: int
    average_words_per_chapter: Optional[float] = None
    included_in_stats: bool = False
    is_initial_sync: bool = False
    is_catch_up_sync: bool = False


class BookChapterUpdateHistorySummary(BaseModel):
    total_update_events: int
    total_chapters_added: int
    total_words_added: int
    average_words_per_week: Optional[float] = None
    average_words_per_month: Optional[float] = None
    average_days_between_updates: Optional[float] = None
    predicted_next_update_at: Optional[datetime] = None
    last_update_at: Optional[datetime] = None


class BookChapterUpdateHistory(BaseModel):
    book_id: int
    history: List[BookChapterUpdateHistoryPoint] = Field(default_factory=list)
    summary: BookChapterUpdateHistorySummary


class ApiKeyCreate(BaseModel):
    label: str


class ApiKey(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    token_prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class ApiKeyWithToken(ApiKey):
    token: str


class SeriesRename(BaseModel):
    new_name: str


class SeriesMerge(BaseModel):
    source: str
    target: str


class SeriesReorder(BaseModel):
    ordered_book_ids: List[int]


class SeriesGenresUpdate(BaseModel):
    user_genre_tags: List[str] = Field(default_factory=list)


class SeriesMetadataSummary(BaseModel):
    series_name: str
    user_genre_tags: List[str] = Field(default_factory=list)


class ReaderAudiobookCapability(BaseModel):
    status: Literal["stale", "processing", "partial", "complete", "error"]
    revision: int
    source_content_version: int
    text_content_version: int
    ready_chapter_count: int
    total_chapter_count: int
    ready_audio_bytes: int
    manifest_url: str


class ReaderAudiobookTextAsset(BaseModel):
    content_version: int
    size_bytes: int
    sha256: str
    url: str


class ReaderAudiobookChapter(BaseModel):
    key: str
    title: Optional[str] = None
    href: str
    state: Literal["pending", "processing", "ready", "error"]
    audio_version: Optional[int] = None
    duration_ms: Optional[int] = None
    audio_size_bytes: Optional[int] = None
    audio_sha256: Optional[str] = None
    smil_size_bytes: Optional[int] = None
    smil_sha256: Optional[str] = None
    audio_url: Optional[str] = None
    smil_url: Optional[str] = None


class ReaderAudiobookManifest(BaseModel):
    revision: int
    source_content_version: int
    text: ReaderAudiobookTextAsset
    chapters: List[ReaderAudiobookChapter]


class ReaderBook(BaseModel):
    id: int
    title: str
    author: str
    series: Optional[str] = None
    series_index: Optional[float] = None
    source_url: Optional[str] = None
    source_type: SourceType
    content_updated_at: datetime
    content_version: int
    current_word_count: Optional[int] = None
    effective_genre_tags: List[str] = Field(default_factory=list)
    download_url: str
    cover_url: Optional[str] = None
    audiobook: Optional[ReaderAudiobookCapability] = None
    audiobook_types: List[AudiobookType] = Field(default_factory=list)


PROCESSING_JOB_TYPES = Literal[
    "clean_book",
    "clean_all",
    "refresh_book",
    "refresh_all",
    "audiobook_pipeline",
    "import_audiobook",
    "upgrade_imported_audiobook",
    "rebuild_imported_audiobook",
    "rematch_imported_audiobook",
    "align_imported_audiobook",
    "metadata_sync",
    "generate_sentence_audio",
    "generate_chapter_preview",
    "retry_cover",
    "create_backup",
    "verify_backup",
]


class ProcessingJobRequest(BaseModel):
    job_type: PROCESSING_JOB_TYPES
    book_ids: List[int] = Field(default_factory=list)
    target_id: Optional[int] = None
    payload: dict = Field(default_factory=dict)


class ProcessingJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    status: str
    resource_lane: str
    book_id: Optional[int] = None
    book_title: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    target_content_version: Optional[int] = None
    parent_job_id: Optional[int] = None
    request_id: str
    payload: dict = Field(default_factory=dict)
    progress_current: int
    progress_total: int
    progress_detail: Optional[str] = None
    attempt_count: int
    max_attempts: int
    available_at: datetime
    lease_expires_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    cancel_requested: bool
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ProcessingJobsCreated(BaseModel):
    jobs: List[ProcessingJob] = Field(default_factory=list)


class BackupArchive(BaseModel):
    filename: str
    created_at: datetime
    size_bytes: int
    library_file_count: int
    library_size_bytes: int
    valid_manifest: bool
    verified_at_creation: bool
    error: Optional[str] = None
    download_url: str


class BackupInventory(BaseModel):
    retention_count: int
    backups: List[BackupArchive] = Field(default_factory=list)


class AttentionBookItem(BaseModel):
    book_id: int
    title: str
    author: str
    issue: str
    detail: Optional[str] = None


class AttentionFileItem(AttentionBookItem):
    path: Optional[str] = None


class AttentionJobItem(BaseModel):
    id: int
    job_type: str
    book_id: Optional[int] = None
    book_title: Optional[str] = None
    error: Optional[str] = None
    completed_at: Optional[datetime] = None


class AttentionMetadataItem(BaseModel):
    proposal_id: int
    book_id: int
    title: str
    author: str
    note: Optional[str] = None


class AttentionBookCategory(BaseModel):
    count: int
    items: List[AttentionBookItem] = Field(default_factory=list)


class AttentionFileCategory(BaseModel):
    count: int
    items: List[AttentionFileItem] = Field(default_factory=list)


class AttentionJobCategory(BaseModel):
    count: int
    items: List[AttentionJobItem] = Field(default_factory=list)


class AttentionMetadataCategory(BaseModel):
    count: int
    items: List[AttentionMetadataItem] = Field(default_factory=list)


class AttentionDashboard(BaseModel):
    total_count: int
    failed_jobs: AttentionJobCategory
    failed_refreshes: AttentionBookCategory
    stale_audiobooks: AttentionBookCategory
    metadata_proposals: AttentionMetadataCategory
    broken_files: AttentionFileCategory
    missing_covers: AttentionFileCategory


class ReaderSeriesSummary(BaseModel):
    name: str
    book_count: int
    total_words: int
    latest_update: Optional[datetime] = None
    cover_url: Optional[str] = None
    genre_tags: List[str] = Field(default_factory=list)


class MetadataSyncPreviewRequest(BaseModel):
    book_ids: Optional[List[int]] = None


class MetadataSyncApplyRequest(BaseModel):
    book_ids: Optional[List[int]] = None


class MetadataSyncBookResult(BaseModel):
    book_id: int
    title: str
    author: str
    matched: bool
    source: Optional[str] = None
    match_confidence: float = 0.0
    remote_title: Optional[str] = None
    remote_author: Optional[str] = None
    remote_url: Optional[str] = None
    remote_ids: Optional[dict] = None
    metadata_details: Optional[dict] = None
    genre_tags: List[str] = Field(default_factory=list)
    new_genre_tags: List[str] = Field(default_factory=list)
    possible_missing_series_books: List[str] = Field(default_factory=list)
    match_issues: List[str] = Field(default_factory=list)
    note: Optional[str] = None


class MetadataSyncPreviewResponse(BaseModel):
    scanned_books: int
    matched_books: int
    books_with_new_genres: int
    books_with_missing_series_candidates: int
    results: List[MetadataSyncBookResult]


class MetadataSyncApplyResponse(BaseModel):
    scanned_books: int
    matched_books: int
    updated_books: int
    books_with_new_genres: int
    books_with_missing_series_candidates: int
    results: List[MetadataSyncBookResult]


class MetadataJobRequest(BaseModel):
    book_ids: Optional[List[int]] = None
    trigger: str = "manual"


class MetadataSyncJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger: str
    status: str
    total_books: int
    processed_books: int
    matched_books: int
    proposed_books: int
    applied_books: int
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class MetadataMatch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    book_id: int
    status: str
    source: Optional[str] = None
    match_confidence: Optional[float] = None
    remote_title: Optional[str] = None
    remote_author: Optional[str] = None
    remote_url: Optional[str] = None
    remote_ids: Optional[dict] = None
    remote_metadata: Optional[dict] = None
    proposed_genre_tags: Optional[List[str]] = None
    possible_missing_series_books: Optional[List[str]] = None
    match_issues: Optional[List[str]] = None
    note: Optional[str] = None
    last_checked_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None


class MetadataProposalSummary(BaseModel):
    id: int
    book_id: int
    book_title: str
    book_author: str
    book_series: Optional[str] = None
    book_series_index: Optional[float] = None
    match: Optional[MetadataMatch] = None
    candidate_matches: List[MetadataMatch] = Field(default_factory=list)
    proposed_genre_tags: List[str] = Field(default_factory=list)
    possible_missing_series_books: List[str] = Field(default_factory=list)
    note: Optional[str] = None
    status: str
    created_at: datetime
    reviewed_at: Optional[datetime] = None
