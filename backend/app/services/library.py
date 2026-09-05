"""Library organization and availability, independent of production status."""

from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models


def universe_expression():
    series_universe = (
        select(models.UniverseSeries.universe_id)
        .where(models.UniverseSeries.series_key == func.lower(models.Book.series))
        .correlate(models.Book)
        .scalar_subquery()
    )
    return case((models.Book.series.is_not(None), series_universe), else_=models.Book.universe_id)


def playable_audio_expression():
    # Match the admin reader: imported ready/aligning editions with tracks, or
    # generated chapters that can play without reassembly. Opt-in alone is not audio.
    imported = exists(
        select(models.ImportedAudiobook.id)
        .join(models.ImportedAudiobookTrack)
        .where(
            models.ImportedAudiobook.book_id == models.Book.id,
            models.ImportedAudiobook.status.in_(["ready", "aligning"]),
        )
    )
    generated = and_(
        models.Book.audiobook_enabled.is_(True),
        exists(
            select(models.AudiobookChapter.id).where(
                models.AudiobookChapter.book_id == models.Book.id,
                models.AudiobookChapter.audio_file_path.is_not(None),
                models.AudiobookChapter.needs_reassembly.is_(False),
            )
        ),
    )
    return imported | generated


async def library_book_info(db: AsyncSession, book_ids: list[int]) -> dict:
    if not book_ids:
        return {}
    result = await db.execute(
        select(
            models.Book.id,
            universe_expression().label("universe_id"),
            models.Universe.name.label("universe_name"),
            playable_audio_expression().label("audio_playable"),
            models.Book.current_path.is_not(None).label("has_epub"),
        )
        .outerjoin(models.Universe, models.Universe.id == universe_expression())
        .where(models.Book.id.in_(book_ids))
    )
    return {row.id: dict(row._mapping) for row in result}


async def library_groups(db: AsyncSession, *, group_by: str, q: str, universe: int | None, source: str | None):
    from ..crud.books import build_catalog_filter_conditions

    conditions = build_catalog_filter_conditions(q=q, universe=universe, source=source)
    key = func.lower(models.Book.series) if group_by == "series" else models.Universe.name
    display_name = func.min(models.Book.series) if group_by == "series" else models.Universe.name
    # The summary query returns group metadata, never every book's full payload.
    result = await db.execute(
        select(
            display_name.label("name"),
            func.count(models.Book.id).label("book_count"),
            func.min(models.Book.author).label("author"),
            func.count(func.distinct(models.Book.author)).label("author_count"),
            func.sum(case((playable_audio_expression(), 1), else_=0)).label("audio_count"),
            func.min(models.Universe.id).label("universe_id"),
        )
        .select_from(models.Book)
        .outerjoin(models.Universe, models.Universe.id == universe_expression())
        .where(*conditions)
        .group_by(key)
        .order_by(key.is_(None), func.lower(key))
    )
    groups = [dict(row._mapping) for row in result]
    covers = (
        select(
            key.label("name"),
            models.Book.id,
            func.row_number()
            .over(partition_by=key, order_by=(models.Book.series_index.asc().nulls_last(), models.Book.id))
            .label("rank"),
        )
        .select_from(models.Book)
        .outerjoin(models.Universe, models.Universe.id == universe_expression())
        .where(*conditions, models.Book.cover_path.is_not(None))
        .subquery()
    )
    cover_map = {}
    for row in await db.execute(select(covers).where(covers.c.rank <= 3).order_by(covers.c.rank)):
        cover_map.setdefault(row.name, []).append(row.id)
    for group in groups:
        cover_key = group["name"].lower() if group_by == "series" and group["name"] else group["name"]
        group["cover_ids"] = cover_map.get(cover_key, [])
    return groups


async def move_series_universe(db: AsyncSession, source: str, target: str):
    """Keep membership when renaming; reject merging incompatible universes."""
    source_key, target_key = source.lower(), target.lower()
    if source_key == target_key:
        return
    old = await db.get(models.UniverseSeries, source_key)
    new = await db.get(models.UniverseSeries, target_key)
    if old and new and old.universe_id != new.universe_id:
        from fastapi import HTTPException

        raise HTTPException(
            409, "These series belong to different universes. Change their universe membership before merging."
        )
    if old:
        if new:
            await db.delete(old)
        else:
            old.series_key = target_key
