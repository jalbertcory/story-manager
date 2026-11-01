"""Web novel add, refresh, detach and download completion."""

from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app import crud, models, schemas
from backend.app.services import web_novel
from api_harness import AsyncTestingSessionLocal, client, _assert_single_processing_job, create_dummy_epub


@pytest.mark.asyncio
async def test_add_web_novel(db_session):
    """
    Test adding a new web novel. The endpoint returns immediately with a pending record
    and records the actual download in the durable processing ledger.
    """
    payload = {"url": "http://example.com/story/123"}
    response = client.post("/api/books/add_web_novel", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["download_status"] == "pending"
    assert data["source_url"] == "http://example.com/story/123"
    assert data["immutable_path"] is None
    assert data["current_path"] is None
    async with AsyncTestingSessionLocal() as session:
        job = (
            await session.execute(select(models.ProcessingJob).where(models.ProcessingJob.book_id == data["id"]))
        ).scalar_one()
        assert job.job_type == "import_web_book"
        assert job.resource_lane == "maintenance"
        assert job.payload["source_url"] == "http://example.com/story/123"

    # Verify that the pending book appears in the book list
    response = client.get("/api/books")
    assert response.status_code == 200
    books = response.json()
    assert len(books) == 1
    assert books[0]["download_status"] == "pending"


@pytest.mark.asyncio
async def test_add_existing_web_novel(db_session):
    """
    Test that adding a book that already exists returns a 409 Conflict error.
    """
    # First, add a book to the database to simulate an existing entry
    async with AsyncTestingSessionLocal() as session:
        book_create = schemas.BookCreate(
            title="Existing Story",
            author="Existing Author",
            source_url="http://example.com/story/exists",
            immutable_path="library/immutable_Existing Story-Existing Author.epub",
            current_path="library/Existing Story-Existing Author.epub",
            source_type=models.SourceType.web,
        )
        await crud.create_book(session, book=book_create)

    # Attempt to add the same book again
    payload = {"url": "http://example.com/story/exists"}
    response = client.post("/api/books/add_web_novel", json=payload)

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_add_failed_web_novel_retries_placeholder(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Download failed",
                author="Pending",
                source_url="https://example.com/story/retry",
                source_type=models.SourceType.web,
                download_status="error",
            ),
        )

    response = client.post("/api/books/add_web_novel", json={"url": "https://example.com/story/retry"})

    assert response.status_code == 201
    data = response.json()
    assert data["id"] == book.id
    assert data["download_status"] == "pending"
    assert data["title"] == "https://example.com/story/retry"
    async with AsyncTestingSessionLocal() as session:
        job = (await session.execute(select(models.ProcessingJob).where(models.ProcessingJob.book_id == book.id))).scalar_one()
        assert job.job_type == "import_web_book"
        assert job.payload["source_url"] == "https://example.com/story/retry"


@pytest.mark.asyncio
async def test_refresh_book(db_session, mocker):
    """Refresh now enqueues a background job and returns 202 with queued status."""
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    author_dir = library_path / "Original Author"
    author_dir.mkdir(exist_ok=True)
    immutable_path = author_dir / "immutable_Original Title.epub"
    current_path = author_dir / "Original Title.epub"
    create_dummy_epub(immutable_path, "Original Title", "Original Author")
    current_path.write_bytes(immutable_path.read_bytes())

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Original Title",
                author="Original Author",
                source_url="http://example.com/story/refresh",
                immutable_path=str(immutable_path.relative_to(library_path.parent)),
                current_path=str(current_path.relative_to(library_path.parent)),
                source_type=models.SourceType.web,
            ),
        )

    response = client.post(f"/api/books/{book.id}/refresh")

    assert response.status_code == 202
    data = response.json()
    assert data["id"] == book.id
    assert data["refresh_status"] == "queued"
    # Book content should not have changed yet — only the status flipped.
    assert data["title"] == "Original Title"
    assert data["author"] == "Original Author"
    await _assert_single_processing_job("refresh_book", book.id)

    async with AsyncTestingSessionLocal() as session:
        persisted = await crud.get_book(session, book_id=book.id)
        assert persisted.refresh_status == "queued"

    # Clean up dummy files
    immutable_path.unlink()
    current_path.unlink()
    author_dir.rmdir()


