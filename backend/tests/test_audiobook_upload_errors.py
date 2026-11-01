"""Upload failures map to the right HTTP status and leave the edition in an error state."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.app.models import Book, ImportedAudiobook, ProcessingJob
from backend.app.routers import audiobook as audiobook_router


async def _seed_book(sqlite_sessionmaker) -> int:
    async with sqlite_sessionmaker() as db:
        book = Book(title="Upload Errors", author="Narrator", content_version=1)
        db.add(book)
        await db.commit()
        return book.id


async def _only_edition(sqlite_sessionmaker, book_id: int) -> ImportedAudiobook:
    async with sqlite_sessionmaker() as db:
        return (await db.execute(select(ImportedAudiobook).where(ImportedAudiobook.book_id == book_id))).scalar_one()


@pytest.fixture
def edition_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        audiobook_router,
        "imported_audiobook_dir",
        lambda book_id, edition_id: tmp_path / str(book_id) / str(edition_id),
    )
    return tmp_path


@pytest.mark.asyncio
async def test_upload_over_size_limit_returns_413(app_client, sqlite_sessionmaker, edition_dirs, monkeypatch):
    book_id = await _seed_book(sqlite_sessionmaker)
    monkeypatch.setattr(audiobook_router, "MAX_AUDIOBOOK_UPLOAD_BYTES", 4)

    response = app_client.post(
        f"/api/books/{book_id}/audiobook/imports",
        files={"files": ("book.m4b", b"more-than-four-bytes", "audio/mp4")},
    )

    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"]
    edition = await _only_edition(sqlite_sessionmaker, book_id)
    assert edition.status == "error"
    assert list((edition_dirs / str(book_id) / str(edition.id) / "incoming").iterdir()) == []


@pytest.mark.asyncio
async def test_upload_failure_unrelated_to_size_is_not_reported_as_413(
    app_client, sqlite_sessionmaker, edition_dirs, monkeypatch
):
    book_id = await _seed_book(sqlite_sessionmaker)

    async def broken_queue_processing_job(**_kwargs):
        raise RuntimeError("processing queue unavailable")

    monkeypatch.setattr(audiobook_router, "queue_processing_job", broken_queue_processing_job)

    response = app_client.post(
        f"/api/books/{book_id}/audiobook/imports",
        files={"files": ("book.m4b", b"audio", "audio/mp4")},
    )

    assert response.status_code == 500
    assert "processing queue unavailable" in response.json()["detail"]
    edition = await _only_edition(sqlite_sessionmaker, book_id)
    assert edition.status == "error"
    assert edition.error == "processing queue unavailable"
    # The upload itself completed, so the received files stay available for a retry.
    assert (edition_dirs / str(book_id) / str(edition.id) / "incoming" / "book.m4b").read_bytes() == b"audio"
    async with sqlite_sessionmaker() as db:
        assert (await db.execute(select(ProcessingJob))).scalars().all() == []


@pytest.mark.asyncio
async def test_upload_write_failure_returns_500_and_discards_partial_files(
    app_client, sqlite_sessionmaker, edition_dirs, monkeypatch
):
    book_id = await _seed_book(sqlite_sessionmaker)

    async def failing_stream(_upload, _destination, _remaining):
        raise OSError("No space left on device")

    monkeypatch.setattr(audiobook_router, "stream_upload_to_path", failing_stream)

    response = app_client.post(
        f"/api/books/{book_id}/audiobook/imports",
        files={"files": ("book.m4b", b"audio", "audio/mp4")},
    )

    assert response.status_code == 500
    edition = await _only_edition(sqlite_sessionmaker, book_id)
    assert edition.status == "error"
    assert edition.progress_detail == "Upload failed"
