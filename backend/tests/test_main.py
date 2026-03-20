import pytest
import pytest_asyncio
import zipfile
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from pathlib import Path

from ebooklib import epub
from backend.app.main import app
from backend.app.services import update_scheduler
from backend.app.services.series import SeriesBook, detect_series_from_books, detect_series_from_titles
from backend.app.database import Base, get_db
from backend.app import models, schemas, crud

# Use an in-memory SQLite database for testing with an async driver
SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
AsyncTestingSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


# Override the `get_db` dependency to use the async test database
async def override_get_db():
    async with AsyncTestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db

# The TestClient for making requests to the app
client = TestClient(app)


# Async pytest fixture to set up and tear down the database for each test function
@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_get_all_books_empty(db_session):
    """
    Test that GET /api/books returns an empty list when the database is empty.
    """
    response = client.get("/api/books")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_book_catalog_returns_minimal_entries(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Catalog Book",
                author="Catalog Author",
                series="Catalog Saga",
                immutable_path="catalog-immutable.epub",
                current_path="catalog.epub",
                source_type=models.SourceType.epub,
                current_word_count=321,
                notes="Should not be in catalog payload",
            ),
        )
        library_path = Path("./library").resolve()
        cover_path = library_path / "covers" / f"{book.id}.jpg"
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        cover_path.write_bytes(b"catalog-cover")
        book.cover_path = str(cover_path.relative_to(library_path.parent))
        await session.commit()

    response = client.get("/api/books/catalog")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Catalog Book"
    assert data[0]["author"] == "Catalog Author"
    assert data[0]["series"] == "Catalog Saga"
    assert data[0]["current_word_count"] == 321
    assert data[0]["cover_path"] == f"library/covers/{book.id}.jpg"
    assert "immutable_path" not in data[0]
    assert "current_path" not in data[0]
    assert "notes" not in data[0]


@pytest.mark.asyncio
async def test_get_book_details_by_ids_preserves_request_order(db_session):
    async with AsyncTestingSessionLocal() as session:
        first = await crud.create_book(
            session,
            schemas.BookCreate(
                title="First Book",
                author="Author A",
                immutable_path="first-immutable.epub",
                current_path="first.epub",
                source_type=models.SourceType.epub,
            ),
        )
        second = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Second Book",
                author="Author B",
                immutable_path="second-immutable.epub",
                current_path="second.epub",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.get(f"/api/books/details?ids={second.id}&ids={first.id}")
    assert response.status_code == 200
    data = response.json()
    assert [book["id"] for book in data] == [second.id, first.id]


@pytest.mark.asyncio
async def test_static_cover_files_are_served_without_cover_lookup(db_session):
    library_path = Path("./library").resolve()
    cover_path = library_path / "covers" / "static-test.jpg"
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_bytes(b"cover-bytes")

    response = client.get("/library/covers/static-test.jpg")

    assert response.status_code == 200
    assert response.content == b"cover-bytes"


