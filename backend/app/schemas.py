from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional
from .models import SourceType

# Pydantic model for creating a new book.
# This is the expected shape of data when creating a book record.
class BookCreate(BaseModel):
    title: str
    author: str
    source_url: Optional[HttpUrl] = None
    source_type: SourceType
    epub_path: str
    cover_path: Optional[str] = None
    series: Optional[str] = None

# Pydantic model for updating a book.
class BookUpdate(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    series: Optional[str] = None

# Pydantic model for reading a book.
# This defines the shape of the data sent back to the client.
# It includes fields from the database that are generated automatically (id, created_at, updated_at).
class Book(BookCreate):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        # This allows the Pydantic model to be created from an ORM model (like our SQLAlchemy Book model).
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
