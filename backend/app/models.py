from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, JSON, Numeric
from sqlalchemy.sql import func
from .database import Base
import enum


class SourceType(enum.Enum):
    web = "web"
    epub = "epub"


class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    author = Column(String, index=True)
    series = Column(String, nullable=True, index=True)
    series_index = Column(Numeric(6, 2), nullable=True)
    genre_tags = Column(JSON, nullable=True)
    user_genre_tags = Column(JSON, nullable=True)
    metadata_remote_ids = Column(JSON, nullable=True)
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

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    content_updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    content_version = Column(Integer, nullable=False, server_default="1")


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
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False)
    entry_type = Column(String, nullable=False)  # e.g., "added", "updated"
    previous_chapter_count = Column(Integer, nullable=True)
    new_chapter_count = Column(Integer, nullable=True)
    words_added = Column(Integer, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class UpdateTask(Base):
    __tablename__ = "update_tasks"

    id = Column(Integer, primary_key=True, index=True)
    total_books = Column(Integer, nullable=False)
    completed_books = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="running")
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)


class MetadataSyncJob(Base):
    __tablename__ = "metadata_sync_jobs"

    id = Column(Integer, primary_key=True, index=True)
    trigger = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")
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
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="pending")
    source = Column(String, nullable=True)
    match_confidence = Column(Numeric(5, 4), nullable=True)
    remote_title = Column(String, nullable=True)
    remote_author = Column(String, nullable=True)
    remote_url = Column(String, nullable=True)
    remote_ids = Column(JSON, nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)


class MetadataProposal(Base):
    __tablename__ = "metadata_proposals"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, unique=True, index=True)
    match_id = Column(Integer, ForeignKey("book_metadata_matches.id"), nullable=True)
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


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String, nullable=False)
    token_prefix = Column(String, unique=True, nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
