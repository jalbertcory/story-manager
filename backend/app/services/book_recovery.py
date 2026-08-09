"""Recycle-bin and book revision helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .. import models

REVISION_FIELDS = (
    "title",
    "author",
    "series",
    "series_index",
    "genre_tags",
    "source_tags",
    "user_genre_tags",
    "metadata_remote_ids",
    "metadata_sync_source",
    "metadata_synced_at",
    "notes",
    "removed_chapters",
    "content_selectors",
    "audiobook_enabled",
)


def snapshot_book(book: models.Book) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for field in REVISION_FIELDS:
        value = getattr(book, field)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif field == "series_index" and value is not None:
            value = float(value)
        snapshot[field] = value
    return snapshot


def add_book_revision(
    db: AsyncSession,
    book: models.Book,
    *,
    action: str,
    summary: str,
    snapshot: dict[str, Any] | None = None,
) -> models.BookRevision:
    revision = models.BookRevision(
        book_id=book.id,
        action=action,
        summary=summary,
        snapshot=snapshot if snapshot is not None else snapshot_book(book),
    )
    db.add(revision)
    return revision


async def get_book_revisions(db: AsyncSession, book_id: int) -> list[models.BookRevision]:
    result = await db.execute(
        select(models.BookRevision)
        .where(models.BookRevision.book_id == book_id)
        .order_by(desc(models.BookRevision.created_at), desc(models.BookRevision.id))
    )
    return list(result.scalars().all())


async def get_book_revision(db: AsyncSession, book_id: int, revision_id: int) -> models.BookRevision | None:
    result = await db.execute(
        select(models.BookRevision).where(
            models.BookRevision.id == revision_id,
            models.BookRevision.book_id == book_id,
        )
    )
    return result.scalars().first()


def restore_snapshot(book: models.Book, snapshot: dict[str, Any]) -> None:
    for field in REVISION_FIELDS:
        if field not in snapshot:
            continue
        value = snapshot[field]
        if field == "metadata_synced_at" and isinstance(value, str):
            value = datetime.fromisoformat(value)
        setattr(book, field, value)
