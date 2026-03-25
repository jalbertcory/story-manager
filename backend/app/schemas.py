from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from datetime import datetime
from typing import Optional, List
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
    next_run_at: Optional[datetime] = None
    scheduler_running: bool
    run_in_progress: bool
    last_run_started_at: Optional[datetime] = None
    last_run_completed_at: Optional[datetime] = None
    last_run_status: Optional[str] = None


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
    download_url: str
    cover_url: Optional[str] = None


class ReaderSeriesSummary(BaseModel):
    name: str
    book_count: int
    total_words: int
    latest_update: Optional[datetime] = None
    cover_url: Optional[str] = None
