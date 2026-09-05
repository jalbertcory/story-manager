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


# Preserve the service import used by existing clients.
from .library_groups import library_groups  # noqa: F401, E402
