"""Tests for the durable processing ledger and audio invalidation graph."""

import asyncio

import pytest
from sqlalchemy import select

from backend.app import crud
from backend.app.models import Book, ImportedAudiobook, ProcessingJob, SourceType
from backend.app.services import processing_queue as processing_queue_module
from backend.app.services.processing_queue import ProcessingQueue, queue_audio_reconciliation


@pytest.mark.asyncio
async def test_processing_api_queues_lists_cancels_and_retries(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        book = Book(
            title="Queue Me",
            author="Worker",
            source_type=SourceType.epub,
            immutable_path="library/queue-me-immutable.epub",
            current_path="library/queue-me.epub",
        )
        db.add(book)
        await db.commit()
        await db.refresh(book)
        book_id = book.id

    response = app_client.post(
        "/api/processing/jobs",
        json={"job_type": "clean_book", "book_ids": [book_id]},
    )
    assert response.status_code == 202
    job = response.json()["jobs"][0]
    assert job["status"] == "queued"
    assert job["book_id"] == book_id

    response = app_client.get("/api/processing/jobs?statuses=queued")
    assert response.status_code == 200
    assert response.json()[0]["book_title"] == "Queue Me"

    response = app_client.delete(f"/api/processing/jobs/{job['id']}")
    assert response.status_code == 200
    assert response.json()["status"] == "canceled"

    response = app_client.post(f"/api/processing/jobs/{job['id']}/retry")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    response = app_client.post(f"/api/books/{book_id}/retry-cover")
    assert response.status_code == 200
    assert response.headers["x-processing-job-id"]
    async with sqlite_sessionmaker() as db:
        cover_job = await db.get(ProcessingJob, int(response.headers["x-processing-job-id"]))
        assert cover_job is not None
        assert cover_job.job_type == "retry_cover"


@pytest.mark.asyncio
async def test_audio_reconciliation_invalidates_generated_and_human_derivatives(db):
    book = Book(
        title="Changed Text",
        author="Cleaner",
        source_type=SourceType.epub,
        immutable_path="library/changed-immutable.epub",
        current_path="library/changed.epub",
        audiobook_enabled=True,
        audiobook_revision=3,
        audiobook_source_content_version=1,
        audiobook_publication_state="complete",
        content_version=2,
    )
    db.add(book)
    await db.flush()
    edition = ImportedAudiobook(
        book_id=book.id,
        name="Human edition",
        status="ready",
        alignment_method="transcribed",
        matched_content_version=1,
    )
    db.add(edition)
    await db.commit()

    jobs = await queue_audio_reconciliation(book, db, parent_job_id=None)
    await db.refresh(book)
    await db.refresh(edition)

    assert book.audiobook_publication_state == "stale"
    assert edition.status == "stale"
    assert [job.job_type for job in jobs] == [
        "rematch_imported_audiobook",
        "audiobook_pipeline",
    ]
    assert jobs[0].payload["realign"] is True
    assert all(job.target_content_version == 2 for job in jobs)


@pytest.mark.asyncio
async def test_touching_content_marks_published_audiobook_stale(db):
    book = Book(
        title="Published",
        author="Versioned",
        source_type=SourceType.epub,
        immutable_path="library/published-immutable.epub",
        current_path="library/published.epub",
        audiobook_enabled=True,
        audiobook_revision=1,
        audiobook_source_content_version=1,
        audiobook_publication_state="complete",
        content_version=1,
    )
    db.add(book)
    await db.commit()

    await crud.touch_book_content(db, book)
    await db.commit()
    result = await db.execute(select(ProcessingJob))

    assert book.content_version == 2
    assert book.audiobook_pending_content_version == 2
    assert book.audiobook_publication_state == "stale"
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_progress_mirror_updates_the_durable_job(monkeypatch, sqlite_sessionmaker):
    monkeypatch.setattr(processing_queue_module, "SessionLocal", sqlite_sessionmaker)
    async with sqlite_sessionmaker() as db:
        job, _created = await crud.create_processing_job(db, job_type="metadata_sync")
        job_id = job.id

    async def operation():
        await asyncio.sleep(0.55)
        return "done"

    async def snapshot():
        return 2, 5, "Checked 2 of 5 books"

    result = await ProcessingQueue()._run_with_progress_mirror(job_id, operation, snapshot)

    async with sqlite_sessionmaker() as db:
        job = await db.get(ProcessingJob, job_id)
        assert job is not None
        assert result == "done"
        assert job.progress_current == 2
        assert job.progress_total == 5
        assert job.progress_detail == "Checked 2 of 5 books"
