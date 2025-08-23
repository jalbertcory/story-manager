import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from pathlib import Path
import configparser
import os

import ebooklib
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
AsyncTestingSessionLocal = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Override the `get_db` dependency to use the async test database
async def override_get_db():
    async with AsyncTestingSessionLocal() as session:
        yield session

app.dependency_overrides[get_db] = override_get_db

# Async pytest fixture to set up and tear down the database for each test function
@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

# The TestClient for making requests to the app
client = TestClient(app)

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
    mocker.patch("backend.app.main.fff_main", return_value=0)

    # Define absolute paths for our dummy files, as the application uses resolve()
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)

    epub_filename = "Test Story-Test Author.epub"
    epub_path = library_path / epub_filename
    metadata_path = library_path / "Test Story-Test Author.fff_metadata"

    # Ensure the library is empty before the test
    if epub_path.exists(): epub_path.unlink()
    if metadata_path.exists(): metadata_path.unlink()

    # The endpoint discovers the new file by checking the directory before and after the call.
    # We mock `iterdir` to simulate this.
    mocker.patch("pathlib.Path.iterdir", side_effect=[
        iter([]),  # Files before call
        iter([epub_path, metadata_path])  # Files after call
    ])

    # Write dummy metadata to the file that the endpoint will read
    config = configparser.ConfigParser()
    config['metadata'] = {'title': 'Test Story', 'author': 'Test Author'}
    with open(metadata_path, 'w') as f:
        config.write(f)

    # The payload for the POST request
    payload = {"url": "http://example.com/story/123"}
    response = client.post("/api/books/add_web_novel", json=payload)

    # Clean up the dummy file
    metadata_path.unlink()

    # Check the response
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Story"
    assert data["author"] == "Test Author"
    assert data["source_url"] == "http://example.com/story/123"
    # The path stored should be relative to the project root (parent of 'library')
    assert data["epub_path"] == str(Path('library') / epub_filename)

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
            epub_path="library/Existing Story-Existing Author.epub"
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
        book.add_metadata('calibre', 'series', series)
    # Add a dummy chapter
    c1 = epub.EpubHtml(title='Intro', file_name='chap_1.xhtml', lang='en')
    c1.content=u'<h1>Introduction</h1><p>Introduction text.</p>'
    book.add_item(c1)
    book.toc = (epub.Link('chap_1.xhtml', 'Introduction', 'intro'),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ['nav', c1]
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

    # Create a dummy epub file
    create_dummy_epub(epub_filepath, "Uploaded Book", "Uploader", "Upload Series")

    with open(epub_filepath, "rb") as f:
        response = client.post("/api/books/upload_epub", files={"file": (epub_filename, f, "application/epub+zip")})

    # Clean up the dummy file
    epub_filepath.unlink()

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Uploaded Book"
    assert data["author"] == "Uploader"
    assert data["series"] == "Upload Series"
    assert data["epub_path"] == str(Path('library') / epub_filename)

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
        await crud.create_book(session, schemas.BookCreate(title="Book 1", author="Author A", epub_path="p1"))
        await crud.create_book(session, schemas.BookCreate(title="Book 2", author="Author B", epub_path="p2"))
        await crud.create_book(session, schemas.BookCreate(title="Book 3", author="Author A", epub_path="p3"))

    response = client.get("/api/books/search/author/Author A")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {b['title'] for b in data} == {"Book 1", "Book 3"}

    response = client.get("/api/books/search/author/author b") # case-insensitive
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]['title'] == "Book 2"

@pytest.mark.asyncio
async def test_search_books_by_series(db_session):
    """
    Test searching for books by series.
    """
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(session, schemas.BookCreate(title="Book 1", author="Author A", series="Series X", epub_path="p1"))
        await crud.create_book(session, schemas.BookCreate(title="Book 2", author="Author B", series="Series Y", epub_path="p2"))
        await crud.create_book(session, schemas.BookCreate(title="Book 3", author="Author A", series="Series X", epub_path="p3"))

    response = client.get("/api/books/search/series/Series X")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert {b['title'] for b in data} == {"Book 1", "Book 3"}

    response = client.get("/api/books/search/series/series y") # case-insensitive
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]['title'] == "Book 2"
