from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from .database import Base

class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    author = Column(String, index=True)
    series = Column(String, nullable=True, index=True)
    source_url = Column(String, unique=True, index=True, nullable=True)
    epub_path = Column(String, unique=True)
    # Storing the cover as a path to a file. The file itself can be extracted from the EPUB.
    cover_path = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
