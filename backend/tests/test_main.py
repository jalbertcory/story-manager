import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from pathlib import Path

from ebooklib import epub
from backend.app.main import app
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
async def test_add_web_novel(db_session, mocker):
    """
    Test adding a new web novel. This test mocks the fanficfare call and simulates file creation.
    """
    # Mock the fanficfare main function to simulate a successful download
    mocker.patch("backend.app.main._run_fff_main", return_value=0)

    # Define absolute paths for our dummy files, as the application uses resolve()
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)

    epub_filename = "Test Story-Test Author.epub"
    epub_path = library_path / epub_filename

    # Ensure the library is empty before the test
    if epub_path.exists():
        epub_path.unlink()

    # Create a dummy EPUB file with metadata. The endpoint will read from this.
    create_dummy_epub(epub_path, "Test Story", "Test Author", "Test Series")

    # The endpoint discovers the new file by checking the directory before and after the call.
    # We mock `iterdir` to simulate this.
    mocker.patch(
        "pathlib.Path.iterdir",
        side_effect=[iter([]), iter([epub_path])],  # Files before call  # Files after call
    )

    # Mock `read_epub` to return a book with the expected metadata
    mock_book = epub.EpubBook()
    mock_book.set_title("Test Story")
    mock_book.add_author("Test Author")
    mock_book.add_metadata("calibre", "series", "Test Series")
    mocker.patch("backend.app.main.epub.read_epub", return_value=mock_book)

    # The payload for the POST request
    payload = {"url": "http://example.com/story/123"}
    response = client.post("/api/books/add_web_novel", json=payload)

    # Clean up the dummy files
    if epub_path.exists():
        epub_path.unlink()
    immutable_path = library_path / f"immutable_{epub_filename}"
    if immutable_path.exists():
        immutable_path.unlink()

    # Check the response
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Story"
    assert data["author"] == "Test Author"
    assert data["source_url"] == "http://example.com/story/123"
    assert data["immutable_path"] == str(Path("library") / f"immutable_{epub_filename}")
    assert data["current_path"] == str(Path("library") / epub_filename)

    # Verify that the book was added to the database
    response = client.get("/api/books")
    assert response.status_code == 200
    books = response.json()
    assert len(books) == 1
    assert books[0]["title"] == "Test Story"


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


@pytest.mark.asyncio
async def test_upload_epub(db_session):
    """
    Test uploading an EPUB file.
    """
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    epub_filename = "Uploaded Book.epub"
    epub_filepath = library_path / epub_filename
    immutable_filepath = library_path / f"immutable_{epub_filename}"

    # Create a dummy epub file
    create_dummy_epub(epub_filepath, "Uploaded Book", "Uploader", "Upload Series")

    with open(epub_filepath, "rb") as f:
        response = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})

    # Clean up the dummy files
    epub_filepath.unlink()
    immutable_filepath.unlink()

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Uploaded Book"
    assert data["author"] == "Uploader"
    assert data["series"] == "Upload Series"
    assert data["immutable_path"] == str(Path("library") / f"immutable_{epub_filename}")
    assert data["current_path"] == str(Path("library") / epub_filename)
    assert data["master_word_count"] > 0
    assert data["current_word_count"] == data["master_word_count"]

    # Verify that the book was added to the database
    response = client.get("/api/books")
    assert response.status_code == 200
    books = response.json()
    assert len(books) == 1
    assert books[0]["title"] == "Uploaded Book"


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
    assert data[0]["title"] == "chap_1.xhtml"


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

    # Update the book with chapters to remove and divs to clean
    update_payload = {
        "removed_chapters": ["chap_1.xhtml"],
        "div_selectors": ["p"],  # This will remove the paragraph
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
        "backend.app.main._download_and_parse_web_novel",
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