@pytest.mark.asyncio
async def test_add_web_novel(db_session, mocker):
    """
    Test adding a new web novel. The endpoint now returns immediately with a pending record
    and schedules the actual download as a background task.
    """
    from unittest.mock import AsyncMock

    # Prevent the background download from running (it uses the prod DB, not the test DB)
    mocker.patch("backend.app.routers.web_novels.finish_web_novel_download", new_callable=AsyncMock)

    payload = {"url": "http://example.com/story/123"}
    response = client.post("/api/books/add_web_novel", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["download_status"] == "pending"
    assert data["source_url"] == "http://example.com/story/123"
    assert data["immutable_path"] is None
    assert data["current_path"] is None

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


def create_dummy_epub(filepath: Path, title: str, author: str, series: str = None):
    """Creates a dummy EPUB file for testing."""
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    if series:
        book.add_metadata("calibre", "series", series)
    # Add a dummy chapter
    c1 = epub.EpubHtml(title="Intro", file_name="chap_1.xhtml", lang="en")
    c1.content = "<h1>Introduction</h1><p>Introduction text.</p>"
    book.add_item(c1)
    book.toc = (epub.Link("chap_1.xhtml", "Introduction", "intro"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1]
    epub.write_epub(filepath, book, {})


def create_zip_archive(zip_path: Path, entries: dict[str, bytes]):
    """Creates a ZIP archive for upload testing."""
    with zipfile.ZipFile(zip_path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


@pytest.mark.asyncio
async def test_upload_epub(db_session):
    """
    Test uploading an EPUB file.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    epub_filename = "Uploaded Book.epub"
    epub_filepath = library_path / epub_filename
    author_dir = library_path / "Uploader"
    immutable_filepath = author_dir / f"immutable_{epub_filename}"
    current_filepath = author_dir / epub_filename

    # Create a dummy epub file
    create_dummy_epub(epub_filepath, "Uploaded Book", "Uploader", "Upload Series")

    with open(epub_filepath, "rb") as f:
        response = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})

    # Clean up the dummy files
    epub_filepath.unlink()
    immutable_filepath.unlink()
    current_filepath.unlink()
    author_dir.rmdir()

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Uploaded Book"
    assert data["author"] == "Uploader"
    assert data["series"] == "Upload Series"
    assert data["immutable_path"] == str(Path("library") / "Uploader" / f"immutable_{epub_filename}")
    assert data["current_path"] == str(Path("library") / "Uploader" / epub_filename)
    assert data["master_word_count"] > 0
    assert data["current_word_count"] == data["master_word_count"]

    # Verify that the book was added to the database
    response = client.get("/api/books")
    assert response.status_code == 200
    books = response.json()
    assert len(books) == 1
    assert books[0]["title"] == "Uploaded Book"


@pytest.mark.asyncio
async def test_upload_zip_with_nested_epubs(db_session):
    """
    Test uploading a ZIP file with EPUBs in nested folders ignores non-EPUB files.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)

    first_epub = library_path / "Nested One.epub"
    second_epub = library_path / "Nested Two.epub"
    zip_path = library_path / "batch-upload.zip"

    create_dummy_epub(first_epub, "Nested One", "Author One")
    create_dummy_epub(second_epub, "Nested Two", "Author Two")

    create_zip_archive(
        zip_path,
        {
            "collection/one/Nested One.epub": first_epub.read_bytes(),
            "collection/two/Nested Two.epub": second_epub.read_bytes(),
            "collection/notes/readme.txt": b"ignore me",
        },
    )

    with open(zip_path, "rb") as f:
        response = client.post("/api/books/upload_epubs", files=[("files", ("batch-upload.zip", f, "application/zip"))])

    first_epub.unlink(missing_ok=True)
    second_epub.unlink(missing_ok=True)
    zip_path.unlink(missing_ok=True)

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {item["status"] for item in data} == {"success"}
    assert {item["book"]["title"] for item in data} == {"Nested One", "Nested Two"}
    assert all(item["filename"].startswith("batch-upload.zip:collection/") for item in data)

    # Imported books are written into author folders using a flattened version of the nested archive path.
    for expected_path in [
        library_path / "Author One" / "collection_one_Nested One.epub",
        library_path / "Author One" / "immutable_collection_one_Nested One.epub",
        library_path / "Author Two" / "collection_two_Nested Two.epub",
        library_path / "Author Two" / "immutable_collection_two_Nested Two.epub",
    ]:
        assert expected_path.exists()
        expected_path.unlink(missing_ok=True)
    (library_path / "Author One").rmdir()
    (library_path / "Author Two").rmdir()


@pytest.mark.asyncio
async def test_upload_zip_with_no_epubs(db_session):
    """
    Test uploading a ZIP file with no EPUB entries reports a skipped result.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    zip_path = library_path / "non-books.zip"
    create_zip_archive(zip_path, {"nested/readme.txt": b"hello", "nested/image.jpg": b"jpg"})

    with open(zip_path, "rb") as f:
        response = client.post("/api/books/upload_epubs", files=[("files", ("non-books.zip", f, "application/zip"))])

    zip_path.unlink(missing_ok=True)

    assert response.status_code == 200
    assert response.json() == [
        {
            "filename": "non-books.zip",
            "status": "skipped",
            "book": None,
            "error": "No EPUB files found in ZIP archive",
        }
    ]


@pytest.mark.asyncio
async def test_search_books_by_author(db_session):
    """
    Test searching for books by author.
    """
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book 1",
                author="Author A",
                immutable_path="p1i",
                current_path="p1c",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book 2",
                author="Author B",
                immutable_path="p2i",
                current_path="p2c",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book 3",
                author="Author A",
                immutable_path="p3i",
                current_path="p3c",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.get("/api/books/search/author/Author A")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {b["title"] for b in data} == {"Book 1", "Book 3"}

    response = client.get("/api/books/search/author/author b")  # case-insensitive
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Book 2"


@pytest.mark.asyncio
async def test_get_book_chapters(db_session):
    """
    Test getting the chapters of a book.
    """
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Test Book",
                author="Test Author",
                immutable_path="library/immutable_test.epub",
                current_path="library/test.epub",
                source_type=models.SourceType.epub,
            ),
        )

    # Create a dummy epub file
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    immutable_filepath = library_path / "immutable_test.epub"
    create_dummy_epub(immutable_filepath, "Test Book", "Test Author")

    response = client.get(f"/api/books/{book.id}/chapters")

    immutable_filepath.unlink()

    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0]["title"] == "Introduction"


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
async def test_update_book_details(db_session):
    """
    Test updating a book's details.
    """
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Original Title",
                author="Original Author",
                immutable_path="p1i",
                current_path="p1c",
                source_type=models.SourceType.epub,
            ),
        )

    update_payload = {"title": "Updated Title", "series": "New Series"}
    response = client.put(f"/api/books/{book.id}", json=update_payload)

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["author"] == "Original Author"  # Should not change
    assert data["series"] == "New Series"


@pytest.mark.asyncio
async def test_refresh_book(db_session, mocker):
    """
    Test refreshing a book from its source URL.
    """
    # Mock the helper function to simulate a successful download and metadata parsing
    library_path = Path("./library").resolve()
    new_epub_path = library_path / "Refreshed Title-Refreshed Author.epub"
    mocker.patch(
        "backend.app.routers.web_novels.download_web_novel",
        return_value=(
            new_epub_path,
            {"title": "Refreshed Title", "author": "Refreshed Author", "series": "Refreshed Series"},
        ),
    )

    # Since we are not mocking the file system, we need to create the dummy files
    library_path.mkdir(exist_ok=True)
    create_dummy_epub(new_epub_path, "Refreshed Title", "Refreshed Author")

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Original Title",
                author="Original Author",
                source_url="http://example.com/story/refresh",
                immutable_path="p1i",
                current_path="p1c",
                source_type=models.SourceType.web,
            ),
        )

    response = client.post(f"/api/books/{book.id}/refresh")

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Refreshed Title"
    assert data["author"] == "Refreshed Author"
    assert data["series"] == "Refreshed Series"
    assert data["master_word_count"] > 0
    assert data["current_word_count"] == data["master_word_count"]

    # Clean up dummy files
    (library_path.parent / data["immutable_path"]).unlink()
    (library_path.parent / data["current_path"]).unlink()


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
                download_status="complete",
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
                download_status="complete",
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
async def test_unified_search(db_session):
    """
    Test the unified search endpoint (GET /api/books/search?q=).
    """
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Dragon's Lair",
                author="Alice Smith",
                series="Dragon Saga",
                immutable_path="pi1",
                current_path="pc1",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Moonlight",
                author="Bob Dragon",
                series="Night Tales",
                immutable_path="pi2",
                current_path="pc2",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="The Summit",
                author="Carol Jones",
                series=None,
                immutable_path="pi3",
                current_path="pc3",
                source_type=models.SourceType.epub,
            ),
        )

    # Matches title
    response = client.get("/api/books/search?q=summit")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "The Summit"

    # Matches author
    response = client.get("/api/books/search?q=dragon")
    assert response.status_code == 200
    data = response.json()
    titles = {b["title"] for b in data}
    assert "Dragon's Lair" in titles  # title match
    assert "Moonlight" in titles  # author match

    # Matches series
    response = client.get("/api/books/search?q=night tales")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Moonlight"

    # No match
    response = client.get("/api/books/search?q=zzznomatch")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_sort_books(db_session):
    """
    Test that GET /api/books returns books sorted correctly.
    """
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Zebra", author="Author Z", immutable_path="pi1", current_path="pc1", source_type=models.SourceType.epub
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Apple", author="Author A", immutable_path="pi2", current_path="pc2", source_type=models.SourceType.epub
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Mango", author="Author M", immutable_path="pi3", current_path="pc3", source_type=models.SourceType.epub
            ),
        )

    response = client.get("/api/books?sort_by=title&sort_order=asc")
    assert response.status_code == 200
    titles = [b["title"] for b in response.json()]
    assert titles == ["Apple", "Mango", "Zebra"]

    response = client.get("/api/books?sort_by=title&sort_order=desc")
    assert response.status_code == 200
    titles = [b["title"] for b in response.json()]
    assert titles == ["Zebra", "Mango", "Apple"]

    response = client.get("/api/books?sort_by=author&sort_order=asc")
    assert response.status_code == 200
    authors = [b["author"] for b in response.json()]
    assert authors == ["Author A", "Author M", "Author Z"]


@pytest.mark.asyncio
async def test_delete_book_by_id(db_session):
    """
    Test deleting a book by ID (DELETE /api/books/{book_id}).
    """
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="To Delete",
                author="Author",
                immutable_path="pi_del",
                current_path="pc_del",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.delete(f"/api/books/{book.id}")
    assert response.status_code == 204

    # Verify it's gone
    response = client.get("/api/books")
    assert response.json() == []

    # Deleting again is idempotent (returns 204)
    response = client.delete(f"/api/books/{book.id}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_book_by_id_removes_author_folder_when_empty(db_session):
    library_path = Path("./library").resolve()
    author_dir = library_path / "Folder Author"
    author_dir.mkdir(parents=True, exist_ok=True)

    immutable_path = author_dir / "immutable_Delete Me.epub"
    current_path = author_dir / "Delete Me.epub"
    create_dummy_epub(immutable_path, "Delete Me", "Folder Author")
    create_dummy_epub(current_path, "Delete Me", "Folder Author")

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Delete Me",
                author="Folder Author",
                immutable_path=str(immutable_path.relative_to(library_path.parent)),
                current_path=str(current_path.relative_to(library_path.parent)),
                source_type=models.SourceType.epub,
            ),
        )

    response = client.delete(f"/api/books/{book.id}")

    assert response.status_code == 204
    assert not author_dir.exists()


@pytest.mark.asyncio
async def test_remove_all_books_preview_and_delete(db_session):
    library_path = Path("./library").resolve()
    author_one_dir = library_path / "Author One"
    author_two_dir = library_path / "Author Two"
    author_one_dir.mkdir(parents=True, exist_ok=True)
    author_two_dir.mkdir(parents=True, exist_ok=True)

    alpha_immutable = author_one_dir / "immutable_Alpha.epub"
    alpha_current = author_one_dir / "Alpha.epub"
    beta_immutable = author_two_dir / "immutable_Beta.epub"
    beta_current = author_two_dir / "Beta.epub"
    create_dummy_epub(alpha_immutable, "Alpha", "Author One")
    create_dummy_epub(alpha_current, "Alpha", "Author One")
    create_dummy_epub(beta_immutable, "Beta", "Author Two")
    create_dummy_epub(beta_current, "Beta", "Author Two")

    async with AsyncTestingSessionLocal() as session:
        alpha = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Alpha",
                author="Author One",
                immutable_path=str(alpha_immutable.relative_to(library_path.parent)),
                current_path=str(alpha_current.relative_to(library_path.parent)),
                source_type=models.SourceType.epub,
            ),
        )
        beta = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Beta",
                author="Author Two",
                immutable_path=str(beta_immutable.relative_to(library_path.parent)),
                current_path=str(beta_current.relative_to(library_path.parent)),
                source_type=models.SourceType.epub,
            ),
        )
        cover_path = library_path / "covers" / f"{alpha.id}.jpg"
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        cover_path.write_bytes(b"cover")
        alpha.cover_path = str(cover_path.relative_to(library_path.parent))
        await session.commit()
        await crud.create_book_log(session, schemas.BookLogCreate(book_id=alpha.id, entry_type="added"))
        await crud.create_book_log(session, schemas.BookLogCreate(book_id=alpha.id, entry_type="updated"))
        await crud.create_book_log(session, schemas.BookLogCreate(book_id=beta.id, entry_type="added"))

    preview_response = client.post("/api/books/remove-all?dry_run=true")

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["dry_run"] is True
    assert preview["book_count"] == 2
    assert preview["file_count"] == 5
    assert preview["log_count"] == 3
    assert "library/Author One/Alpha.epub" in preview["paths"]
    assert any(book["title"] == "Alpha" and book["log_entries"] == 2 for book in preview["books"])

    delete_response = client.post("/api/books/remove-all?dry_run=false")

    assert delete_response.status_code == 200
    assert client.get("/api/books").json() == []
    assert not author_one_dir.exists()
    assert not author_two_dir.exists()
    assert not cover_path.exists()


@pytest.mark.asyncio
async def test_delete_book_by_title(db_session):
    """
    Test deleting a book by title (DELETE /api/books/by-title/{title}).
    """
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Gone With Wind",
                author="Author",
                immutable_path="pi_del2",
                current_path="pc_del2",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.delete("/api/books/by-title/Gone With Wind")
    assert response.status_code == 204

    response = client.get("/api/books")
    assert response.json() == []

    # Deleting non-existent title is idempotent
    response = client.delete("/api/books/by-title/Nonexistent")
    assert response.status_code == 204


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
async def test_book_notes(db_session):
    """
    Test updating a book's notes field via PUT /api/books/{book_id}.
    """
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Noted Book",
                author="Author",
                immutable_path="pi_notes",
                current_path="pc_notes",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.put(f"/api/books/{book.id}", json={"notes": "Great read, revisit chapter 5."})
    assert response.status_code == 200
    data = response.json()
    assert data["notes"] == "Great read, revisit chapter 5."
    assert data["title"] == "Noted Book"  # unchanged

    # Clear notes
    response = client.put(f"/api/books/{book.id}", json={"notes": ""})
    assert response.status_code == 200
    assert response.json()["notes"] == ""


@pytest.mark.asyncio
async def test_scheduler_status_empty(db_session):
    """
    Test GET /api/scheduler/status returns null when no tasks exist.
    """
    response = client.get("/api/scheduler/status")
    assert response.status_code == 200
    assert response.json() is None


def test_calculate_next_run_time_uses_last_run_plus_interval():
    now = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)
    last_run = now - timedelta(hours=6)

    next_run = update_scheduler.calculate_next_run_time(last_run, now=now)

    assert next_run == last_run + timedelta(hours=24)


def test_calculate_next_run_time_runs_soon_when_overdue():
    now = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)
    last_run = now - timedelta(hours=30)

    next_run = update_scheduler.calculate_next_run_time(last_run, now=now)

    assert next_run == now + update_scheduler.OVERDUE_RUN_DELAY


def test_get_last_run_anchor_prefers_start_for_failed_tasks():
    task = models.UpdateTask(status="failed", total_books=1, completed_books=1)
    task.started_at = datetime(2026, 3, 18, 10, 0, tzinfo=timezone.utc)
    task.completed_at = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)

    anchor = update_scheduler.get_last_run_anchor(task)

    assert anchor == task.started_at


@pytest.mark.asyncio
async def test_scheduler_job_status(db_session, mocker):
    """
    Test GET /api/scheduler/job returns schedule metadata and latest run details.
    """
    async with AsyncTestingSessionLocal() as session:
        task = await crud.create_update_task(session, total_books=2)
        await crud.complete_update_task(session, task)

    class DummyJob:
        next_run_time = datetime(2026, 3, 20, 14, 30, tzinfo=timezone.utc)

    mocker.patch("backend.app.routers.scheduler.update_scheduler.get_scheduled_job", return_value=DummyJob())
    mocker.patch("backend.app.routers.scheduler.update_scheduler.is_scheduler_running", return_value=True)
    mocker.patch("backend.app.routers.scheduler.update_scheduler.is_update_running", return_value=False)

    response = client.get("/api/scheduler/job")

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "update_web_novels"
    assert data["schedule"] == "Every 24 hours"
    assert data["next_run_at"] == "2026-03-20T14:30:00Z"
    assert data["scheduler_running"] is True
    assert data["run_in_progress"] is False
    assert data["last_run_status"] == "completed"
    assert data["last_run_started_at"] is not None
    assert data["last_run_completed_at"] is not None


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
    data = response.json()
    assert data["reprocessed"] == 2


@pytest.mark.asyncio
async def test_download_book(db_session):
    """
    Test GET /api/books/{book_id}/download returns the EPUB file.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    epub_filename = "Download Test Book.epub"
    epub_filepath = library_path / epub_filename
    immutable_filepath = library_path / f"immutable_{epub_filename}"

    create_dummy_epub(epub_filepath, "Download Test Book", "Downloader")
    create_dummy_epub(immutable_filepath, "Download Test Book", "Downloader")

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Download Test Book",
                author="Downloader",
                immutable_path=str(Path("library") / f"immutable_{epub_filename}"),
                current_path=str(Path("library") / epub_filename),
                source_type=models.SourceType.epub,
            ),
        )

    response = client.get(f"/api/books/{book.id}/download")

    epub_filepath.unlink()
    immutable_filepath.unlink()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    assert epub_filename in response.headers["content-disposition"]


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


