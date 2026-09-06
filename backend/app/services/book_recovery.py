"""Recycle-bin and book revision helpers."""

from __future__ import annotations

from pydantic import JsonValue
from ..book_snapshots import BookSnapshot

from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .. import models


def snapshot_book(book: models.Book) -> dict[str, JsonValue]:
    return BookSnapshot.model_validate(book).model_dump(mode="json")


def add_book_revision(
    db: AsyncSession,
    book: models.Book,
    *,
    action: str,
    summary: str,
    snapshot: dict[str, JsonValue] | None = None,
) -> models.BookRevision:
    revision = models.BookRevision(
        book_id=book.id,
        action=action,
        summary=summary,
        snapshot=(
            BookSnapshot.model_validate(snapshot).model_dump(mode="json", exclude_unset=True)
            if snapshot is not None
            else snapshot_book(book)
        ),
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


def restore_snapshot(book: models.Book, snapshot: object) -> None:
    # Validate every field before touching the ORM object; even a late invalid
    # timestamp or boolean must leave the entire book unchanged.
    validated = BookSnapshot.model_validate(snapshot)
    if "title" in validated.model_fields_set:
        book.title = validated.title
    if "author" in validated.model_fields_set:
        book.author = validated.author
    if "series" in validated.model_fields_set:
        book.series = validated.series
    if "series_index" in validated.model_fields_set:
        book.series_index = validated.series_index
    if "genre_tags" in validated.model_fields_set:
        book.genre_tags = validated.genre_tags
    if "source_tags" in validated.model_fields_set:
        book.source_tags = validated.source_tags
    if "user_genre_tags" in validated.model_fields_set:
        book.user_genre_tags = validated.user_genre_tags
    if "metadata_remote_ids" in validated.model_fields_set:
        book.metadata_remote_ids = validated.metadata_remote_ids
    if "metadata_details" in validated.model_fields_set:
        book.metadata_details = validated.metadata_details
    if "metadata_sync_source" in validated.model_fields_set:
        book.metadata_sync_source = validated.metadata_sync_source
    if "metadata_synced_at" in validated.model_fields_set:
        book.metadata_synced_at = validated.metadata_synced_at
    if "notes" in validated.model_fields_set:
        book.notes = validated.notes
    if "removed_chapters" in validated.model_fields_set:
        book.removed_chapters = validated.removed_chapters
    if "content_selectors" in validated.model_fields_set:
        book.content_selectors = validated.content_selectors
    if "audiobook_enabled" in validated.model_fields_set:
        book.audiobook_enabled = validated.audiobook_enabled
