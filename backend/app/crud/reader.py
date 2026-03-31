"""Reader API CRUD operations."""

from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import asc, case, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models


def _reader_books_query():
    return select(models.Book).where(
        models.Book.current_path.is_not(None),
        models.Book.download_status.is_(None),
    )


async def get_reader_books(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[models.Book]:
    result = await db.execute(
        _reader_books_query().order_by(desc(models.Book.content_updated_at), asc(models.Book.title)).offset(skip).limit(limit)
    )
    return result.scalars().all()


async def search_reader_books(db: AsyncSession, q: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    from sqlalchemy import or_

    pattern = f"%{q}%"
    result = await db.execute(
        _reader_books_query()
        .where(
            or_(
                models.Book.title.ilike(pattern),
                models.Book.author.ilike(pattern),
                models.Book.series.ilike(pattern),
            )
        )
        .order_by(asc(models.Book.title))
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def get_reader_book(db: AsyncSession, book_id: int) -> models.Book:
    result = await db.execute(_reader_books_query().where(models.Book.id == book_id))
    book = result.scalars().first()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


async def get_reader_series(db: AsyncSession) -> List[dict]:
    """Group reader-eligible books by series, returning summary stats."""
    query = (
        select(
            func.min(models.Book.series).label("name"),
            func.count(models.Book.id).label("book_count"),
            func.coalesce(func.sum(models.Book.current_word_count), 0).label("total_words"),
            func.max(models.Book.content_updated_at).label("latest_update"),
            func.min(case((models.Book.cover_path.is_not(None), models.Book.id))).label("cover_book_id"),
        )
        .where(
            models.Book.current_path.is_not(None),
            models.Book.download_status.is_(None),
            models.Book.series.is_not(None),
        )
        .group_by(func.lower(models.Book.series))
        .order_by(func.lower(models.Book.series))
    )
    result = await db.execute(query)
    return [
        {
            "name": row.name,
            "book_count": row.book_count,
            "total_words": row.total_words,
            "latest_update": row.latest_update,
            "cover_book_id": row.cover_book_id,
        }
        for row in result.all()
    ]


async def get_reader_standalone_books(db: AsyncSession) -> List[models.Book]:
    """Get reader-eligible books that have no series assigned."""
    result = await db.execute(_reader_books_query().where(models.Book.series.is_(None)).order_by(asc(models.Book.title)))
    return result.scalars().all()


async def get_reader_books_by_series(db: AsyncSession, name: str) -> List[models.Book]:
    """Get reader-eligible books in a series (case-insensitive), ordered by series index then title."""
    from .series import _series_order_columns

    result = await db.execute(
        _reader_books_query().where(func.lower(models.Book.series) == name.lower()).order_by(*_series_order_columns())
    )
    return result.scalars().all()


async def get_all_reader_books(db: AsyncSession) -> List[models.Book]:
    """Return all reader-eligible books."""
    result = await db.execute(_reader_books_query().order_by(asc(models.Book.title)))
    return result.scalars().all()


async def get_reader_updates(db: AsyncSession, since: Optional[datetime]) -> List[models.Book]:
    query = _reader_books_query()
    if since is not None:
        query = query.where(models.Book.content_updated_at > since)
    result = await db.execute(query.order_by(desc(models.Book.content_updated_at), asc(models.Book.title)))
    return result.scalars().all()


async def get_reader_books_by_series_names(
    db: AsyncSession, series_names: list[str]
) -> dict[str, list[models.Book]]:
    """Fetch reader-eligible books grouped by series name."""
    if not series_names:
        return {}
    lowered = [n.lower() for n in series_names]
    result = await db.execute(
        _reader_books_query().where(func.lower(models.Book.series).in_(lowered))
    )
    groups: dict[str, list[models.Book]] = {}
    for book in result.scalars().all():
        if book.series:
            groups.setdefault(book.series, []).append(book)
    return groups
