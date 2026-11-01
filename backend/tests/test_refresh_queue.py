"""Tests for run_book_refresh and crud.get_pending_refresh_books."""

import pytest

from backend.app import crud, models, schemas
from backend.app.services import web_novel as web_novel_mod


async def _make_web_book(db, **overrides):
    payload = dict(
        title="Web Book",
        author="Author",
        source_url="https://example.com/story/1",
        source_type=models.SourceType.web,
    )
    payload.update(overrides)
    return await crud.create_book(db, schemas.BookCreate(**payload))


@pytest.mark.asyncio
async def test_get_pending_refresh_books_returns_queued_and_processing(db):
    queued = await _make_web_book(db, source_url="https://example.com/a")
    queued.refresh_status = "queued"
    processing = await _make_web_book(db, source_url="https://example.com/b")
    processing.refresh_status = "processing"
    errored = await _make_web_book(db, source_url="https://example.com/c")
    errored.refresh_status = "error"
    idle = await _make_web_book(db, source_url="https://example.com/d")
    # Non-web book with a queued-looking status should not appear.
    non_web = await crud.create_book(
        db,
        schemas.BookCreate(
            title="Not web",
            author="Author",
            source_type=models.SourceType.epub,
            immutable_path="p1",
            current_path="p2",
        ),
    )
    non_web.refresh_status = "queued"
    await db.commit()

    pending = await crud.get_pending_refresh_books(db)
    ids = {book.id for book in pending}

    assert queued.id in ids
    assert processing.id in ids
    assert errored.id not in ids
    assert idle.id not in ids
    assert non_web.id not in ids


@pytest.mark.asyncio
async def test_run_book_refresh_marks_error_when_no_source_url(monkeypatch, db, sqlite_sessionmaker):
    # Build a web book with no source_url (sneak past the schema by creating
    # it as epub first and then mutating source_type).
    book = await crud.create_book(
        db,
        schemas.BookCreate(
            title="No URL",
            author="Author",
            source_type=models.SourceType.epub,
            immutable_path="p1",
            current_path="p2",
        ),
    )
    book.source_type = models.SourceType.web
    book.source_url = None
    await db.commit()

    monkeypatch.setattr(web_novel_mod, "SessionLocal", sqlite_sessionmaker)

    await web_novel_mod.run_book_refresh(book.id)

    refreshed = await crud.get_book(db, book_id=book.id)
    await db.refresh(refreshed)
    assert refreshed.refresh_status == "error"


@pytest.mark.asyncio
async def test_run_book_refresh_marks_error_when_download_fails(monkeypatch, db, sqlite_sessionmaker):
    book = await _make_web_book(
        db,
        source_url="https://example.com/story/fail",
        immutable_path="library/Author/immutable.epub",
        current_path="library/Author/current.epub",
    )
    await db.commit()

    monkeypatch.setattr(web_novel_mod, "SessionLocal", sqlite_sessionmaker)

    def broken_word_count(path):
        raise RuntimeError("cannot read epub")

    # get_epub_word_and_chapter_count is the first call that touches disk in
    # the "has existing paths" branch — failing it short-circuits the job into
    # the error handler without requiring real EPUB files on disk.
    monkeypatch.setattr(web_novel_mod, "get_epub_word_and_chapter_count", broken_word_count)

    await web_novel_mod.run_book_refresh(book.id)

    refreshed = await crud.get_book(db, book_id=book.id)
    await db.refresh(refreshed)
    assert refreshed.refresh_status == "error"


@pytest.mark.asyncio
async def test_run_book_refresh_swallows_missing_book(monkeypatch, db, sqlite_sessionmaker):
    """Worker should no-op cleanly when the book was deleted between enqueue and run."""
    monkeypatch.setattr(web_novel_mod, "SessionLocal", sqlite_sessionmaker)
    # Should not raise even though book 99999 does not exist.
    await web_novel_mod.run_book_refresh(99999)
