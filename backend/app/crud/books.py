"""Book CRUD operations: queries, creation, update, deletion."""

from typing import List, Optional
from datetime import datetime, timezone

from sqlalchemy import String, asc, case, cast, delete, desc, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models, schemas


def _build_books_query(sort_by: str = "title", sort_order: str = "asc"):
    sort_columns = {
        "title": models.Book.title,
        "author": models.Book.author,
        "series": models.Book.series,
        "word_count": models.Book.current_word_count,
        "updated_at": models.Book.updated_at,
        "audiobook_enabled": models.Book.audiobook_enabled,
    }
    column = sort_columns.get(sort_by, models.Book.title)
    order = asc(column) if sort_order == "asc" else desc(column)
    return select(models.Book).order_by(order, asc(models.Book.title), asc(models.Book.id))


def _series_order_columns():
    return (
        asc(case((models.Book.series_index.is_(None), 1), else_=0)),
        asc(models.Book.series_index),
        asc(models.Book.title),
        asc(models.Book.id),
    )


def _build_book_search_query(q: str, sort_by: str = "title", sort_order: str = "asc"):
    pattern = f"%{q}%"
    return _build_books_query(sort_by=sort_by, sort_order=sort_order).filter(
        or_(
            models.Book.title.ilike(pattern),
            models.Book.author.ilike(pattern),
            models.Book.series.ilike(pattern),
            cast(models.Book.genre_tags, String).ilike(pattern),
            cast(models.Book.user_genre_tags, String).ilike(pattern),
        )
    )


async def get_book_by_source_url(db: AsyncSession, source_url: str) -> Optional[models.Book]:
    """Retrieve a single book from the database by its source URL."""
    result = await db.execute(select(models.Book).filter(models.Book.source_url == source_url))
    return result.scalars().first()


async def get_web_books(db: AsyncSession) -> List[models.Book]:
    """Retrieve all web books from the database."""
    result = await db.execute(select(models.Book).filter(models.Book.source_type == models.SourceType.web))
    return result.scalars().all()


async def get_pending_web_books(db: AsyncSession) -> List[models.Book]:
    """Return pending web books so they can be resumed by the import queue."""
    result = await db.execute(
        select(models.Book).filter(
            models.Book.source_type == models.SourceType.web,
            models.Book.download_status == "pending",
        )
    )
    return result.scalars().all()


async def get_pending_refresh_books(db: AsyncSession) -> List[models.Book]:
    """Return web books whose refresh job was in-flight, so the queue can resume them."""
    result = await db.execute(
        select(models.Book).filter(
            models.Book.source_type == models.SourceType.web,
            models.Book.refresh_status.in_(["queued", "processing"]),
        )
    )
    return result.scalars().all()


async def get_books(
    db: AsyncSession,
    skip: int = 0,
    limit: int = 100,
    sort_by: str = "title",
    sort_order: str = "asc",
) -> List[models.Book]:
    """Retrieve a list of books from the database."""
    query = _build_books_query(sort_by=sort_by, sort_order=sort_order)
    result = await db.execute(query.offset(skip).limit(limit))
    return result.scalars().all()


