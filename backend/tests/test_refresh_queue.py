"""Tests for RefreshQueue, run_book_refresh, and crud.get_pending_refresh_books."""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.app import crud, models, schemas
from backend.app.database import Base
from backend.app.services import refresh_queue as refresh_queue_mod
from backend.app.services import web_novel as web_novel_mod

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
AsyncTestingSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


@pytest_asyncio.fixture(scope="function")
async def db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncTestingSessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


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


class _RecordingQueue:
    """Captures book_ids as run_book_refresh is invoked from the worker."""

    def __init__(self):
        self.calls: list[int] = []
        self.started = asyncio.Event()

    async def __call__(self, book_id: int) -> None:
        self.calls.append(book_id)
        self.started.set()


@pytest.mark.asyncio
async def test_refresh_queue_enqueue_is_idempotent(monkeypatch):
    recorder = _RecordingQueue()
    # Block the worker so we can observe set membership mid-flight.
    block = asyncio.Event()

    async def slow_refresh(book_id: int) -> None:
        recorder.calls.append(book_id)
        await block.wait()

    monkeypatch.setattr(refresh_queue_mod, "run_book_refresh", slow_refresh)
    queue = refresh_queue_mod.RefreshQueue()
    await queue.start()
    try:
        assert await queue.enqueue(42) is True
        # While the worker is blocked on the first item, a second enqueue for
        # the same id should short-circuit.
        assert await queue.enqueue(42) is False
        # A different id should still be accepted.
        assert await queue.enqueue(43) is True
    finally:
        block.set()
        await queue.stop()

    # Both unique ids were eventually processed.
    assert sorted(recorder.calls) == [42, 43]


@pytest.mark.asyncio
async def test_refresh_queue_worker_invokes_run_book_refresh(monkeypatch):
    done = asyncio.Event()
    processed: list[int] = []

    async def fake_refresh(book_id: int) -> None:
        processed.append(book_id)
        done.set()

    monkeypatch.setattr(refresh_queue_mod, "run_book_refresh", fake_refresh)
    queue = refresh_queue_mod.RefreshQueue()
    await queue.start()
    try:
        await queue.enqueue(7)
        await asyncio.wait_for(done.wait(), timeout=1)
    finally:
        await queue.stop()

    assert processed == [7]


@pytest.mark.asyncio
async def test_refresh_queue_continues_after_worker_exception(monkeypatch):
    """An exception inside run_book_refresh must not kill the worker loop."""
    second_done = asyncio.Event()
    seen: list[int] = []

    async def fake_refresh(book_id: int) -> None:
        seen.append(book_id)
        if book_id == 1:
            raise RuntimeError("boom")
        second_done.set()

    monkeypatch.setattr(refresh_queue_mod, "run_book_refresh", fake_refresh)
    queue = refresh_queue_mod.RefreshQueue()
    await queue.start()
    try:
        await queue.enqueue(1)
        await queue.enqueue(2)
        await asyncio.wait_for(second_done.wait(), timeout=1)
    finally:
        await queue.stop()

    assert seen == [1, 2]


@pytest.mark.asyncio
async def test_refresh_queue_requeue_pending_books_uses_crud(monkeypatch, db):
    queued = await _make_web_book(db, source_url="https://example.com/q")
    queued.refresh_status = "queued"
    processing = await _make_web_book(db, source_url="https://example.com/p")
    processing.refresh_status = "processing"
    idle = await _make_web_book(db, source_url="https://example.com/i")
    await db.commit()

    # Point the queue module's SessionLocal at the test database so
    # requeue_pending_books sees our fixture rows.
    monkeypatch.setattr(refresh_queue_mod, "SessionLocal", AsyncTestingSessionLocal)

    enqueued: list[int] = []

    async def fake_enqueue(self, book_id):
        enqueued.append(book_id)
        return True

    queue = refresh_queue_mod.RefreshQueue()
    monkeypatch.setattr(refresh_queue_mod.RefreshQueue, "enqueue", fake_enqueue)

    count = await queue.requeue_pending_books()

    assert count == 2
    assert sorted(enqueued) == sorted([queued.id, processing.id])
    assert idle.id not in enqueued


@pytest.mark.asyncio
async def test_run_book_refresh_marks_error_when_no_source_url(monkeypatch, db):
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

    monkeypatch.setattr(web_novel_mod, "SessionLocal", AsyncTestingSessionLocal)

    await web_novel_mod.run_book_refresh(book.id)

    refreshed = await crud.get_book(db, book_id=book.id)
    await db.refresh(refreshed)
    assert refreshed.refresh_status == "error"


@pytest.mark.asyncio
async def test_run_book_refresh_marks_error_when_download_fails(monkeypatch, db):
    book = await _make_web_book(
        db,
        source_url="https://example.com/story/fail",
        immutable_path="library/Author/immutable.epub",
        current_path="library/Author/current.epub",
    )
    await db.commit()

    monkeypatch.setattr(web_novel_mod, "SessionLocal", AsyncTestingSessionLocal)

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
async def test_run_book_refresh_swallows_missing_book(monkeypatch, db):
    """Worker should no-op cleanly when the book was deleted between enqueue and run."""
    monkeypatch.setattr(web_novel_mod, "SessionLocal", AsyncTestingSessionLocal)
    # Should not raise even though book 99999 does not exist.
    await web_novel_mod.run_book_refresh(99999)
