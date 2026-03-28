"""Series-related CRUD operations."""

from decimal import Decimal
from typing import List

from fastapi import HTTPException
from sqlalchemy import asc, case, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models


def _series_order_columns():
    return (
        asc(case((models.Book.series_index.is_(None), 1), else_=0)),
        asc(models.Book.series_index),
        asc(models.Book.title),
        asc(models.Book.id),
    )


async def get_books_by_series(db: AsyncSession, series: str, skip: int = 0, limit: int = 100) -> List[models.Book]:
    """Retrieve books from the database by series."""
    result = await db.execute(
        select(models.Book)
        .filter(func.lower(models.Book.series) == series.lower())
        .order_by(*_series_order_columns())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


async def reorder_series_books(db: AsyncSession, series: str, ordered_book_ids: List[int]) -> int:
    books = await get_books_by_series(db, series=series, skip=0, limit=100000)
    if not books:
        return 0

    if len(ordered_book_ids) != len(set(ordered_book_ids)):
        raise HTTPException(status_code=400, detail="Series reorder contains duplicate book ids")

    current_ids = {book.id for book in books}
    if current_ids != set(ordered_book_ids):
        raise HTTPException(status_code=400, detail="Series reorder must include every book in the series exactly once")

    books_by_id = {book.id: book for book in books}
    for index, book_id in enumerate(ordered_book_ids, start=1):
        books_by_id[book_id].series_index = Decimal(index)

    await db.commit()
    return len(ordered_book_ids)


async def get_all_series(db: AsyncSession) -> List[str]:
    """Return all distinct non-null series names, sorted alphabetically."""
    result = await db.execute(
        select(models.Book.series).filter(models.Book.series.isnot(None)).distinct().order_by(models.Book.series)
    )
    return [row[0] for row in result.all()]


async def rename_series(db: AsyncSession, old_name: str, new_name: str) -> int:
    """Rename a series, updating all books that belong to it. Returns count of updated books."""
    result = await db.execute(select(models.Book).filter(func.lower(models.Book.series) == old_name.lower()))
    books = result.scalars().all()
    for book in books:
        book.series = new_name
    await db.commit()
    return len(books)


async def merge_series(db: AsyncSession, source: str, target: str) -> int:
    """Move all books from source series into target series. Returns count of moved books."""
    result = await db.execute(select(models.Book).filter(func.lower(models.Book.series) == source.lower()))
    books = result.scalars().all()
    for book in books:
        book.series = target
    await db.commit()
    return len(books)
