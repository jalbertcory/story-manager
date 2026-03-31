"""Series-related CRUD operations."""

import math
from decimal import Decimal
from typing import List

from fastapi import HTTPException
from sqlalchemy import asc, case, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .. import models

MAX_TAGS_PER_SERIES = 20
MAX_TAG_LENGTH = 50


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


def validate_genre_tags(tags: list[str]) -> None:
    """Raise HTTPException if tags exceed limits."""
    if len(tags) > MAX_TAGS_PER_SERIES:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_TAGS_PER_SERIES} genre tags allowed")
    for tag in tags:
        if len(tag.strip()) > MAX_TAG_LENGTH:
            raise HTTPException(status_code=400, detail=f"Genre tags must be {MAX_TAG_LENGTH} characters or fewer")


def compute_effective_series_genre_tags(
    books: list,
    series_metadata: "models.SeriesMetadata | None",
) -> list[str]:
    """Compute effective genre tags for a series.

    If the series has explicit user genre tags, returns those.
    Otherwise aggregates from book-level tags using frequency analysis.
    """
    if series_metadata and series_metadata.user_genre_tags:
        return _normalize_tags(series_metadata.user_genre_tags)

    if not books:
        return []

    counts: dict[str, int] = {}
    canonical: dict[str, str] = {}
    for book in books:
        book_tags = _normalize_tags([
            *(book.user_genre_tags or []),
            *(book.genre_tags or []),
        ])
        for tag in book_tags:
            key = tag.casefold()
            counts[key] = counts.get(key, 0) + 1
            if key not in canonical:
                canonical[key] = tag

    if not counts:
        return []

    minimum_matches = math.ceil(len(books) / 2)
    ranked = sorted(counts.items(), key=lambda x: (-x[1], x[0]))

    shared = [canonical[key] for key, count in ranked if count >= minimum_matches]
    if shared:
        return shared

    return [canonical[key] for key, _ in ranked[:4]]


async def cleanup_orphaned_series_metadata(db: AsyncSession) -> int:
    """Delete SeriesMetadata records whose series_name has no matching books."""
    result = await db.execute(select(models.SeriesMetadata))
    all_metadata = result.scalars().all()
    if not all_metadata:
        return 0

    active_result = await db.execute(
        select(func.lower(models.Book.series)).filter(models.Book.series.isnot(None)).distinct()
    )
    active_series = {row[0] for row in active_result.all()}

    deleted = 0
    for metadata in all_metadata:
        if metadata.series_name.lower() not in active_series:
            await db.delete(metadata)
            deleted += 1

    if deleted:
        await db.commit()
    return deleted