@pytest.mark.asyncio
async def test_search_books_by_series(db_session):
    """
    Test searching for books by series.
    """
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book 1",
                author="Author A",
                series="Series X",
                immutable_path="p1i",
                current_path="p1c",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book 2",
                author="Author B",
                series="Series Y",
                immutable_path="p2i",
                current_path="p2c",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book 3",
                author="Author A",
                series="Series X",
                immutable_path="p3i",
                current_path="p3c",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book 4",
                author="Author C",
                series="Series XY",
                immutable_path="p4i",
                current_path="p4c",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.get("/api/books/search/series/Series X")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {b["title"] for b in data} == {"Book 1", "Book 3"}

    response = client.get("/api/books/search/series/series y")  # case-insensitive
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["title"] == "Book 2"


@pytest.mark.asyncio
async def test_opds_root_feed(db_session):
    """
    Test that GET /reader/opds returns a valid authenticated Atom navigation feed.
    """
    key_response = client.post("/api/reader-keys", json={"label": "Test Reader"})
    assert key_response.status_code == 201
    token = key_response.json()["token"]

    response = client.get("/reader/opds", auth=("reader", token))
    assert response.status_code == 200
    assert "application/atom+xml" in response.headers["content-type"]

    import xml.etree.ElementTree as ET

    ATOM = "{http://www.w3.org/2005/Atom}"
    root = ET.fromstring(response.content)
    assert root.tag == f"{ATOM}feed"
    assert root.findtext(f"{ATOM}title") == "Story Manager Reader"
    # Should have subsection entries for both the catalog and the series listing.
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 2
    assert [entry.findtext(f"{ATOM}title") for entry in entries] == ["All Books", "Series"]


