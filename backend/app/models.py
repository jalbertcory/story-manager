from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
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
    source_url = Column(String, unique=True, index=True, nullable=True)
    source_type = Column(Enum(SourceType), nullable=False, default=SourceType.epub)
    epub_path = Column(String, unique=True)
    # Storing the cover as a path to a file. The file itself can be extracted from the EPUB.
    cover_path = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


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
