"""Series-related CRUD operations."""

from decimal import Decimal
from typing import List

from fastapi import HTTPException
from sqlalchemy import asc, case, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models


def _normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in tags:
        cleaned = raw_tag.strip()
        if not cleaned:
            continue
        folded = cleaned.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append(cleaned)
    return sorted(normalized, key=str.casefold)


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


async def get_series_metadata(db: AsyncSession, series_name: str) -> models.SeriesMetadata | None:
    result = await db.execute(
        select(models.SeriesMetadata).filter(func.lower(models.SeriesMetadata.series_name) == series_name.lower())
    )
    return result.scalars().first()


async def get_series_metadata_for_names(
    db: AsyncSession,
    series_names: list[str],
) -> dict[str, models.SeriesMetadata]:
    normalized_names = [name.strip() for name in series_names if name and name.strip()]
    if not normalized_names:
        return {}

    lowered_names = [name.lower() for name in normalized_names]
    result = await db.execute(
        select(models.SeriesMetadata).filter(func.lower(models.SeriesMetadata.series_name).in_(lowered_names))
    )
    metadata_by_lower = {
        metadata.series_name.lower(): metadata
        for metadata in result.scalars().all()
    }
    return {
        name: metadata_by_lower[name.lower()]
        for name in normalized_names
        if name.lower() in metadata_by_lower
    }


async def set_series_user_genre_tags(
    db: AsyncSession,
    series_name: str,
    user_genre_tags: list[str],
) -> models.SeriesMetadata | None:
    metadata = await get_series_metadata(db, series_name)
    normalized_tags = _normalize_tags(user_genre_tags)

    if not normalized_tags:
        if metadata is not None:
            await db.delete(metadata)
            await db.commit()
        return None

    if metadata is None:
        metadata = models.SeriesMetadata(series_name=series_name, user_genre_tags=normalized_tags)
        db.add(metadata)
    else:
        metadata.series_name = series_name
        metadata.user_genre_tags = normalized_tags

    await db.commit()
    await db.refresh(metadata)
    return metadata


async def rename_series(db: AsyncSession, old_name: str, new_name: str) -> int:
    """Rename a series, updating all books that belong to it. Returns count of updated books."""
    result = await db.execute(select(models.Book).filter(func.lower(models.Book.series) == old_name.lower()))
    books = result.scalars().all()
    for book in books:
        book.series = new_name

    old_metadata = await get_series_metadata(db, old_name)
    new_metadata = await get_series_metadata(db, new_name)
    if old_metadata is not None:
        if new_metadata is not None and new_metadata.id != old_metadata.id:
            new_metadata.user_genre_tags = _normalize_tags(
                [*(new_metadata.user_genre_tags or []), *(old_metadata.user_genre_tags or [])]
            )
            await db.delete(old_metadata)
        else:
            old_metadata.series_name = new_name

    await db.commit()
    return len(books)


async def merge_series(db: AsyncSession, source: str, target: str) -> int:
    """Move all books from source series into target series. Returns count of moved books."""
    result = await db.execute(select(models.Book).filter(func.lower(models.Book.series) == source.lower()))
    books = result.scalars().all()
    for book in books:
        book.series = target

    source_metadata = await get_series_metadata(db, source)
    target_metadata = await get_series_metadata(db, target)
    if source_metadata is not None:
        if target_metadata is None:
            source_metadata.series_name = target
        else:
            target_metadata.user_genre_tags = _normalize_tags(
                [*(target_metadata.user_genre_tags or []), *(source_metadata.user_genre_tags or [])]
            )
            await db.delete(source_metadata)

    await db.commit()
    return len(books)
