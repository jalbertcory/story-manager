"""Cleaning configs, processing, preview and reprocess-all routes."""

from pathlib import Path

import pytest

from backend.app import crud, epub_editor, models, schemas
from backend.app.services import library_paths
from api_harness import AsyncTestingSessionLocal, client, create_dummy_epub


def test_process_epub_handles_string_spine_entries(tmp_path: Path):
    immutable_path = tmp_path / "immutable.epub"
    current_path = tmp_path / "current.epub"
    create_dummy_epub(immutable_path, "Spine Book", "Spine Author")

    changed = epub_editor.process_epub(
        str(immutable_path),
        str(current_path),
        removed_chapters=[],
        content_selectors=["p"],
    )

    assert changed is not None
    chapters = epub_editor.get_chapters(str(current_path))
    assert "Introduction text." not in chapters[0]["content"]


@pytest.mark.asyncio
async def test_process_book(db_session):
    """
    Test processing a book to remove chapters and divs.
    """
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Process Book",
                author="Processor",
                immutable_path="library/immutable_process.epub",
                current_path="library/process.epub",
                source_type=models.SourceType.epub,
            ),
        )

    # Create dummy epub files
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    immutable_filepath = library_path / "immutable_process.epub"
    current_filepath = library_path / "process.epub"
    create_dummy_epub(immutable_filepath, "Process Book", "Processor")
    create_dummy_epub(current_filepath, "Process Book", "Processor")

    # Update the book with chapters to remove and content to clean
    update_payload = {
        "removed_chapters": ["chap_1.xhtml"],
        "content_selectors": ["p"],  # This will remove the paragraph
    }
    response = client.put(f"/api/books/{book.id}", json=update_payload)
    assert response.status_code == 200

    # Process the book
    response = client.post(f"/api/books/{book.id}/process")
    assert response.status_code == 200

    data = response.json()
    assert data["current_word_count"] == 0  # Intro and text removed

    immutable_filepath.unlink()
    current_filepath.unlink()


@pytest.mark.asyncio
async def test_create_cleaning_config(db_session):
    payload = {
        "name": "Example",
        "url_pattern": "example.com",
        "chapter_selectors": ["div.ann"],
        "content_selectors": ["div.note"],
    }
    response = client.post("/api/cleaning-configs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Example"

    response = client.get("/api/cleaning-configs")
    assert response.status_code == 200
    configs = response.json()
    assert len(configs) == 1
    assert configs[0]["url_pattern"] == "example.com"


@pytest.mark.asyncio
async def test_update_and_delete_cleaning_config(db_session):
    payload = {
        "name": "Example",
        "url_pattern": "example.com",
        "chapter_selectors": ["div.ann"],
        "content_selectors": ["div.note"],
    }
    response = client.post("/api/cleaning-configs", json=payload)
    assert response.status_code == 201
    config = response.json()
    config_id = config["id"]

    response = client.get(f"/api/cleaning-configs/{config_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Example"

    update_payload = {
        "name": "Updated",
        "chapter_selectors": ["div.new"],
    }
    response = client.put(f"/api/cleaning-configs/{config_id}", json=update_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated"
    assert data["chapter_selectors"] == ["div.new"]

    response = client.delete(f"/api/cleaning-configs/{config_id}")
    assert response.status_code == 204

    response = client.get("/api/cleaning-configs")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_restore_original_epub_clears_book_cleaning_rules(db_session, tmp_path, monkeypatch):
    from backend.app.routers import books as books_router

    library_path = (tmp_path / "library").resolve()
    monkeypatch.setattr(books_router, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(library_paths, "LIBRARY_PATH", library_path)
    library_path.mkdir(parents=True)
    immutable_path = library_path / "immutable_Original.epub"
    current_path = library_path / "Original.epub"
    create_dummy_epub(immutable_path, "Original", "Author")
    current_path.write_bytes(b"changed-current-copy")

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Original",
                author="Author",
                source_type=models.SourceType.epub,
                immutable_path=str(immutable_path.relative_to(library_path.parent)),
                current_path=str(current_path.relative_to(library_path.parent)),
                removed_chapters=["chapter-2.xhtml"],
                content_selectors=[".advertisement"],
            ),
        )

    response = client.post(f"/api/books/{book.id}/restore-original")

    assert response.status_code == 200
    assert response.json()["removed_chapters"] == []
    assert response.json()["content_selectors"] == []
    assert current_path.read_bytes() == immutable_path.read_bytes()
    revisions = client.get(f"/api/books/{book.id}/revisions").json()
    assert revisions[0]["action"] == "original_restored"
    assert revisions[0]["snapshot"]["removed_chapters"] == ["chapter-2.xhtml"]


@pytest.mark.asyncio
async def test_matched_config(db_session):
    """
    Test GET /api/books/{book_id}/matched-config returns matching configs.
    """
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Web Novel",
                author="Author",
                source_url="https://royalroad.com/fiction/123",
                immutable_path="pi_web",
                current_path="pc_web",
                source_type=models.SourceType.web,
            ),
        )
        book_no_url = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Local Book",
                author="Author",
                immutable_path="pi_local",
                current_path="pc_local",
                source_type=models.SourceType.epub,
            ),
        )

    # Create a cleaning config that matches the URL
    client.post(
        "/api/cleaning-configs",
        json={"name": "RoyalRoad", "url_pattern": "royalroad.com", "chapter_selectors": [], "content_selectors": ["div.note"]},
    )

    # Book with matching URL returns the config
    response = client.get(f"/api/books/{book.id}/matched-config")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "RoyalRoad"

    # Book without source URL returns empty list
    response = client.get(f"/api/books/{book_no_url.id}/matched-config")
    assert response.status_code == 200
    assert response.json() == []

    # Non-existent book returns 404
    response = client.get("/api/books/9999/matched-config")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reprocess_all(db_session):
    """
    Test POST /api/books/reprocess-all returns count of processed books.
    """
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book A", author="Author", immutable_path="rpi1", current_path="rpc1", source_type=models.SourceType.epub
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book B", author="Author", immutable_path="rpi2", current_path="rpc2", source_type=models.SourceType.epub
            ),
        )

    response = client.post("/api/books/reprocess-all")
    assert response.status_code == 200
    assert response.json() == {"status": "started"}


