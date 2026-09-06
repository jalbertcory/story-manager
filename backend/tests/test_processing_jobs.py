"""Tests for the durable processing ledger and audio invalidation graph."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.app import crud
from backend.app.models import (
    AudiobookChapter,
    AudiobookSettings,
    Book,
    ImportedAudiobook,
    ImportedAudiobookTrack,
    ProcessingJob,
    SourceType,
)
from backend.app.services import processing_queue as processing_queue_module
from backend.app.services.processing_queue import ProcessingQueue, queue_audio_reconciliation, queue_processing_job


@pytest.mark.asyncio
async def test_processing_jobs_use_explicit_resource_policies(sqlite_sessionmaker):
    expected = {
        "clean_book": "cpu",
        "refresh_book": "maintenance",
        "metadata_sync": "llm",
        "generate_sentence_audio": "tts",
        "align_imported_audiobook": "transcription",
    }
    async with sqlite_sessionmaker() as db:
        for index, (job_type, lane) in enumerate(expected.items(), start=1):
            job = await queue_processing_job(
                db=db,
                job_type=job_type,
                dedupe_key=f"lane-test-{index}",
            )
            assert job.resource_lane == lane
            assert job.max_attempts == 3

    async with sqlite_sessionmaker() as db:
        backup = await queue_processing_job(db=db, job_type="create_backup", dedupe_key="backup-lane-test")
        assert backup.resource_lane == "maintenance"
        assert backup.max_attempts == 1


@pytest.mark.asyncio
async def test_processing_queue_creates_backup_under_write_barrier(sqlite_sessionmaker, monkeypatch, tmp_path):
    async with sqlite_sessionmaker() as db:
        job, _created = await crud.create_processing_job(
            db,
            job_type="create_backup",
            resource_lane="maintenance",
            max_attempts=1,
        )
        job.status = "running"
        await db.commit()
        await db.refresh(job)

    observed = {}

    def create_backup(**kwargs):
        observed.update(kwargs)
        assert processing_queue_module.backup_barrier.backup_active is True
        return {"filename": "test.story-manager.zip"}

    monkeypatch.setattr(processing_queue_module, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(processing_queue_module, "create_backup_archive", create_backup)
    monkeypatch.setattr(processing_queue_module, "LIBRARY_PATH", tmp_path / "library")
    monkeypatch.setattr(processing_queue_module, "BACKUP_PATH", tmp_path / "backups")
    monkeypatch.setattr(processing_queue_module, "DATABASE_URL", "postgresql+psycopg://localhost/test")

    detail = await ProcessingQueue()._execute(job)

    assert detail == "Backup created and verified: test.story-manager.zip"
    assert observed["library_path"] == tmp_path / "library"
    assert observed["backup_path"] == tmp_path / "backups"
    assert processing_queue_module.backup_barrier.backup_active is False


@pytest.mark.asyncio
async def test_worker_defers_claimed_job_when_backup_barrier_wins_race(sqlite_sessionmaker, monkeypatch):
    async with sqlite_sessionmaker() as db:
        job, _created = await crud.create_processing_job(db, job_type="clean_book", resource_lane="cpu")
        job_id = job.id

    # The first wait permits polling, but a backup is active by the time the
    # worker has claimed the job. Stop at the second wait, after deferral.
    barrier = SimpleNamespace(
        backup_active=True,
        wait_until_writes_allowed=AsyncMock(side_effect=[None, asyncio.CancelledError]),
    )
    monkeypatch.setattr(processing_queue_module, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(processing_queue_module, "backup_barrier", barrier)
    queue = ProcessingQueue()
    execute = AsyncMock()
    monkeypatch.setattr(queue, "_execute_with_heartbeat", execute)

    with pytest.raises(asyncio.CancelledError):
        await queue._run("cpu", 1)

    execute.assert_not_awaited()
    async with sqlite_sessionmaker() as db:
        deferred = await db.get(ProcessingJob, job_id)
        assert deferred.status == "queued"
        assert deferred.attempt_count == 0
        assert deferred.lease_owner is None
        assert deferred.lease_expires_at is None
        assert deferred.progress_detail == "Waiting for library backup to finish"


@pytest.mark.asyncio
async def test_processing_job_claim_is_exclusive_and_heartbeated(sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        job, _created = await crud.create_processing_job(
            db,
            job_type="clean_book",
            resource_lane="cpu",
        )

    async with sqlite_sessionmaker() as db:
        claimed = await crud.claim_processing_job(
            db,
            resource_lane="cpu",
            lease_owner="worker-one",
            lease_seconds=30,
        )
        assert claimed is not None
        assert claimed.id == job.id
        first_expiry = claimed.lease_expires_at

    async with sqlite_sessionmaker() as db:
        assert (
            await crud.claim_processing_job(
                db,
                resource_lane="cpu",
                lease_owner="worker-two",
                lease_seconds=30,
            )
            is None
        )
        assert await crud.heartbeat_processing_job(
            db,
            job.id,
            lease_owner="worker-one",
            lease_seconds=60,
        )
        renewed = await db.get(ProcessingJob, job.id)
        assert renewed.lease_expires_at > first_expiry


@pytest.mark.asyncio
async def test_expired_processing_job_is_reclaimed_until_attempt_limit(sqlite_sessionmaker):
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    async with sqlite_sessionmaker() as db:
        job, _created = await crud.create_processing_job(
            db,
            job_type="refresh_book",
            resource_lane="maintenance",
            max_attempts=2,
        )
        job.status = "running"
        job.attempt_count = 1
        job.lease_owner = "dead-worker"
        job.lease_expires_at = expired
        await db.commit()
        job_id = job.id

    async with sqlite_sessionmaker() as db:
        reclaimed = await crud.claim_processing_job(
            db,
            resource_lane="maintenance",
            lease_owner="replacement-worker",
            lease_seconds=30,
        )
        assert reclaimed is not None
        assert reclaimed.id == job_id
        assert reclaimed.attempt_count == 2
        reclaimed.lease_expires_at = expired
        await db.commit()

    async with sqlite_sessionmaker() as db:
        _canceled, exhausted = await crud.recover_abandoned_processing_jobs(db)
        assert exhausted == 1
        failed = await db.get(ProcessingJob, job_id)
        assert failed.status == "error"
        assert "retry limit" in failed.error


@pytest.mark.asyncio
async def test_processing_failure_backoff_and_manual_retry_reset(sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        job, _created = await crud.create_processing_job(
            db,
            job_type="metadata_sync",
            resource_lane="llm",
        )
        claimed = await crud.claim_processing_job(
            db,
            resource_lane="llm",
            lease_owner="worker",
            lease_seconds=30,
        )
        assert claimed is not None
        status = await crud.fail_processing_job(
            db,
            job.id,
            "provider unavailable",
            lease_owner="worker",
            retry_backoff_seconds=5,
        )
        assert status == "queued"
        await db.refresh(job)
        available_at = job.available_at.replace(tzinfo=timezone.utc)
        assert available_at > datetime.now(timezone.utc)

        job.status = "error"
        await db.commit()
        retried = await crud.retry_processing_job(db, job.id)
        assert retried is not None
        assert retried.attempt_count == 0
        retry_at = retried.available_at.replace(tzinfo=timezone.utc)
        assert retry_at <= datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_active_processing_job_deduplication_includes_running(sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        first, created = await crud.create_processing_job(
            db,
            job_type="clean_all",
            resource_lane="cpu",
            dedupe_key="clean-all",
        )
        assert created
        first.status = "running"
        await db.commit()

        duplicate, created = await crud.create_processing_job(
            db,
            job_type="clean_all",
            resource_lane="cpu",
            dedupe_key="clean-all",
        )
        assert not created
        assert duplicate.id == first.id


@pytest.mark.asyncio
async def test_processing_jobs_are_listed_in_execution_order(sqlite_sessionmaker):
    now = datetime.now(timezone.utc)
    async with sqlite_sessionmaker() as db:
        running_first = ProcessingJob(
            job_type="clean_book",
            status="running",
            started_at=now - timedelta(minutes=10),
            created_at=now - timedelta(minutes=20),
        )
        queued_delayed = ProcessingJob(
            job_type="refresh_book",
            status="queued",
            available_at=now + timedelta(minutes=5),
            created_at=now - timedelta(minutes=15),
        )
        terminal_older = ProcessingJob(
            job_type="metadata_sync",
            status="completed",
            created_at=now - timedelta(minutes=8),
        )
        queued_next = ProcessingJob(
            job_type="audiobook_pipeline",
            status="queued",
            available_at=now,
            created_at=now - timedelta(minutes=5),
        )
        running_second = ProcessingJob(
            job_type="clean_all",
            status="running",
            started_at=now - timedelta(minutes=2),
            created_at=now - timedelta(minutes=3),
        )
        terminal_newer = ProcessingJob(
            job_type="refresh_all",
            status="error",
            created_at=now - timedelta(minutes=1),
        )
        db.add_all(
            [
                running_first,
                queued_delayed,
                terminal_older,
                queued_next,
                running_second,
                terminal_newer,
            ]
        )
        await db.commit()

        rows = await crud.get_processing_jobs(db)

    assert [job.id for job, _book_title in rows] == [
        running_first.id,
        running_second.id,
        queued_next.id,
        queued_delayed.id,
        terminal_newer.id,
        terminal_older.id,
    ]


@pytest.mark.asyncio
async def test_canceled_abandoned_job_is_not_reclaimed(sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        job, _created = await crud.create_processing_job(
            db,
            job_type="refresh_all",
            resource_lane="maintenance",
        )
        claimed = await crud.claim_processing_job(
            db,
            resource_lane="maintenance",
            lease_owner="stopped-worker",
            lease_seconds=30,
        )
        assert claimed is not None
        await crud.request_processing_job_cancel(db, job.id)
        claimed.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db.commit()

    async with sqlite_sessionmaker() as db:
        canceled, _exhausted = await crud.recover_abandoned_processing_jobs(db)
        assert canceled == 1
        recovered = await db.get(ProcessingJob, job.id)
        assert recovered.status == "canceled"
        assert recovered.lease_owner is None
        assert (
            await crud.claim_processing_job(
                db,
                resource_lane="maintenance",
                lease_owner="replacement-worker",
                lease_seconds=30,
            )
            is None
        )


@pytest.mark.asyncio
async def test_audiobook_import_automatically_queues_whisper_alignment(
    sqlite_sessionmaker,
    monkeypatch,
):
    async with sqlite_sessionmaker() as db:
        book = Book(
            title="Auto Align",
            author="Narrator",
            source_type=SourceType.epub,
            immutable_path="library/auto-align-immutable.epub",
            current_path="library/auto-align.epub",
            content_version=1,
        )
        db.add(book)
        await db.flush()
        chapter = AudiobookChapter(
            book_id=book.id,
            chapter_number=1,
            title="Chapter 1",
            stable_chapter_key="auto-align-chapter",
            spine_order=0,
        )
        edition = ImportedAudiobook(
            book_id=book.id,
            name="Human narration",
            status="queued",
        )
        db.add_all([chapter, edition])
        await db.flush()
        db.add(
            AudiobookSettings(
                transcription_provider="whisperx",
                transcription_base_url="http://whisper:8002",
            )
        )
        job = ProcessingJob(
            job_type="import_audiobook",
            status="running",
            book_id=book.id,
            target_type="imported_audiobook",
            target_id=edition.id,
            payload={"auto_align": True},
            dedupe_key=f"import_audiobook:imported_audiobook:{edition.id}",
        )
        db.add(job)
        await db.commit()

    async def fake_import(edition_id, db):
        selected = await db.get(ImportedAudiobook, edition_id)
        selected.status = "ready"
        selected.matched_content_version = 1
        db.add(
            ImportedAudiobookTrack(
                imported_audiobook_id=edition_id,
                matched_chapter_id=chapter.id,
                sequence_order=1,
                title="Chapter 1",
                audio_file_path="library/audio.m4b",
                media_type="audio/mp4",
                source_start_ms=0,
                source_end_ms=10_000,
                duration_ms=10_000,
            )
        )
        await db.commit()

    monkeypatch.setattr(processing_queue_module, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(processing_queue_module, "process_import", fake_import)
    queue = ProcessingQueue()

    detail = await queue._execute(job)

    assert detail.endswith("timestamp alignment queued")
    async with sqlite_sessionmaker() as db:
        alignment_job = (
            await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.job_type == "align_imported_audiobook",
                    ProcessingJob.target_id == edition.id,
                )
            )
        ).scalar_one()
        assert alignment_job.parent_job_id == job.id


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