@pytest.mark.asyncio
async def test_refresh_book_while_already_queued_is_idempotent(db_session, mocker):
    """A second refresh while one is still queued/processing should not flip status back."""

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Title",
                author="Author",
                source_url="http://example.com/story/already-queued",
                immutable_path="p1i",
                current_path="p1c",
                source_type=models.SourceType.web,
            ),
        )
        book.refresh_status = "processing"
        await session.commit()

    response = client.post(f"/api/books/{book.id}/refresh")

    assert response.status_code == 202
    data = response.json()
    # Still "processing" — the endpoint should not step on an in-flight job.
    assert data["refresh_status"] == "processing"
    await _assert_single_processing_job("refresh_book", book.id)


@pytest.mark.asyncio
async def test_refresh_book_no_source_url(db_session):
    """
    Test that refreshing a book with no source URL returns an error.
    """
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Uploaded Book",
                author="Uploader",
                immutable_path="p1i",
                current_path="p1c",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.post(f"/api/books/{book.id}/refresh")

    assert response.status_code == 400
    assert "does not have a source URL" in response.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_failed_placeholder_enqueues_refresh(db_session, mocker):
    """Refresh for a failed placeholder (no EPUB yet) enqueues a job without touching files."""

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Download failed",
                author="Pending",
                source_url="https://example.com/story/recovered",
                source_type=models.SourceType.web,
                download_status="error",
            ),
        )

    response = client.post(f"/api/books/{book.id}/refresh")

    assert response.status_code == 202
    data = response.json()
    assert data["id"] == book.id
    assert data["refresh_status"] == "queued"
    # download_status is not cleared at enqueue time — the worker clears it on success.
    assert data["download_status"] == "error"
    await _assert_single_processing_job("refresh_book", book.id)


@pytest.mark.asyncio
async def test_detach_book_source(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Imported FFF EPUB",
                author="Uploader",
                source_url="https://example.com/story/123",
                immutable_path="library/imported/original.epub",
                current_path="library/imported/current.epub",
                source_type=models.SourceType.web,
                download_status="pending",
            ),
        )

    response = client.post(f"/api/books/{book.id}/detach-source")

    assert response.status_code == 200
    data = response.json()
    assert data["source_type"] == "epub"
    assert data["source_url"] is None
    assert data["download_status"] is None
    assert data["immutable_path"] == "library/imported/original.epub"
    assert data["current_path"] == "library/imported/current.epub"


@pytest.mark.asyncio
async def test_detach_book_source_allows_missing_source_url_for_web_books(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Imported Web EPUB",
                author="Uploader",
                source_url=None,
                immutable_path="library/imported/original.epub",
                current_path="library/imported/current.epub",
                source_type=models.SourceType.web,
                download_status="pending",
            ),
        )

    response = client.post(f"/api/books/{book.id}/detach-source")

    assert response.status_code == 200
    data = response.json()
    assert data["source_type"] == "epub"
    assert data["source_url"] is None
    assert data["download_status"] is None


@pytest.mark.asyncio
async def test_detach_book_source_requires_epub_files(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Pending Web Novel",
                author="Pending",
                source_url="https://example.com/story/456",
                source_type=models.SourceType.web,
                download_status="pending",
            ),
        )

    response = client.post(f"/api/books/{book.id}/detach-source")

    assert response.status_code == 400
    assert "must have EPUB files" in response.json()["detail"]