@pytest.mark.asyncio
async def test_opds_catalog_feed(db_session):
    """
    Test that GET /reader/opds/catalog returns an acquisition feed with book entries.
    """
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Catalog Book",
                author="Cat Author",
                immutable_path="ci",
                current_path="cc",
                source_type=models.SourceType.epub,
            ),
        )

    key_response = client.post("/api/reader-keys", json={"label": "Catalog Reader"})
    assert key_response.status_code == 201
    token = key_response.json()["token"]

    response = client.get("/reader/opds/catalog", auth=("reader", token))
    assert response.status_code == 200
    assert "application/atom+xml" in response.headers["content-type"]

    import xml.etree.ElementTree as ET

    ATOM = "{http://www.w3.org/2005/Atom}"
    root = ET.fromstring(response.content)
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 1
    assert entries[0].findtext(f"{ATOM}title") == "Catalog Book"

    # Acquisition link present
    links = entries[0].findall(f"{ATOM}link")
    acq_links = [link for link in links if link.get("rel") == "http://opds-spec.org/acquisition"]
    assert len(acq_links) == 1
    assert "epub+zip" in acq_links[0].get("type", "")


@pytest.mark.asyncio
async def test_opds_search_feed(db_session):
    """
    Test that GET /reader/opds/search?q=... returns matching book entries.
    """
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Searchable Title",
                author="Search Author",
                immutable_path="si",
                current_path="sc",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Other Book",
                author="Other Author",
                immutable_path="oi",
                current_path="oc",
                source_type=models.SourceType.epub,
            ),
        )

    key_response = client.post("/api/reader-keys", json={"label": "Search Reader"})
    assert key_response.status_code == 201
    token = key_response.json()["token"]

    response = client.get("/reader/opds/search?q=Searchable", auth=("reader", token))
    assert response.status_code == 200
    assert "application/atom+xml" in response.headers["content-type"]

    import xml.etree.ElementTree as ET

    ATOM = "{http://www.w3.org/2005/Atom}"
    root = ET.fromstring(response.content)
    entries = root.findall(f"{ATOM}entry")
    assert len(entries) == 1
    assert entries[0].findtext(f"{ATOM}title") == "Searchable Title"


