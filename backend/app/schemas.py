from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from datetime import datetime
from typing import Optional, List
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .models import SourceType


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
    metadata_sync_source: Optional[str] = None
    metadata_synced_at: Optional[datetime] = None
    master_word_count: Optional[int] = None
    current_word_count: Optional[int] = None
    removed_chapters: Optional[List[str]] = Field(default_factory=list)
    content_selectors: Optional[List[str]] = Field(default_factory=list)
    notes: Optional[str] = None
    download_status: Optional[str] = None


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


class BookCatalogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class ReaderBook(BaseModel):
    id: int
    title: str
    author: str
    series: Optional[str] = None
    series_index: Optional[float] = None
    source_type: SourceType
    content_updated_at: datetime
    content_version: int
    current_word_count: Optional[int] = None
    effective_genre_tags: List[str] = Field(default_factory=list)
    download_url: str
    cover_url: Optional[str] = None


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
    match_confidence: float = 0.0
    remote_title: Optional[str] = None
    remote_author: Optional[str] = None
    remote_url: Optional[str] = None
    genre_tags: List[str] = Field(default_factory=list)
    new_genre_tags: List[str] = Field(default_factory=list)
    possible_missing_series_books: List[str] = Field(default_factory=list)
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
    last_checked_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None


class MetadataProposalSummary(BaseModel):
    id: int
    book_id: int
    book_title: str
    book_author: str
    book_series: Optional[str] = None
    match: Optional[MetadataMatch] = None
    proposed_genre_tags: List[str] = Field(default_factory=list)
    possible_missing_series_books: List[str] = Field(default_factory=list)
    note: Optional[str] = None
    status: str
    created_at: datetime
    reviewed_at: Optional[datetime] = None
