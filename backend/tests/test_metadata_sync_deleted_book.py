"""A book permanently deleted while a metadata sync job runs must be skipped, not orphaned."""

import pytest
from sqlalchemy import func, select, text

from backend.app import crud, models, schemas
from backend.app.services.metadata.suggestion import MetadataSuggestion
from backend.app.services.metadata_jobs import process_metadata_sync_job


async def _create_book(db, title: str) -> models.Book:
    return await crud.create_book(
        db,
        schemas.BookCreate(
            title=title,
            author="Alice Smith",
            immutable_path=f"{title}-immutable.epub",
            current_path=f"{title}.epub",
            source_type=models.SourceType.epub,
        ),
    )


async def _count(db, model, book_id: int) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(model.book_id == book_id))


@pytest.mark.asyncio
async def test_metadata_job_skips_book_deleted_between_fetch_and_write(db, sqlite_sessionmaker, mocker):
    # Enforce foreign keys like PostgreSQL does; the in-memory engine shares one connection.
    await db.execute(text("PRAGMA foreign_keys=ON"))
    deleted = await _create_book(db, "Deleted Midway")
    kept = await _create_book(db, "Still Here")
    deleted_id, kept_id = deleted.id, kept.id
    job = await crud.create_metadata_sync_job(db, trigger="manual", book_ids=[deleted_id, kept_id])

    async def fetch_then_delete(batch, all_books, **_kwargs):
        # The remote lookup is where the job spends its time; delete the book from
        # another session while it is "in flight".
        async with sqlite_sessionmaker() as other:
            await crud.delete_book(other, await crud.get_book(other, deleted_id))
        return [
            [
                MetadataSuggestion(
                    book=book,
                    matched=True,
                    source="open_library",
                    match_confidence=1.0,
                    remote_title=book.title,
                    remote_author=book.author,
                    remote_ids={"open_library_work_key": f"/works/OL{book.id}W"},
                    genre_tags=["Fantasy"],
                )
            ]
            for book in batch
        ]

    mocker.patch(
        "backend.app.services.metadata_jobs.generate_candidate_suggestions",
        side_effect=fetch_then_delete,
    )

    await process_metadata_sync_job(db, job.id)
    await db.refresh(job)

    assert job.status == "completed"
    assert job.error is None
    assert job.processed_books == 2
    assert job.matched_books == 1
    assert await db.scalar(select(func.count()).select_from(models.Book).where(models.Book.id == deleted_id)) == 0
    assert await _count(db, models.BookMetadataMatch, deleted_id) == 0
    assert await _count(db, models.MetadataProposal, deleted_id) == 0
    assert await _count(db, models.BookMetadataMatch, kept_id) == 1