@pytest.mark.asyncio
async def test_duplicate_epub_upload(db_session):
    """
    Test that uploading an EPUB with the same title and author as an existing book returns 409.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    epub_filename = "Dup Book.epub"
    epub_filepath = library_path / epub_filename
    immutable_filepath = library_path / f"immutable_{epub_filename}"

    create_dummy_epub(epub_filepath, "Dup Book", "Dup Author")

    # First upload — should succeed
    with open(epub_filepath, "rb") as f:
        response = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})
    assert response.status_code == 201

    # Recreate the file for the second upload (first upload consumed the stream)
    create_dummy_epub(epub_filepath, "Dup Book", "Dup Author")

    # Second upload — same title + author → 409
    with open(epub_filepath, "rb") as f:
        response = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]

    # Clean up
    for p in [epub_filepath, immutable_filepath]:
        if p.exists():
            p.unlink()


@pytest.mark.asyncio
async def test_books_count(db_session):
    """
    Test that GET /api/books/count returns the correct total.
    """
    response = client.get("/api/books/count")
    assert response.status_code == 200
    assert response.json() == {"total": 0}

    async with AsyncTestingSessionLocal() as session:
        for i in range(3):
            await crud.create_book(
                session,
                schemas.BookCreate(
                    title=f"Count Book {i}",
                    author="Counter",
                    immutable_path=f"cbi{i}",
                    current_path=f"cbc{i}",
                    source_type=models.SourceType.epub,
                ),
            )

    response = client.get("/api/books/count")
    assert response.status_code == 200
    assert response.json() == {"total": 3}

    # With search filter
    response = client.get("/api/books/count?q=Count+Book+1")
    assert response.status_code == 200
    assert response.json() == {"total": 1}


@pytest.mark.asyncio
async def test_scheduler_history_empty(db_session):
    """
    Test GET /api/scheduler/history returns empty list when no tasks exist.
    """
    response = client.get("/api/scheduler/history")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_scheduler_history_with_tasks(db_session):
    """
    Test GET /api/scheduler/history returns tasks ordered newest first.
    """
    async with AsyncTestingSessionLocal() as session:
        task1 = await crud.create_update_task(session, total_books=5)
        await crud.complete_update_task(session, task1)
        task2 = await crud.create_update_task(session, total_books=3)
        await crud.complete_update_task(session, task2)

    response = client.get("/api/scheduler/history")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {d["total_books"] for d in data} == {3, 5}
    assert all(d["status"] == "completed" for d in data)

    # Pagination works: limit=1 returns exactly 1 task
    r1 = client.get("/api/scheduler/history?limit=1")
    assert r1.status_code == 200
    assert len(r1.json()) == 1

    # offset=1 returns the other task
    r2 = client.get("/api/scheduler/history?limit=1&offset=1")
    assert r2.status_code == 200
    assert len(r2.json()) == 1
    assert r1.json()[0]["id"] != r2.json()[0]["id"]


@pytest.mark.asyncio
async def test_scheduler_history_task_logs(db_session):
    """
    Test GET /api/scheduler/history/{task_id}/logs returns per-book log entries.
    """
    async with AsyncTestingSessionLocal() as session:
        book_a = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Log Book A",
                author="Author",
                immutable_path="lba_i",
                current_path="lba_c",
                source_type=models.SourceType.web,
                source_url="http://example.com/lba",
            ),
        )
        book_b = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Log Book B",
                author="Author",
                immutable_path="lbb_i",
                current_path="lbb_c",
                source_type=models.SourceType.web,
                source_url="http://example.com/lbb",
            ),
        )
        task = await crud.create_update_task(session, total_books=2)
        await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book_a.id,
                entry_type="updated",
                previous_chapter_count=10,
                new_chapter_count=15,
                words_added=5000,
            ),
        )
        await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book_b.id,
                entry_type="checked",
                previous_chapter_count=8,
                new_chapter_count=8,
                words_added=0,
            ),
        )
        await crud.complete_update_task(session, task)

    response = client.get(f"/api/scheduler/history/{task.id}/logs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    titles = {entry["book_title"] for entry in data}
    assert titles == {"Log Book A", "Log Book B"}

    updated = next(e for e in data if e["entry_type"] == "updated")
    assert updated["book_title"] == "Log Book A"
    assert updated["previous_chapter_count"] == 10
    assert updated["new_chapter_count"] == 15
    assert updated["words_added"] == 5000

    checked = next(e for e in data if e["entry_type"] == "checked")
    assert checked["book_title"] == "Log Book B"
    assert checked["words_added"] == 0


@pytest.mark.asyncio
async def test_scheduler_history_task_logs_not_found(db_session):
    """
    Test GET /api/scheduler/history/{task_id}/logs returns 404 for unknown task.
    """
    response = client.get("/api/scheduler/history/9999/logs")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ─── detect_series_from_titles unit tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_series_empty(db_session):
    """
    Test that GET /api/series returns an empty list when no books have a series.
    """
    response = client.get("/api/series")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_series_sorted_and_distinct(db_session):
    """
    Test that GET /api/series returns distinct, alphabetically sorted series names
    and excludes books with no series.
    """
    async with AsyncTestingSessionLocal() as session:
        # Two books in the same series (should appear once)
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Zebra Saga 1",
                author="Author A",
                series="Zebra Saga",
                immutable_path="zs1i",
                current_path="zs1c",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Zebra Saga 2",
                author="Author A",
                series="Zebra Saga",
                immutable_path="zs2i",
                current_path="zs2c",
                source_type=models.SourceType.epub,
            ),
        )
        # A second series
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Alpha Chronicles 1",
                author="Author B",
                series="Alpha Chronicles",
                immutable_path="ac1i",
                current_path="ac1c",
                source_type=models.SourceType.epub,
            ),
        )
        # A book with no series (should be excluded)
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Standalone Book",
                author="Author C",
                series=None,
                immutable_path="sbi",
                current_path="sbc",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.get("/api/series")
    assert response.status_code == 200
    data = response.json()
    # Two distinct series, alphabetically sorted, no duplicates, no None
    assert data == ["Alpha Chronicles", "Zebra Saga"]


def test_detect_series_numbered_arabic():
    """Two books with arabic numbers and subtitles form a series."""
    titles = ["Series A 1 - The Beginning", "Series A 2 - The Next One"]
    result = detect_series_from_titles(titles)
    assert result == {
        "Series A 1 - The Beginning": "Series A",
        "Series A 2 - The Next One": "Series A",
    }


def test_detect_series_roman_numerals():
    """Books with roman numerals II and III are detected as a series."""
    titles = ["12 Miles Below II", "12 Miles Below III"]
    result = detect_series_from_titles(titles)
    assert result["12 Miles Below II"] == "12 Miles Below"
    assert result["12 Miles Below III"] == "12 Miles Below"


def test_detect_series_unnumbered_exact_prefix():
    """A title that is exactly the series prefix is pulled into the series."""
    titles = ["12 Miles Below II", "12 Miles Below III", "12 Miles Below"]
    result = detect_series_from_titles(titles)
    assert result["12 Miles Below"] == "12 Miles Below"


def test_detect_series_unnumbered_colon_subtitle():
    """A title with the series prefix followed by ': subtitle' is pulled in."""
    titles = [
        "12 Miles Below II",
        "12 Miles Below III",
        "12 Miles Below: A Prog Fantasy",
    ]
    result = detect_series_from_titles(titles)
    assert result["12 Miles Below: A Prog Fantasy"] == "12 Miles Below"


def test_detect_series_all_four_12_miles_below():
    """All four 12 Miles Below titles are grouped into a single series."""
    titles = [
        "12 Miles Below II",
        "12 Miles Below III",
        "12 Miles Below",
        "12 Miles Below: A Prog Fantasy",
    ]
    result = detect_series_from_titles(titles)
    assert set(result.keys()) == set(titles)
    assert all(v == "12 Miles Below" for v in result.values())


def test_detect_series_requires_two_numbered_anchors():
    """A single numbered entry is not enough to confirm a series."""
    titles = ["My Series 1 - Intro", "Unrelated Book"]
    result = detect_series_from_titles(titles)
    assert result == {}


def test_detect_series_no_false_positive_standalone():
    """Books that share no common pattern are not grouped."""
    titles = ["The Hobbit", "Dune", "Foundation"]
    result = detect_series_from_titles(titles)
    assert result == {}


def test_detect_series_multiple_independent_series():
    """Two distinct series in the same list are both detected independently."""
    titles = [
        "Shadow 1 - Awakening",
        "Shadow 2 - Reckoning",
        "Iron 1 - Forge",
        "Iron 2 - Flame",
    ]
    result = detect_series_from_titles(titles)
    assert result["Shadow 1 - Awakening"] == "Shadow"
    assert result["Shadow 2 - Reckoning"] == "Shadow"
    assert result["Iron 1 - Forge"] == "Iron"
    assert result["Iron 2 - Flame"] == "Iron"


def test_detect_series_dash_subtitle_unnumbered():
    """Unnumbered title with ' - subtitle' separator is pulled into the series."""
    titles = [
        "My Series 1 - Part One",
        "My Series 2 - Part Two",
        "My Series - The Prequel",
    ]
    result = detect_series_from_titles(titles)
    assert result["My Series - The Prequel"] == "My Series"


def test_detect_series_parenthetical_book_suffix_by_author():
    """Trailing '(Series Book N)' metadata is detected when the author matches."""
    books = [
        SeriesBook(title="Soulsmith (Cradle Book 2)", author="Will Wight"),
        SeriesBook(title="Blackflame (Cradle Book 3)", author="Will Wight"),
        SeriesBook(title="Reaper (Cradle Book 10)", author="Will Wight"),
    ]
    result = detect_series_from_books(books)
    assert result[("Will Wight", "Soulsmith (Cradle Book 2)")] == "Cradle"
    assert result[("Will Wight", "Blackflame (Cradle Book 3)")] == "Cradle"
    assert result[("Will Wight", "Reaper (Cradle Book 10)")] == "Cradle"


def test_detect_series_mixed_formats_same_author():
    """Equivalent series hints from the same author are merged into one canonical series."""
    books = [
        SeriesBook(title="Cultivating Chaos (VeilVerse: Cultivating Chaos Book 1)", author="William D. Arand"),
        SeriesBook(title="Cultivating Chaos: Book 2 (VeilVerse: Cultivating Chaos)", author="William D. Arand"),
        SeriesBook(title="Cultivating Chaos 3", author="William D. Arand"),
    ]
    result = detect_series_from_books(books)
    assert result[("William D. Arand", "Cultivating Chaos (VeilVerse: Cultivating Chaos Book 1)")] == "Cultivating Chaos"
    assert result[("William D. Arand", "Cultivating Chaos: Book 2 (VeilVerse: Cultivating Chaos)")] == "Cultivating Chaos"
    assert result[("William D. Arand", "Cultivating Chaos 3")] == "Cultivating Chaos"


def test_detect_series_hash_number_same_author():
    """Hash-numbered entries should be grouped with plain numbered entries for the same author."""
    books = [
        SeriesBook(title="Throne Hunters 1", author="Phil Tucker"),
        SeriesBook(title="Throne Hunters #2", author="Phil Tucker"),
        SeriesBook(title="Throne Hunters #3", author="Phil Tucker"),
        SeriesBook(title="Throne Hunters 4", author="Phil Tucker"),
    ]
    result = detect_series_from_books(books)
    assert result[("Phil Tucker", "Throne Hunters 1")] == "Throne Hunters"
    assert result[("Phil Tucker", "Throne Hunters #2")] == "Throne Hunters"
    assert result[("Phil Tucker", "Throne Hunters #3")] == "Throne Hunters"
    assert result[("Phil Tucker", "Throne Hunters 4")] == "Throne Hunters"


def test_detect_series_repeated_parenthetical_hint_same_author():
    """Repeated terminal parenthetical series labels should confirm a series for one author."""
    books = [
        SeriesBook(title="The Shadow of What Was Lost (The Licanius Trilogy)", author="James Islington"),
        SeriesBook(title="An Echo of Things to Come (The Licanius Trilogy)", author="James Islington"),
        SeriesBook(title="The Light of All That Falls (The Licanius Trilogy)", author="James Islington"),
    ]
    result = detect_series_from_books(books)
    assert result[("James Islington", "The Shadow of What Was Lost (The Licanius Trilogy)")] == "The Licanius Trilogy"
    assert result[("James Islington", "An Echo of Things to Come (The Licanius Trilogy)")] == "The Licanius Trilogy"
    assert result[("James Islington", "The Light of All That Falls (The Licanius Trilogy)")] == "The Licanius Trilogy"


def test_detect_series_prefix_subtitle_with_book_number():
    """Series prefixes before a subtitle should be detected when the title still carries 'Book N'."""
    books = [
        SeriesBook(title="The Beginning After The End: Early Years, Book 1", author="TurtleMe"),
        SeriesBook(title="The Beginning After The End: Reckoning, Book 9", author="TurtleMe"),
        SeriesBook(title="The Beginning After The End: Providence, Book 11", author="TurtleMe"),
    ]
    result = detect_series_from_books(books)
    assert result[("TurtleMe", "The Beginning After The End: Early Years, Book 1")] == "The Beginning After The End"
    assert result[("TurtleMe", "The Beginning After The End: Reckoning, Book 9")] == "The Beginning After The End"
    assert result[("TurtleMe", "The Beginning After The End: Providence, Book 11")] == "The Beginning After The End"


def test_detect_series_same_author_multiple_independent_series():
    """A single author can still have multiple distinct detected series."""
    books = [
        SeriesBook(title="Soulsmith (Cradle Book 2)", author="Will Wight"),
        SeriesBook(title="Blackflame (Cradle Book 3)", author="Will Wight"),
        SeriesBook(title="Of Sea and Shadow (The Elder Empire: Sea Book 1)", author="Will Wight"),
        SeriesBook(title="Of Dawn and Darkness (The Elder Empire: Sea Book 2)", author="Will Wight"),
        SeriesBook(title="Of Shadow and Sea (The Elder Empire: Shadow Book 1)", author="Will Wight"),
        SeriesBook(title="Of Darkness and Dawn (The Elder Empire: Shadow Book 2)", author="Will Wight"),
    ]
    result = detect_series_from_books(books)
    assert result[("Will Wight", "Soulsmith (Cradle Book 2)")] == "Cradle"
    assert result[("Will Wight", "Blackflame (Cradle Book 3)")] == "Cradle"
    assert result[("Will Wight", "Of Sea and Shadow (The Elder Empire: Sea Book 1)")] == "The Elder Empire: Sea"
    assert result[("Will Wight", "Of Dawn and Darkness (The Elder Empire: Sea Book 2)")] == "The Elder Empire: Sea"
    assert result[("Will Wight", "Of Shadow and Sea (The Elder Empire: Shadow Book 1)")] == "The Elder Empire: Shadow"
    assert result[("Will Wight", "Of Darkness and Dawn (The Elder Empire: Shadow Book 2)")] == "The Elder Empire: Shadow"


def test_detect_series_does_not_cross_authors():
    """Matching title patterns from different authors should not confirm a shared series."""
    books = [
        SeriesBook(title="Shared Saga 1", author="Author One"),
        SeriesBook(title="Shared Saga 2", author="Author Two"),
    ]
    assert detect_series_from_books(books) == {}


@pytest.mark.asyncio
async def test_detect_series_endpoint_uses_author_aware_patterns(db_session):
    """The detect-series endpoint updates books for the live formats seen in the library sample."""
    async with AsyncTestingSessionLocal() as session:
        for title, author in [
            ("Soulsmith (Cradle Book 2)", "Will Wight"),
            ("Blackflame (Cradle Book 3)", "Will Wight"),
            ("Cultivating Chaos (VeilVerse: Cultivating Chaos Book 1)", "William D. Arand"),
            ("Cultivating Chaos: Book 2 (VeilVerse: Cultivating Chaos)", "William D. Arand"),
            ("Cultivating Chaos 3", "William D. Arand"),
            ("Shared Saga 1", "Author One"),
            ("Shared Saga 2", "Author Two"),
        ]:
            await crud.create_book(
                session,
                schemas.BookCreate(
                    title=title,
                    author=author,
                    immutable_path=f"library/immutable_{author}_{title}.epub",
                    current_path=f"library/{author}_{title}.epub",
                    source_type=models.SourceType.epub,
                ),
            )

    response = client.post("/api/books/detect-series")
    assert response.status_code == 200
    data = response.json()
    assert data["updated"] == 5
    assert data["series_detected"] == ["Cradle", "Cultivating Chaos"]

    response = client.get("/api/books", params={"limit": 20})
    assert response.status_code == 200
    books = {(book["author"], book["title"]): book["series"] for book in response.json()}
    assert books[("Will Wight", "Soulsmith (Cradle Book 2)")] == "Cradle"
    assert books[("Will Wight", "Blackflame (Cradle Book 3)")] == "Cradle"
    assert books[("William D. Arand", "Cultivating Chaos (VeilVerse: Cultivating Chaos Book 1)")] == "Cultivating Chaos"
    assert books[("William D. Arand", "Cultivating Chaos: Book 2 (VeilVerse: Cultivating Chaos)")] == "Cultivating Chaos"
    assert books[("William D. Arand", "Cultivating Chaos 3")] == "Cultivating Chaos"
    assert books[("Author One", "Shared Saga 1")] is None
    assert books[("Author Two", "Shared Saga 2")] is None


@pytest.mark.asyncio
async def test_create_reader_key_and_use_reader_updates(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Reader Book",
                author="Reader Author",
                immutable_path="library/immutable_reader.epub",
                current_path="library/reader.epub",
                source_type=models.SourceType.epub,
                current_word_count=4321,
            ),
        )

    create_response = client.post("/api/reader-keys", json={"label": "Kobo"})
    assert create_response.status_code == 201
    created_key = create_response.json()
    assert created_key["token"].startswith(created_key["token_prefix"])

    list_response = client.get("/api/reader-keys")
    assert list_response.status_code == 200
    assert list_response.json()[0]["label"] == "Kobo"

    reader_response = client.get(
        "/reader/updates",
        headers={"Authorization": f"Bearer {created_key['token']}"},
    )
    assert reader_response.status_code == 200
    payload = reader_response.json()
    assert len(payload) == 1
    assert payload[0]["title"] == "Reader Book"
    assert payload[0]["download_url"].endswith("/reader/books/1/download")
    assert payload[0]["content_version"] == 1
    assert payload[0]["current_word_count"] == 4321


@pytest.mark.asyncio
async def test_reader_series_api_and_opds_feeds(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Arcane Saga 1",
                author="Author A",
                series="Arcane Saga",
                immutable_path="library/immutable_arcane_1.epub",
                current_path="library/arcane_1.epub",
                source_type=models.SourceType.epub,
                current_word_count=1000,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Arcane Saga 2",
                author="Author A",
                series="arcane saga",
                immutable_path="library/immutable_arcane_2.epub",
                current_path="library/arcane_2.epub",
                source_type=models.SourceType.epub,
                current_word_count=2000,
                cover_path="library/arcane_cover.jpg",
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Hidden Standalone",
                author="Author B",
                series="Arcane Saga",
                immutable_path="library/immutable_hidden.epub",
                current_path="library/hidden.epub",
                source_type=models.SourceType.epub,
                download_status="processing",
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="No Cover Chronicle",
                author="Author C",
                series="No Cover Chronicle",
                immutable_path="library/immutable_no_cover.epub",
                current_path="library/no_cover.epub",
                source_type=models.SourceType.epub,
                current_word_count=500,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Truly Standalone",
                author="Author D",
                series=None,
                immutable_path="library/immutable_standalone.epub",
                current_path="library/standalone.epub",
                source_type=models.SourceType.epub,
                current_word_count=750,
            ),
        )

    key_response = client.post("/api/reader-keys", json={"label": "Series Reader"})
    assert key_response.status_code == 201
    token = key_response.json()["token"]

    series_response = client.get("/reader/series", auth=("reader", token))
    assert series_response.status_code == 200
    series_payload = series_response.json()
    assert [series["name"] for series in series_payload] == ["Arcane Saga", "No Cover Chronicle"]
    assert series_payload[0]["book_count"] == 2
    assert series_payload[0]["total_words"] == 3000
    assert series_payload[0]["cover_url"].endswith("/reader/covers/2")
    assert series_payload[1]["cover_url"] is None

    books_response = client.get("/reader/series/arcane saga/books", auth=("reader", token))
    assert books_response.status_code == 200
    books_payload = books_response.json()
    assert [book["title"] for book in books_payload] == ["Arcane Saga 1", "Arcane Saga 2"]
    assert [book["current_word_count"] for book in books_payload] == [1000, 2000]

    standalone_response = client.get("/reader/books/standalone", auth=("reader", token))
    assert standalone_response.status_code == 200
    standalone_payload = standalone_response.json()
    assert [book["title"] for book in standalone_payload] == ["Truly Standalone"]
    assert standalone_payload[0]["cover_url"] is None
    assert standalone_payload[0]["download_url"].endswith(f"/reader/books/{standalone_payload[0]['id']}/download")

    opds_series_response = client.get("/reader/opds/series", auth=("reader", token))
    assert opds_series_response.status_code == 200

    import xml.etree.ElementTree as ET

    ATOM = "{http://www.w3.org/2005/Atom}"
    root = ET.fromstring(opds_series_response.content)
    entries = root.findall(f"{ATOM}entry")
    assert [entry.findtext(f"{ATOM}title") for entry in entries] == ["Arcane Saga", "No Cover Chronicle"]
    series_link = entries[0].find(f"{ATOM}link")
    assert series_link is not None
    assert series_link.get("href", "").endswith("/reader/opds/series/Arcane%20Saga")

    opds_series_books_response = client.get("/reader/opds/series/Arcane%20Saga", auth=("reader", token))
    assert opds_series_books_response.status_code == 200
    books_root = ET.fromstring(opds_series_books_response.content)
    self_links = [link.get("href") for link in books_root.findall(f"{ATOM}link") if link.get("rel") == "self"]
    assert self_links == ["http://testserver/reader/opds/series/Arcane%20Saga"]
    book_entries = books_root.findall(f"{ATOM}entry")
    assert [entry.findtext(f"{ATOM}title") for entry in book_entries] == ["Arcane Saga 1", "Arcane Saga 2"]


@pytest.mark.asyncio
async def test_reader_books_all_returns_only_reader_eligible_books(db_session):
    async with AsyncTestingSessionLocal() as session:
        visible = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Collected Volume",
                author="Author A",
                immutable_path="library/immutable_collected.epub",
                current_path="library/collected.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Background Download",
                author="Author B",
                immutable_path="library/immutable_background.epub",
                current_path="library/background.epub",
                source_type=models.SourceType.epub,
                download_status="processing",
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Missing File Path",
                author="Author C",
                immutable_path="library/immutable_missing.epub",
                current_path=None,
                source_type=models.SourceType.epub,
            ),
        )
        covered = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Zeta Volume",
                author="Author D",
                immutable_path="library/immutable_zeta.epub",
                current_path="library/zeta.epub",
                cover_path="library/zeta.jpg",
                source_type=models.SourceType.epub,
            ),
        )

    key_response = client.post("/api/reader-keys", json={"label": "All Books Reader"})
    assert key_response.status_code == 201
    token = key_response.json()["token"]

    response = client.get("/reader/books/all", auth=("reader", token))
    assert response.status_code == 200

    payload = response.json()
    assert [book["title"] for book in payload] == ["Collected Volume", "Zeta Volume"]
    assert payload[0]["download_url"].endswith(f"/reader/books/{visible.id}/download")
    assert payload[0]["cover_url"] is None
    assert payload[1]["cover_url"].endswith(f"/reader/covers/{covered.id}")


@pytest.mark.asyncio
async def test_reader_opds_requires_auth_and_revoked_keys_fail(db_session):
    create_response = client.post("/api/reader-keys", json={"label": "Boox"})
    assert create_response.status_code == 201
    key = create_response.json()

    unauthenticated = client.get("/reader/opds")
    assert unauthenticated.status_code == 401

    authenticated = client.get("/reader/opds", auth=("reader", key["token"]))
    assert authenticated.status_code == 200
    assert "Story Manager Reader" in authenticated.text

    revoke_response = client.delete(f"/api/reader-keys/{key['id']}")
    assert revoke_response.status_code == 204

    revoked = client.get("/reader/opds", auth=("reader", key["token"]))
    assert revoked.status_code == 401