async def search_books(db: AsyncSession, q: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """Search books by title, author, or series (case-insensitive)."""
    result = await db.execute(_build_book_search_query(q=q).offset(skip).limit(limit))
    return result.scalars().all()


async def get_book_catalog(
    db: AsyncSession,
    q: Optional[str] = None,
    sort_by: str = "title",
    sort_order: str = "asc",
) -> List[models.Book]:
    query = (
        _build_book_search_query(q=q, sort_by=sort_by, sort_order=sort_order)
        if q
        else _build_books_query(
            sort_by=sort_by,
            sort_order=sort_order,
        )
    )
    result = await db.execute(query)
    return result.scalars().all()


async def create_book(db: AsyncSession, book: schemas.BookCreate) -> models.Book:
    """Create a new book record in the database."""
    book_data = book.model_dump(exclude_unset=True)
    if "source_url" in book_data and book_data["source_url"] is not None:
        book_data["source_url"] = str(book_data["source_url"])
    book_data.setdefault("content_updated_at", datetime.now(timezone.utc))
    book_data.setdefault("content_version", 1)

    db_book = models.Book(**book_data)
    db.add(db_book)
    await db.commit()
    await db.refresh(db_book)
    return db_book


async def get_book(db: AsyncSession, book_id: int) -> Optional[models.Book]:
    """Retrieve a single book from the database by its ID."""
    result = await db.execute(select(models.Book).filter(models.Book.id == book_id))
    return result.scalars().first()


async def get_books_by_ids(db: AsyncSession, book_ids: List[int]) -> List[models.Book]:
    if not book_ids:
        return []

    result = await db.execute(select(models.Book).filter(models.Book.id.in_(book_ids)))
    books = {book.id: book for book in result.scalars().all()}
    return [books[book_id] for book_id in book_ids if book_id in books]


async def update_book(db: AsyncSession, book: models.Book, update_data: schemas.BookUpdate) -> models.Book:
    """Update a book record in the database."""
    update_data_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_data_dict.items():
        setattr(book, key, value)
    if "series" in update_data_dict and not update_data_dict["series"]:
        book.series_index = None
    await db.commit()
    await db.refresh(book)
    return book


async def reset_failed_web_book_for_retry(
    db: AsyncSession,
    book: models.Book,
    source_url: str,
) -> models.Book:
    """Reuse a failed web-import placeholder so the same URL can be retried."""
    book.title = source_url
    book.author = "Pending"
    book.series = None
    book.series_index = None
    book.genre_tags = []
    book.source_tags = []
    book.cover_path = None
    book.immutable_path = None
    book.current_path = None
    book.master_word_count = None
    book.current_word_count = None
    book.removed_chapters = []
    book.content_selectors = []
    book.download_status = "pending"
    book.source_url = source_url
    book.source_type = models.SourceType.web
    await db.commit()
    await db.refresh(book)
    return book


async def detach_book_source(db: AsyncSession, book: models.Book) -> models.Book:
    """Clear a book's remote source metadata and treat it as a normal EPUB."""
    book.source_url = None
    book.source_type = models.SourceType.epub
    book.download_status = None
    await db.commit()
    await db.refresh(book)
    return book


async def touch_book_content(db: AsyncSession, book: models.Book) -> None:
    book.content_updated_at = datetime.now(timezone.utc)
    book.content_version = (book.content_version or 0) + 1


async def get_books_by_author(db: AsyncSession, author: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """Retrieve books from the database by author."""
    result = await db.execute(select(models.Book).filter(models.Book.author.ilike(f"%{author}%")).offset(skip).limit(limit))
    return result.scalars().all()


async def get_book_by_title(db: AsyncSession, title: str) -> Optional[models.Book]:
    """Retrieve a single book from the database by its title."""
    result = await db.execute(select(models.Book).filter(models.Book.title == title))
    return result.scalars().first()


async def get_book_by_title_and_author(db: AsyncSession, title: str, author: str) -> Optional[models.Book]:
    """Retrieve a book by exact (case-insensitive) title and author match."""
    result = await db.execute(
        select(models.Book).where(
            func.lower(models.Book.title) == title.lower(),
            func.lower(models.Book.author) == author.lower(),
        )
    )
    return result.scalars().first()


async def delete_book(db: AsyncSession, book: models.Book) -> None:
    """Delete a book record from the database."""
    await db.execute(delete(models.MetadataProposal).where(models.MetadataProposal.book_id == book.id))
    await db.execute(delete(models.BookMetadataMatch).where(models.BookMetadataMatch.book_id == book.id))
    await db.execute(delete(models.BookLog).where(models.BookLog.book_id == book.id))
    await db.delete(book)
    await db.commit()


async def delete_all_books(db: AsyncSession) -> int:
    books = await get_books(db, limit=100000)
    book_count = len(books)
    if book_count == 0:
        return 0

    book_ids = [book.id for book in books]
    await db.execute(delete(models.MetadataProposal).where(models.MetadataProposal.book_id.in_(book_ids)))
    await db.execute(delete(models.BookMetadataMatch).where(models.BookMetadataMatch.book_id.in_(book_ids)))
    await db.execute(delete(models.BookLog).where(models.BookLog.book_id.in_(book_ids)))
    await db.execute(delete(models.Book))
    await db.commit()
    return book_count


async def count_books(db: AsyncSession, q: Optional[str] = None) -> int:
    """Count books, optionally filtered by a search query (title/author/series)."""
    if q:
        pattern = f"%{q}%"
        result = await db.execute(
            select(func.count(models.Book.id)).filter(
                or_(
                    models.Book.title.ilike(pattern),
                    models.Book.author.ilike(pattern),
                    models.Book.series.ilike(pattern),
                    cast(models.Book.genre_tags, String).ilike(pattern),
                    cast(models.Book.user_genre_tags, String).ilike(pattern),
                )
            )
        )
    else:
        result = await db.execute(select(func.count(models.Book.id)))
    return result.scalar() or 0


async def get_books_without_series(db: AsyncSession) -> List[models.Book]:
    """Retrieve all books that have no series assigned."""
    result = await db.execute(select(models.Book).filter(models.Book.series.is_(None)))
    return result.scalars().all()
