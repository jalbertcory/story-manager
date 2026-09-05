"""Audio-only upload, splitting, publication, and retry regression coverage."""

import shutil
import subprocess
from unittest.mock import AsyncMock
from starlette.requests import Request

import pytest
from sqlalchemy import select

from backend.app import crud
from backend.app.models import Book, ImportedAudiobook, ImportedAudiobookTrack, ProcessingJob, SourceType
from backend.app.routers import audiobook as audiobook_router, reader
from backend.app.services import audiobook_import
from backend.app.services.library_health import inspect_library_files


@pytest.mark.asyncio
async def test_audio_only_upload_split_and_reader_access(app_client, sqlite_sessionmaker, tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg and ffprobe are required")
    library = tmp_path / "library"
    library.mkdir()
    for module in (audiobook_router, audiobook_import, reader):
        monkeypatch.setattr(module, "LIBRARY_PATH", library)
    ingest = AsyncMock(side_effect=AssertionError("Audio-only books must not ingest EPUBs"))
    monkeypatch.setattr(audiobook_import, "ingest_epub", ingest)
    audio = tmp_path / "book.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            "2",
            "-q:a",
            "9",
            str(audio),
        ],
        check=True,
    )
    cue = (
        'FILE "book.mp3" MP3\n'
        'TRACK 1 AUDIO\n TITLE "Chapter 1"\n INDEX 01 0:00:00\n'
        'TRACK 2 AUDIO\n TITLE "Chapter 2"\n INDEX 01 0:01:00\n'
    )
    response = app_client.post(
        "/api/audiobooks/upload",
        data={"title": "Only Audio", "author": "An Author"},
        files=[
            ("files", ("book.mp3", audio.read_bytes(), "audio/mpeg")),
            ("files", ("book.cue", cue.encode(), "text/plain")),
        ],
    )
    assert response.status_code == 200, response.text
    edition_id, book_id = response.json()["id"], response.json()["book_id"]
    async with sqlite_sessionmaker() as db:
        book = await db.get(Book, book_id)
        assert book.source_type == SourceType.audiobook
        assert book.current_path is None and book.immutable_path is None
        assert not book.audiobook_enabled
        book.series = "Audio Series"
        await db.commit()
        assert not inspect_library_files([book], library_path=library)
        assert not await crud.get_all_reader_books(db)
        job = (await db.execute(select(ProcessingJob).where(ProcessingJob.target_id == edition_id))).scalar_one()
        assert job.payload == {"auto_align": False}
        await audiobook_import.process_import(edition_id, db)
        edition = await db.get(ImportedAudiobook, edition_id)
        assert edition.status == "ready", edition.error
        tracks = list(
            (await db.execute(select(ImportedAudiobookTrack).order_by(ImportedAudiobookTrack.sequence_order))).scalars()
        )
        assert [track.title for track in tracks] == ["Chapter 1", "Chapter 2"]
        assert all(track.matched_chapter_id is None for track in tracks)
        assert len({track.audio_file_path for track in tracks}) == 2
        assert all((library.parent / track.audio_file_path).is_file() for track in tracks)
        assert [item.id for item in await crud.get_all_reader_books(db)] == [book_id]
        assert (await crud.get_reader_series(db))[0]["book_count"] == 1
        assert [item.id for item in await crud.search_reader_books(db, "Only Audio")] == [book_id]
        payload = reader._reader_book_payload(
            book,
            Request({"type": "http", "scheme": "http", "server": ("testserver", 80), "path": "/", "headers": []}),
            has_human_audiobook=True,
        )
        assert payload["download_url"] is None and payload["has_text"] is False
        assert payload["audiobook_types"] == ["human_narrated"]
        assert "application/epub+zip" not in reader.ET.tostring(reader._build_book_entry(book, "http://testserver")).decode()
        editions = await reader.get_reader_human_audiobooks(book_id, db)
        assert len(editions[0].tracks) == 2
        assert all(track.smil_url is None for track in editions[0].tracks)
        track_id = tracks[0].id
        asset = await reader.get_reader_human_audiobook_audio(edition_id, track_id, db)
        assert asset.media_type == "audio/mpeg"
        rebuilt = await audiobook_import.rebuild_imported_audiobook(edition_id, db)
        assert rebuilt.track_count == 2 and rebuilt.matched_track_count == 0
        book.deleted_at = book.created_at
        await db.commit()
        assert not await crud.get_all_reader_books(db)
    ingest.assert_not_called()


@pytest.mark.asyncio
async def test_invalid_audio_only_upload_does_not_create_book(app_client, sqlite_sessionmaker):
    for title, filename in [("   ", "book.exe"), ("Title", "book.exe")]:
        response = app_client.post("/api/audiobooks/upload", data={"title": title}, files={"files": (filename, b"bad")})
        assert response.status_code == 400
    async with sqlite_sessionmaker() as db:
        assert not (await db.execute(select(Book))).scalars().all()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_migration", [True, False])
async def test_audio_only_upload_explains_missing_migration(missing_migration):
    from io import BytesIO
    from unittest.mock import Mock

    from fastapi import HTTPException, UploadFile
    from sqlalchemy.exc import DataError

    error = Exception('invalid input value for enum sourcetype: "audiobook"' if missing_migration else "other data error")
    error.sqlstate = "22P02"
    db = Mock()
    db.commit = AsyncMock(side_effect=DataError(None, None, error))
    db.rollback = AsyncMock()
    with pytest.raises(HTTPException if missing_migration else DataError) as caught:
        await audiobook_router.upload_audio_only_book(
            files=[UploadFile(filename="book.m4b", file=BytesIO(b"audio"))],
            title="Audio book",
            author="Author",
            name=None,
            source_paths=[],
            infer_title=False,
            db=db,
        )
    db.rollback.assert_awaited_once()
    if missing_migration:
        assert caught.value.status_code == 503
        assert "make migrate" in caught.value.detail
