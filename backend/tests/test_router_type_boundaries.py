"""Regression coverage for nullable data exposed by static checking."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from backend.app import models, schemas
from backend.app.routers import audiobook, cleaning, dashboard, processing, reader, scheduler


def test_dashboard_handles_missing_book_metadata():
    book = models.Book(id=1, title=None, author=None, source_type=models.SourceType.epub)

    item = dashboard._book_item(book, "missing_files")

    assert item.book_id == 1
    assert item.title == ""
    assert item.author == ""


def test_dashboard_file_issue_handles_missing_book_metadata():
    item = dashboard._file_item(
        {"book_id": 1, "title": None, "author": None, "issue": "missing_current_path"}, can_retry_cover=True
    )

    assert item.title == ""
    assert item.author == ""
    assert item.path is None
    assert item.can_retry_cover is True


@pytest.mark.asyncio
@pytest.mark.parametrize("source_type", [models.SourceType.web, models.SourceType.epub])
async def test_refresh_job_requires_web_source_enum(db, source_type):
    book = models.Book(title="Refreshable", source_type=source_type, source_url="https://example.com/book")
    db.add(book)
    await db.commit()
    await db.refresh(book)
    request = schemas.ProcessingJobRequest(job_type="refresh_book", book_ids=[book.id])

    if source_type == models.SourceType.web:
        result = await processing.create_processing_jobs(request, db)
        assert len(result.jobs) == 1
        assert result.jobs[0].book_id == book.id
        assert result.jobs[0].job_type == "refresh_book"
    else:
        with pytest.raises(HTTPException) as error:
            await processing.create_processing_jobs(request, db)
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_scheduler_history_handles_missing_book_title(monkeypatch):
    timestamp = datetime.now(timezone.utc)
    log = models.BookLog(id=1, book_id=1, entry_type="checked", timestamp=timestamp)
    monkeypatch.setattr(
        scheduler.crud,
        "get_book_logs_for_task",
        AsyncMock(return_value=(models.UpdateTask(id=1), [(log, None)])),
    )

    results = await scheduler.get_task_logs(1, AsyncMock())

    assert results[0].book_title == ""
    assert results[0].timestamp == timestamp


@pytest.mark.asyncio
async def test_cleaning_preview_rejects_book_without_original_epub(monkeypatch):
    monkeypatch.setattr(cleaning.crud, "get_book", AsyncMock(return_value=models.Book(id=1, immutable_path=None)))

    with pytest.raises(HTTPException) as error:
        await cleaning.preview_cleaning(1, cleaning.PreviewCleaningRequest(), AsyncMock())

    assert error.value.status_code == 404
    assert error.value.detail == "Original EPUB not available"


@pytest.mark.asyncio
async def test_locked_provider_requires_settings_for_non_stub_provider(monkeypatch):
    monkeypatch.setattr(audiobook.crud.audiobook, "get_audiobook_settings", AsyncMock(return_value=None))
    monkeypatch.setattr(audiobook.crud.audiobook, "lock_book_tts_provider", AsyncMock(return_value="qwen3"))

    with pytest.raises(HTTPException) as error:
        await audiobook._settings_for_locked_book_provider(AsyncMock(), 1)

    assert error.value.status_code == 409
    assert "settings are required" in error.value.detail


@pytest.mark.asyncio
async def test_locked_stub_provider_still_works_without_settings(monkeypatch):
    monkeypatch.setattr(audiobook.crud.audiobook, "get_audiobook_settings", AsyncMock(return_value=None))
    monkeypatch.setattr(audiobook.crud.audiobook, "lock_book_tts_provider", AsyncMock(return_value="stub"))

    assert await audiobook._settings_for_locked_book_provider(AsyncMock(), 1) == ("stub", None)


@pytest.mark.asyncio
async def test_character_deleted_during_update_returns_not_found(monkeypatch):
    existing = models.AudiobookCharacter(id=1, book_id=1)
    monkeypatch.setattr(audiobook.crud.audiobook, "get_character", AsyncMock(return_value=existing))
    monkeypatch.setattr(audiobook.crud.audiobook, "update_character", AsyncMock(return_value=None))
    monkeypatch.setattr(audiobook, "_get_audiobook_book_or_404", AsyncMock(return_value=models.Book(id=1)))
    propagate = AsyncMock()
    monkeypatch.setattr(audiobook.crud.audiobook, "propagate_character_profile_across_series", propagate)

    with pytest.raises(HTTPException) as error:
        await audiobook.update_character(1, audiobook.CharacterUpdate(), AsyncMock())

    assert error.value.status_code == 404
    propagate.assert_not_called()


@pytest.mark.asyncio
async def test_smil_rejects_cue_chapter_without_content_file(monkeypatch):
    chapter = models.AudiobookChapter(id=1, content_file_name=None)
    track = models.ImportedAudiobookTrack(id=1, matched_chapter_id=1)
    edition = models.ImportedAudiobook(id=1)
    sentence = models.AudiobookSentence(chapter_id=1)
    monkeypatch.setattr(audiobook, "_get_imported_track_or_404", AsyncMock(return_value=(edition, track)))
    monkeypatch.setattr(audiobook, "_canonical_audio_track_id", AsyncMock(return_value=1))
    rows = Mock()
    rows.all.return_value = [(models.ImportedAudiobookCue(), sentence)]
    chapters = Mock()
    chapters.scalars.return_value.all.return_value = [chapter]
    db = AsyncMock()
    db.get.return_value = chapter
    db.execute.side_effect = [rows, chapters]

    with pytest.raises(HTTPException) as error:
        await audiobook.get_imported_track_smil(1, 1, db)

    assert error.value.status_code == 404
    assert error.value.detail == "Matched chapter has no EPUB content file"


@pytest.mark.asyncio
async def test_reader_smil_accepts_memoryview_response_body(monkeypatch):
    monkeypatch.setattr(
        reader.audiobook_router,
        "get_imported_track_smil",
        AsyncMock(return_value=SimpleNamespace(body=memoryview(b"/api/imported-audiobooks/1/tracks/2/audio"))),
    )

    response = await reader.get_reader_human_audiobook_smil(1, 2, AsyncMock())

    assert response.body == b"/reader/human-audiobooks/1/tracks/2/audio"
