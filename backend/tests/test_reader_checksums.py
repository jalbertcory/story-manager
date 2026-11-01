"""Reader audiobook file I/O stays off the event loop and checksums are stored, not recomputed."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update

from backend.app import models
from backend.app.routers import books as books_router
from backend.app.routers import reader
from backend.app.services import audiobook_publication, library_paths
from backend.app.services import processing_queue as processing_queue_module
from backend.app.services.processing_queue import ProcessingQueue

SMIL = b"""<?xml version="1.0" encoding="UTF-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" version="3.0"><body><seq>
  <par><text src="Text/chapter.xhtml#sentence-1"/>
  <audio src="ch0001.mp3" clipBegin="00:00:00.000" clipEnd="00:00:01.250"/></par>
</seq></body></smil>"""


def _relative(library: Path, path: Path) -> str:
    return str(path.relative_to(library.parent))


@pytest.fixture
def reader_auth(app_client):
    token = app_client.post("/api/reader-keys", json={"label": "Checksum tests"}).json()["token"]
    return ("reader", token)


@pytest.fixture
def library(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(reader, "LIBRARY_PATH", library)
    monkeypatch.setattr(library_paths, "LIBRARY_PATH", library)
    monkeypatch.setattr(audiobook_publication, "LIBRARY_PATH", library)
    audiobook_publication._cached_reader_smil.cache_clear()
    return library


def _write_assets(library: Path, book_id: int) -> tuple[Path, Path, Path]:
    output = library / "audiobooks" / str(book_id)
    output.mkdir(parents=True)
    text_path = output / "working.epub"
    audio_path = output / "ch0001.mp3"
    smil_path = output / "ch0001.smil"
    text_path.write_bytes(b"reader-text-epub")
    audio_path.write_bytes(b"0123456789abcdef")
    smil_path.write_bytes(SMIL)
    return text_path, audio_path, smil_path


async def _add_legacy_book(db, library: Path, book_id: int, **chapter_fields) -> None:
    """A publication from before sizes and hashes were stored: every checksum column is null."""
    text_path, audio_path, smil_path = _write_assets(library, book_id)
    db.add(
        models.Book(
            id=book_id,
            title="Legacy Audio",
            author="Reader",
            source_type=models.SourceType.epub,
            immutable_path=f"library/source-{book_id}.epub",
            current_path=f"library/current-{book_id}.epub",
            content_version=3,
            audiobook_enabled=True,
            audiobook_pipeline_status="complete",
            audiobook_revision=2,
            audiobook_publication_state="complete",
            audiobook_text_file_path=_relative(library, text_path),
        )
    )
    db.add(
        models.AudiobookChapter(
            id=book_id * 10,
            book_id=book_id,
            chapter_number=1,
            stable_chapter_key="src-chapter-one",
            source_href="Text/chapter.xhtml",
            content_file_name="Text/chapter.xhtml",
            title="Chapter One",
            spine_order=0,
            generation_state="ready",
            audio_revision=1,
            audio_file_path=_relative(library, audio_path),
            smil_file_path=_relative(library, smil_path),
            reader_audio_file_path=_relative(library, audio_path),
            reader_smil_file_path=_relative(library, smil_path),
            **chapter_fields,
        )
    )
    await db.commit()


def test_reader_smil_is_parsed_once_per_file_version(library, monkeypatch):
    smil_path = library / "overlay.smil"
    smil_path.write_bytes(SMIL)
    chapter = models.AudiobookChapter(
        reader_smil_file_path=_relative(library, smil_path),
        source_href="Text/chapter.xhtml",
    )
    calls = []
    original = audiobook_publication.reader_smil_bytes
    monkeypatch.setattr(
        audiobook_publication, "reader_smil_bytes", lambda source, href: calls.append(href) or original(source, href)
    )

    first = audiobook_publication.chapter_reader_smil_bytes(chapter)
    assert audiobook_publication.chapter_reader_smil_bytes(chapter) == first
    assert first == original(SMIL, "Text/chapter.xhtml")
    assert len(calls) == 1

    changed = SMIL.replace(b"sentence-1", b"sentence-9")
    smil_path.write_bytes(changed)
    stat = smil_path.stat()
    os.utime(smil_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert b"sentence-9" in audiobook_publication.chapter_reader_smil_bytes(chapter)
    assert len(calls) == 2


def test_reader_smil_is_missing_for_directories_and_absent_files(library):
    directory = library / "not-a-file"
    directory.mkdir()
    assert (
        audiobook_publication.chapter_reader_smil_bytes(
            models.AudiobookChapter(reader_smil_file_path=_relative(library, directory))
        )
        is None
    )
    assert (
        audiobook_publication.chapter_reader_smil_bytes(
            models.AudiobookChapter(reader_smil_file_path=_relative(library, library / "gone.smil"))
        )
        is None
    )


@pytest.mark.asyncio
async def test_manifest_serves_stored_checksums_without_reading_smil(
    app_client, reader_auth, sqlite_sessionmaker, library, monkeypatch
):
    async with sqlite_sessionmaker() as db:
        await _add_legacy_book(
            db,
            library,
            901,
            audio_size_bytes=16,
            audio_sha256="a" * 64,
            smil_size_bytes=123,
            smil_sha256="b" * 64,
        )
        book = await db.get(models.Book, 901)
        book.audiobook_text_size_bytes = 16
        book.audiobook_text_sha256 = "c" * 64
        await db.commit()

    def unexpected_io(*args, **kwargs):
        raise AssertionError("stored checksums must be served as-is")

    monkeypatch.setattr(reader, "chapter_reader_smil_bytes", unexpected_io)
    monkeypatch.setattr(reader, "sha256_file", unexpected_io)

    response = app_client.get("/reader/books/901/audiobook/manifest", auth=reader_auth)

    assert response.status_code == 200
    chapter = response.json()["chapters"][0]
    assert chapter["state"] == "ready"
    assert (chapter["audio_sha256"], chapter["smil_size_bytes"], chapter["smil_sha256"]) == ("a" * 64, 123, "b" * 64)
    assert response.json()["text"]["sha256"] == "c" * 64


@pytest.mark.asyncio
async def test_manifest_still_hashes_legacy_rows(app_client, reader_auth, sqlite_sessionmaker, library):
    async with sqlite_sessionmaker() as db:
        await _add_legacy_book(db, library, 902)

    response = app_client.get("/reader/books/902/audiobook/manifest", auth=reader_auth)

    assert response.status_code == 200
    reader_smil = audiobook_publication.reader_smil_bytes(SMIL, "Text/chapter.xhtml")
    chapter = response.json()["chapters"][0]
    assert chapter["audio_sha256"] == hashlib.sha256(b"0123456789abcdef").hexdigest()
    assert chapter["smil_size_bytes"] == len(reader_smil)
    assert chapter["smil_sha256"] == hashlib.sha256(reader_smil).hexdigest()
    assert response.json()["text"]["sha256"] == hashlib.sha256(b"reader-text-epub").hexdigest()


@pytest.mark.asyncio
async def test_backfill_records_legacy_checksums_once(app_client, reader_auth, sqlite_sessionmaker, library):
    async with sqlite_sessionmaker() as db:
        await _add_legacy_book(db, library, 903)
    before = app_client.get("/reader/books/903/audiobook/manifest", auth=reader_auth).json()

    async with sqlite_sessionmaker() as db:
        assert await audiobook_publication.backfill_reader_checksums(db) == 3
    async with sqlite_sessionmaker() as db:
        chapter = await db.get(models.AudiobookChapter, 9030)
        book = await db.get(models.Book, 903)
        reader_smil = audiobook_publication.reader_smil_bytes(SMIL, "Text/chapter.xhtml")
        assert chapter.audio_size_bytes == 16
        assert chapter.audio_sha256 == hashlib.sha256(b"0123456789abcdef").hexdigest()
        assert chapter.smil_size_bytes == len(reader_smil)
        assert chapter.smil_sha256 == hashlib.sha256(reader_smil).hexdigest()
        assert book.audiobook_text_size_bytes == len(b"reader-text-epub")
        assert book.audiobook_text_sha256 == hashlib.sha256(b"reader-text-epub").hexdigest()
        assert await audiobook_publication.backfill_reader_checksums(db) == 0

    # Recording the checksums changes nothing a reader sees.
    assert app_client.get("/reader/books/903/audiobook/manifest", auth=reader_auth).json() == before


@pytest.mark.asyncio
async def test_backfill_skips_missing_files_and_republished_chapters(sqlite_sessionmaker, library, monkeypatch):
    async with sqlite_sessionmaker() as db:
        await _add_legacy_book(db, library, 904)
        await _add_legacy_book(db, library, 905)
    (library / "audiobooks" / "904" / "ch0001.mp3").unlink()
    republished = "library/audiobooks/905/reader/overlay-v2.smil"
    real_to_thread = asyncio.to_thread

    async def publish_while_hashing(func, *args, **kwargs):
        # A publish moves chapter 9050 to new files while the backfill hashes its old SMIL.
        if func is audiobook_publication.chapter_reader_smil_bytes and args[0].id == 9050:
            async with sqlite_sessionmaker() as other:
                await other.execute(
                    update(models.AudiobookChapter)
                    .where(models.AudiobookChapter.id == 9050)
                    .values(reader_smil_file_path=republished)
                )
                await other.commit()
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", publish_while_hashing)
    async with sqlite_sessionmaker() as db:
        await audiobook_publication.backfill_reader_checksums(db)
    monkeypatch.undo()

    async with sqlite_sessionmaker() as db:
        missing_audio = await db.get(models.AudiobookChapter, 9040)
        assert missing_audio.audio_sha256 is None
        assert missing_audio.smil_sha256 is not None
        moved = await db.get(models.AudiobookChapter, 9050)
        assert moved.reader_smil_file_path == republished
        assert moved.smil_sha256 is None


@pytest.mark.asyncio
async def test_backfill_handler_reports_progress(monkeypatch):
    progress = AsyncMock()
    backfill = AsyncMock(return_value=4)
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(processing_queue_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(processing_queue_module.crud, "update_processing_job_progress", progress)
    monkeypatch.setattr(processing_queue_module, "backfill_reader_checksums", backfill)

    summary = await ProcessingQueue()._execute(SimpleNamespace(id=7, job_type="backfill_reader_checksums", payload={}))

    assert summary == "Recorded 4 reader audiobook checksums"
    backfill.assert_awaited_once_with(session)
    assert progress.await_args_list[-1].kwargs["detail"] == "Recorded 4 checksums"


@pytest.mark.asyncio
async def test_permanent_delete_removes_files_in_a_worker_thread(library, monkeypatch):
    book_file = library / "book.epub"
    book_file.write_bytes(b"epub")
    audiobook_dir = library / "audiobooks" / "906"
    (audiobook_dir / "reader").mkdir(parents=True)
    (audiobook_dir / "reader" / "audio.mp3").write_bytes(b"mp3")
    monkeypatch.setattr(books_router, "LIBRARY_PATH", library)
    threads = []

    async def to_thread(func, *args, **kwargs):
        threads.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", to_thread)
    monkeypatch.setattr(books_router.crud, "delete_book", AsyncMock())
    book = models.Book(id=906, immutable_path=_relative(library, book_file), current_path=None, cover_path=None)

    await books_router._permanently_delete_book(AsyncMock(), book)

    assert threads == [books_router._remove_book_files]
    assert not book_file.exists()
    assert not audiobook_dir.exists()