@pytest.mark.asyncio
async def test_epub_upload_allowed_when_web_novel_has_same_title_and_author(db_session):
    """An epub upload is allowed even when a web novel with the same title and author already exists."""
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    title = "The Lighthouse at the Edge of Everything"
    author = "Cordelia Vance-Whitmore"

    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title=title,
                author=author,
                source_url="https://example.com/fiction/999",
                source_type=models.SourceType.web,
                immutable_path="library/web-novel-immutable.epub",
                current_path="library/web-novel-current.epub",
            ),
        )

    epub_filename = "lighthouse-edge-upload.epub"
    epub_filepath = library_path / epub_filename
    create_dummy_epub(epub_filepath, title, author)

    with open(epub_filepath, "rb") as f:
        response = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})
    assert response.status_code == 201

    epub_filepath.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_finish_web_novel_download_conflicts_with_existing_web_novel(db_session, mocker, tmp_path):
    """A web novel download is blocked when another web novel with the same title and author already exists."""
    library_path = tmp_path / "library"
    library_path.mkdir()
    mocker.patch("backend.app.services.web_novel.LIBRARY_PATH", library_path)

    title = "Sovereign of the Fractured Sky"
    author = "Rosamund Thielke"

    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title=title,
                author=author,
                source_url="https://example.com/fiction/100",
                source_type=models.SourceType.web,
                immutable_path="library/existing-immutable.epub",
                current_path="library/existing-current.epub",
            ),
        )
        placeholder = await crud.create_book(
            session,
            schemas.BookCreate(
                title="https://example.com/fiction/200",
                author="Pending",
                source_url="https://example.com/fiction/200",
                source_type=models.SourceType.web,
                download_status="pending",
            ),
        )
        placeholder_id = placeholder.id

    fake_epub = library_path / "Sovereign-of-the-Fractured-Sky-ex_200.epub"
    create_dummy_epub(fake_epub, title, author)

    mocker.patch(
        "backend.app.services.web_novel.download_web_novel",
        return_value=(fake_epub, {"title": title, "author": author, "series": None}),
    )
    mocker.patch("backend.app.services.web_novel.SessionLocal", AsyncTestingSessionLocal)

    await web_novel.finish_web_novel_download(placeholder_id, "https://example.com/fiction/200")

    async with AsyncTestingSessionLocal() as session:
        updated = await crud.get_book(session, placeholder_id)
    assert updated.download_status == "error"
    assert "Conflict" in updated.title


@pytest.mark.asyncio
async def test_finish_web_novel_download_allowed_when_epub_has_same_title_and_author(db_session, mocker, tmp_path):
    """A web novel download succeeds when only an epub (not a web novel) with the same title and author exists."""
    library_path = tmp_path / "library"
    library_path.mkdir()
    mocker.patch("backend.app.services.web_novel.LIBRARY_PATH", library_path)
    mocker.patch("backend.app.services.library_paths.LIBRARY_PATH", library_path)

    title = "Sovereign of the Fractured Sky"
    author = "Rosamund Thielke"

    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title=title,
                author=author,
                source_type=models.SourceType.epub,
                immutable_path="library/existing-epub-immutable.epub",
                current_path="library/existing-epub-current.epub",
            ),
        )
        placeholder = await crud.create_book(
            session,
            schemas.BookCreate(
                title="https://example.com/fiction/200",
                author="Pending",
                source_url="https://example.com/fiction/200",
                source_type=models.SourceType.web,
                download_status="pending",
            ),
        )
        placeholder_id = placeholder.id

    fake_epub = library_path / "Sovereign-of-the-Fractured-Sky-ex_200.epub"
    create_dummy_epub(fake_epub, title, author)

    mocker.patch(
        "backend.app.services.web_novel.download_web_novel",
        return_value=(fake_epub, {"title": title, "author": author, "series": None}),
    )
    mocker.patch("backend.app.services.web_novel.SessionLocal", AsyncTestingSessionLocal)
    mocker.patch("backend.app.services.web_novel.epub_editor.get_word_count", return_value=50000)
    mocker.patch("backend.app.services.web_novel.get_epub_word_and_chapter_count", return_value=(50000, 42))
    mocker.patch("backend.app.services.web_novel.get_and_save_epub_cover", return_value=None)
    mocker.patch("backend.app.services.web_novel.collect_cover", mocker.AsyncMock(return_value=None))
    mocker.patch("backend.app.services.web_novel.epub_editor.apply_book_cleaning", mocker.AsyncMock(return_value=False))
    mocker.patch("backend.app.services.web_novel.queue_metadata_sync_job", mocker.AsyncMock())

    await web_novel.finish_web_novel_download(placeholder_id, "https://example.com/fiction/200")

    async with AsyncTestingSessionLocal() as session:
        updated = await crud.get_book(session, placeholder_id)
    assert updated.download_status is None
    assert updated.title == title
    assert updated.author == author
