from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional, List
from .models import SourceType


# Base Pydantic model for a book, defining common attributes.
class BookBase(BaseModel):
    title: str
    author: str
    source_url: Optional[HttpUrl] = None
    source_type: SourceType
    immutable_path: str
    current_path: str
    cover_path: Optional[str] = None
    series: Optional[str] = None
    master_word_count: Optional[int] = None
    current_word_count: Optional[int] = None
    removed_chapters: Optional[List[str]] = []
    div_selectors: Optional[List[str]] = []


# Pydantic model for creating a new book.
class BookCreate(BookBase):
    pass


# Pydantic model for updating a book.
class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    series: Optional[str] = None
    removed_chapters: Optional[List[str]] = None
    div_selectors: Optional[List[str]] = None


# Pydantic model for reading a book (API response).
class Book(BookBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Pydantic model for creating a new book log.
class BookLogCreate(BaseModel):
    book_id: int
    entry_type: str
    previous_chapter_count: Optional[int] = None
    new_chapter_count: Optional[int] = None
    words_added: Optional[int] = None


# Pydantic model for reading a book log.
class BookLog(BookLogCreate):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True


class CleaningConfigBase(BaseModel):
    name: str
    url_pattern: str
    chapter_selectors: Optional[List[str]] = None
    content_selectors: Optional[List[str]] = None


class CleaningConfigCreate(CleaningConfigBase):
    pass


class CleaningConfig(CleaningConfigBase):
    id: int

    class Config:
        from_attributes = True


class CleaningConfigUpdate(BaseModel):
    name: Optional[str] = None
    url_pattern: Optional[str] = None
    chapter_selectors: Optional[List[str]] = None
    content_selectors: Optional[List[str]] = None