@pytest.mark.asyncio
async def test_reprocess_all_skips_unchanged_books_without_cleaning_rules(db_session):
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    author_dir = library_path / "Reprocess Author"
    author_dir.mkdir(exist_ok=True)
    immutable_path = author_dir / "immutable_reprocess.epub"
    current_path = author_dir / "reprocess.epub"
    create_dummy_epub(immutable_path, "Reprocess Book", "Reprocess Author")
    current_path.write_bytes(immutable_path.read_bytes())

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Reprocess Book",
                author="Reprocess Author",
                immutable_path=str(immutable_path.relative_to(library_path.parent)),
                current_path=str(current_path.relative_to(library_path.parent)),
                source_type=models.SourceType.epub,
                current_word_count=2,
            ),
        )
        original_version = book.content_version

    response = client.post("/api/books/reprocess-all")

    assert response.status_code == 200
    assert response.json() == {"status": "started"}

    async with AsyncTestingSessionLocal() as session:
        refreshed = await crud.get_book(session, book.id)
        assert refreshed is not None
        assert refreshed.content_version == original_version

    immutable_path.unlink()
    current_path.unlink()
    author_dir.rmdir()


@pytest.mark.asyncio
async def test_preview_cleaning(db_session):
    """
    Test POST /api/books/{book_id}/preview-cleaning returns word count preview.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    epub_filename = "immutable_preview.epub"
    epub_filepath = library_path / epub_filename
    create_dummy_epub(epub_filepath, "Preview Book", "Author")

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Preview Book",
                author="Author",
                immutable_path=str(Path("library") / epub_filename),
                current_path=str(Path("library") / epub_filename),
                source_type=models.SourceType.epub,
            ),
        )

    # Preview with no selectors — should return the unmodified word count
    response = client.post(f"/api/books/{book.id}/preview-cleaning", json={"content_selectors": [], "removed_chapters": []})

    epub_filepath.unlink()

    assert response.status_code == 200
    data = response.json()
    assert "estimated_word_count" in data

    # Preview with a selector that removes content
    library_path.mkdir(exist_ok=True)
    create_dummy_epub(epub_filepath, "Preview Book", "Author")
    response_stripped = client.post(
        f"/api/books/{book.id}/preview-cleaning", json={"content_selectors": ["p"], "removed_chapters": []}
    )
    epub_filepath.unlink()

    assert response_stripped.status_code == 200
    assert response_stripped.json()["estimated_word_count"] < data["estimated_word_count"]
