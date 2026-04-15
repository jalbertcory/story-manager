import pytest
import pytest_asyncio
import zipfile
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from pathlib import Path

from ebooklib import epub
from backend.app.main import app
from backend.app.services import update_scheduler, web_novel
from backend.app.services.series import SeriesBook, detect_series_from_books, detect_series_from_titles
from backend.app.database import Base, get_db
from backend.app import crud, epub_editor, models, schemas

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
async def test_get_book_catalog_includes_series_and_effective_genre_tags(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Catalog Book",
                author="Catalog Author",
                series="Catalog Saga",
                immutable_path="catalog-immutable.epub",
                current_path="catalog.epub",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy"],
                user_genre_tags=["Progression Fantasy"],
            ),
        )
        await crud.set_series_user_genre_tags(session, "Catalog Saga", ["Adventure", "Fantasy"])

    response = client.get("/api/books/catalog")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["series_user_genre_tags"] == ["Adventure", "Fantasy"]
    assert data[0]["effective_genre_tags"] == ["Adventure", "Fantasy", "Progression Fantasy"]


@pytest.mark.asyncio
async def test_update_series_genres_updates_catalog_effective_genres(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Series Book",
                author="Series Author",
                series="Dragon Saga",
                immutable_path="dragon-saga-immutable.epub",
                current_path="dragon-saga.epub",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy"],
            ),
        )

    response = client.put(
        "/api/series/Dragon%20Saga/genres",
        json={"user_genre_tags": [" Progression Fantasy ", "Fantasy", "Progression Fantasy"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "series_name": "Dragon Saga",
        "user_genre_tags": ["Fantasy", "Progression Fantasy"],
    }

    catalog_response = client.get("/api/books/catalog")

    assert catalog_response.status_code == 200
    catalog_data = catalog_response.json()
    assert catalog_data[0]["series_user_genre_tags"] == ["Fantasy", "Progression Fantasy"]
    assert catalog_data[0]["effective_genre_tags"] == ["Fantasy", "Progression Fantasy"]


@pytest.mark.asyncio
async def test_metadata_sync_preview_returns_genres_and_possible_missing_series_books(db_session, mocker):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Dragon Saga 1",
                author="Alice Smith",
                series="Dragon Saga",
                immutable_path="dragon-1-immutable.epub",
                current_path="dragon-1.epub",
                source_type=models.SourceType.epub,
            ),
        )

    def fake_open_library_get(url, params=None, timeout=None, headers=None):
        if url == "https://openlibrary.org/search.json":
            return FakeRequestsResponse(
                {
                    "docs": [
                        {
                            "key": "/works/OL1W",
                            "title": "Dragon Saga 1",
                            "author_name": ["Alice Smith"],
                            "author_key": ["OLA1A"],
                            "cover_edition_key": "OL99M",
                        }
                    ]
                }
            )
        if url == "https://openlibrary.org/works/OL1W.json":
            return FakeRequestsResponse({"subjects": ["Fantasy", "Adventure stories"]})
        if url == "https://openlibrary.org/authors/OLA1A/works.json":
            return FakeRequestsResponse(
                {
                    "entries": [
                        {"title": "Dragon Saga 1"},
                        {"title": "Dragon Saga 2"},
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    mocker.patch("backend.app.services.metadata_sync.requests.get", side_effect=fake_open_library_get)

    response = client.post("/api/metadata/sync-preview", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["scanned_books"] == 1
    assert data["matched_books"] == 1
    assert data["books_with_new_genres"] == 1
    assert data["books_with_missing_series_candidates"] == 1
    assert data["results"][0]["genre_tags"] == ["Fantasy", "Adventure"]
    assert data["results"][0]["new_genre_tags"] == ["Fantasy", "Adventure"]
    assert data["results"][0]["possible_missing_series_books"] == ["Dragon Saga 2"]


@pytest.mark.asyncio
async def test_metadata_sync_apply_persists_genres_and_provenance(db_session, mocker):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Dragon Saga 1",
                author="Alice Smith",
                series="Dragon Saga",
                immutable_path="dragon-1-immutable.epub",
                current_path="dragon-1.epub",
                source_type=models.SourceType.epub,
                genre_tags=["Adventure"],
            ),
        )

    def fake_open_library_get(url, params=None, timeout=None, headers=None):
        if url == "https://openlibrary.org/search.json":
            return FakeRequestsResponse(
                {
                    "docs": [
                        {
                            "key": "/works/OL1W",
                            "title": "Dragon Saga 1",
                            "author_name": ["Alice Smith"],
                            "author_key": ["OLA1A"],
                            "cover_edition_key": "OL99M",
                        }
                    ]
                }
            )
        if url == "https://openlibrary.org/works/OL1W.json":
            return FakeRequestsResponse({"subjects": ["Fantasy", "Adventure stories"]})
        if url == "https://openlibrary.org/authors/OLA1A/works.json":
            return FakeRequestsResponse({"entries": [{"title": "Dragon Saga 1"}]})
        raise AssertionError(f"Unexpected URL: {url}")

    mocker.patch("backend.app.services.metadata_sync.requests.get", side_effect=fake_open_library_get)

    response = client.post("/api/metadata/apply", json={"book_ids": [book.id]})

    assert response.status_code == 200
    data = response.json()
    assert data["updated_books"] == 1
    assert data["results"][0]["new_genre_tags"] == ["Fantasy"]

    async with AsyncTestingSessionLocal() as session:
        stored = await crud.get_book(session, book.id)
        assert stored is not None
        assert stored.genre_tags == ["Adventure", "Fantasy"]
        assert stored.metadata_sync_source == "open_library"
        assert stored.metadata_remote_ids == {
            "open_library_work_key": "/works/OL1W",
            "open_library_author_key": "OLA1A",
            "open_library_edition_key": "OL99M",
        }
        assert stored.metadata_synced_at is not None

    response = client.get("/api/books/catalog?q=Fantasy&sort_by=title&sort_order=asc")
    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["Dragon Saga 1"]


@pytest.mark.asyncio
async def test_metadata_sync_uses_manual_isbn_identifier(db_session, mocker):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Manual ID Book",
                author="Manual Author",
                immutable_path="manual-id-immutable.epub",
                current_path="manual-id.epub",
                source_type=models.SourceType.epub,
                metadata_remote_ids={"isbn_13": "9780316339158"},
            ),
        )

    def fake_open_library_get(url, params=None, timeout=None, headers=None):
        if url == "https://openlibrary.org/search.json":
            if params.get("isbn") == "9780316339158":
                return FakeRequestsResponse(
                    {
                        "docs": [
                            {
                                "key": "/works/OL42W",
                                "title": "Manual ID Book",
                                "author_name": ["Manual Author"],
                                "author_key": ["OLA42A"],
                                "isbn": ["9780316339158"],
                            }
                        ]
                    }
                )
            return FakeRequestsResponse({"docs": []})
        if url == "https://openlibrary.org/works/OL42W.json":
            return FakeRequestsResponse({"subjects": ["Fantasy"]})
        if url == "https://openlibrary.org/authors/OLA42A/works.json":
            return FakeRequestsResponse({"entries": [{"title": "Manual ID Book"}]})
        raise AssertionError(f"Unexpected URL: {url}")

    mocker.patch("backend.app.services.metadata_sync.requests.get", side_effect=fake_open_library_get)

    response = client.post("/api/metadata/sync-preview", json={})

    assert response.status_code == 200
    assert response.json()["matched_books"] == 1


@pytest.mark.asyncio
async def test_metadata_sync_falls_back_to_google_books_when_open_library_has_no_match(db_session, mocker):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Fallback Book",
                author="Google Author",
                immutable_path="fallback-immutable.epub",
                current_path="fallback.epub",
                source_type=models.SourceType.epub,
            ),
        )

    def fake_requests_get(url, params=None, timeout=None, headers=None):
        if url == "https://openlibrary.org/search.json":
            return FakeRequestsResponse({"docs": []})
        if url == "https://www.googleapis.com/books/v1/volumes":
            return FakeRequestsResponse(
                {
                    "items": [
                        {
                            "id": "google-volume-1",
                            "volumeInfo": {
                                "title": "Fallback Book",
                                "authors": ["Google Author"],
                                "categories": ["Fiction / Fantasy / Epic"],
                                "industryIdentifiers": [
                                    {"type": "ISBN_10", "identifier": "1234567890"},
                                    {"type": "ISBN_13", "identifier": "9781234567897"},
                                ],
                                "infoLink": "https://books.google.com/books?id=google-volume-1",
                            },
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    mocker.patch("backend.app.services.metadata_sync.GOOGLE_BOOKS_API_KEY", "test-key")
    mocker.patch("backend.app.services.metadata_sync.requests.get", side_effect=fake_requests_get)

    response = client.post("/api/metadata/apply", json={"book_ids": [book.id]})

    assert response.status_code == 200
    data = response.json()
    assert data["matched_books"] == 1
    assert data["updated_books"] == 1
    assert data["results"][0]["genre_tags"] == ["Fantasy"]

    async with AsyncTestingSessionLocal() as session:
        stored = await crud.get_book(session, book.id)
        assert stored is not None
        assert stored.genre_tags == ["Fantasy"]
        assert stored.metadata_sync_source == "google_books"
        assert stored.metadata_remote_ids == {
            "google_books_volume_id": "google-volume-1",
            "isbn_10": "1234567890",
            "isbn_13": "9781234567897",
        }


@pytest.mark.asyncio
async def test_metadata_sync_supplements_open_library_match_with_google_books_categories(db_session, mocker):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Supplemented Book",
                author="Alice Smith",
                immutable_path="supplemented-immutable.epub",
                current_path="supplemented.epub",
                source_type=models.SourceType.epub,
            ),
        )

    def fake_requests_get(url, params=None, timeout=None, headers=None):
        if url == "https://openlibrary.org/search.json":
            return FakeRequestsResponse(
                {
                    "docs": [
                        {
                            "key": "/works/OL55W",
                            "title": "Supplemented Book",
                            "author_name": ["Alice Smith"],
                            "author_key": ["OLA55A"],
                        }
                    ]
                }
            )
        if url == "https://openlibrary.org/works/OL55W.json":
            return FakeRequestsResponse({})
        if url == "https://openlibrary.org/authors/OLA55A/works.json":
            return FakeRequestsResponse({"entries": [{"title": "Supplemented Book"}]})
        if url == "https://www.googleapis.com/books/v1/volumes":
            return FakeRequestsResponse(
                {
                    "items": [
                        {
                            "id": "google-volume-55",
                            "volumeInfo": {
                                "title": "Supplemented Book",
                                "authors": ["Alice Smith"],
                                "categories": ["Fiction / Fantasy / Romance"],
                                "industryIdentifiers": [
                                    {"type": "ISBN_13", "identifier": "9780316339158"},
                                ],
                                "infoLink": "https://books.google.com/books?id=google-volume-55",
                            },
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    mocker.patch("backend.app.services.metadata_sync.GOOGLE_BOOKS_API_KEY", "test-key")
    mocker.patch("backend.app.services.metadata_sync.requests.get", side_effect=fake_requests_get)

    response = client.post("/api/metadata/apply", json={"book_ids": [book.id]})

    assert response.status_code == 200
    data = response.json()
    assert data["matched_books"] == 1
    assert data["updated_books"] == 1
    assert data["results"][0]["genre_tags"] == ["Fantasy", "Romance"]

    async with AsyncTestingSessionLocal() as session:
        stored = await crud.get_book(session, book.id)
        assert stored is not None
        assert stored.genre_tags == ["Fantasy", "Romance"]
        assert stored.metadata_sync_source == "open_library+google_books"
        assert stored.metadata_remote_ids == {
            "google_books_volume_id": "google-volume-55",
            "isbn_13": "9780316339158",
            "open_library_work_key": "/works/OL55W",
            "open_library_author_key": "OLA55A",
        }


@pytest.mark.asyncio
async def test_metadata_sync_uses_same_series_open_library_author_key_for_related_books(db_session, mocker):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Dragon Saga 1",
                author="Alice Smith",
                series="Dragon Saga",
                immutable_path="dragon-saga-1-immutable.epub",
                current_path="dragon-saga-1.epub",
                source_type=models.SourceType.epub,
                metadata_remote_ids={
                    "open_library_author_key": "OLA1A",
                    "open_library_work_key": "/works/OL1W",
                },
            ),
        )
        sequel = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Dragon Saga 2",
                author="Alice Smith",
                series="Dragon Saga",
                immutable_path="dragon-saga-2-immutable.epub",
                current_path="dragon-saga-2.epub",
                source_type=models.SourceType.epub,
            ),
        )

    def fake_open_library_get(url, params=None, timeout=None, headers=None):
        if url == "https://openlibrary.org/search.json":
            return FakeRequestsResponse({"docs": []})
        if url == "https://openlibrary.org/authors/OLA1A/works.json":
            return FakeRequestsResponse(
                {
                    "entries": [
                        {"key": "/works/OL1W", "title": "Dragon Saga 1"},
                        {"key": "/works/OL2W", "title": "Dragon Saga 2"},
                    ]
                }
            )
        if url in {"https://openlibrary.org/works/OL1W.json", "https://openlibrary.org/works/OL2W.json"}:
            return FakeRequestsResponse({"subjects": ["Fantasy"]})
        raise AssertionError(f"Unexpected URL: {url}")

    mocker.patch("backend.app.services.metadata_sync.requests.get", side_effect=fake_open_library_get)

    response = client.post("/api/metadata/sync-preview", json={"book_ids": [sequel.id]})

    assert response.status_code == 200
    data = response.json()
    assert data["matched_books"] == 1
    assert data["results"][0]["remote_title"] == "Dragon Saga 2"


@pytest.mark.asyncio
async def test_create_metadata_job_enqueues_background_sync(db_session, mocker):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Queued Book",
                author="Queue Author",
                immutable_path="queued-immutable.epub",
                current_path="queued.epub",
                source_type=models.SourceType.epub,
            ),
        )

    queue = mocker.Mock()
    queue.enqueue = mocker.AsyncMock(return_value=True)
    mocker.patch("backend.app.services.metadata_sync_queue.get_metadata_sync_queue", return_value=queue)

    response = client.post("/api/metadata/jobs", json={"book_ids": [book.id], "trigger": "manual"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["total_books"] == 1
    queue.enqueue.assert_awaited_once_with(data["id"])


@pytest.mark.asyncio
async def test_metadata_inbox_lists_pending_match_proposals(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Inbox Book",
                author="Inbox Author",
                immutable_path="inbox-immutable.epub",
                current_path="inbox.epub",
                source_type=models.SourceType.epub,
            ),
        )
        match = models.BookMetadataMatch(
            book_id=book.id,
            status="pending",
            source="open_library",
            match_confidence=0.88,
            remote_title="Inbox Book",
            remote_author="Inbox Author",
            remote_url="https://openlibrary.org/works/OL123W",
            remote_ids={"open_library_work_key": "/works/OL123W"},
        )
        session.add(match)
        await session.flush()
        proposal = models.MetadataProposal(
            book_id=book.id,
            match_id=match.id,
            status="open",
            proposed_genre_tags=["Fantasy"],
            possible_missing_series_books=["Inbox Book 2"],
        )
        session.add(proposal)
        await session.commit()

    response = client.get("/api/metadata/inbox")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["book_title"] == "Inbox Book"
    assert data[0]["match"]["status"] == "pending"
    assert data[0]["proposed_genre_tags"] == ["Fantasy"]


@pytest.mark.asyncio
async def test_approve_metadata_match_applies_genres_and_resolves_proposal(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Approval Book",
                author="Approval Author",
                immutable_path="approval-immutable.epub",
                current_path="approval.epub",
                source_type=models.SourceType.epub,
            ),
        )
        match = models.BookMetadataMatch(
            book_id=book.id,
            status="pending",
            source="open_library",
            match_confidence=0.9,
            remote_title="Approval Book",
            remote_author="Approval Author",
            remote_url="https://openlibrary.org/works/OL500W",
            remote_ids={"open_library_work_key": "/works/OL500W"},
        )
        session.add(match)
        await session.flush()
        proposal = models.MetadataProposal(
            book_id=book.id,
            match_id=match.id,
            status="open",
            proposed_genre_tags=["Science Fiction"],
            possible_missing_series_books=[],
        )
        session.add(proposal)
        await session.commit()

    response = client.post(f"/api/metadata/matches/{match.id}/approve")

    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    async with AsyncTestingSessionLocal() as session:
        stored_book = await crud.get_book(session, book.id)
        stored_match = await crud.get_metadata_match(session, match.id)
        stored_proposal = await crud.get_metadata_proposal_by_book_id(session, book.id)
        assert stored_book.genre_tags == ["Science Fiction"]
        assert stored_book.metadata_sync_source == "open_library"
        assert stored_match.status == "approved"
        assert stored_proposal.status == "resolved"


@pytest.mark.asyncio
async def test_book_update_replaces_user_genre_tags(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="User Genre Book",
                author="User Genre Author",
                immutable_path="user-genre-immutable.epub",
                current_path="user-genre.epub",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy"],
                user_genre_tags=["Progression Fantasy"],
            ),
        )

    response = client.put(f"/api/books/{book.id}", json={"user_genre_tags": ["Romance", "Fantasy", "Romance", " LitRPG "]})

    assert response.status_code == 200
    data = response.json()
    assert data["genre_tags"] == ["Fantasy"]
    assert data["user_genre_tags"] == ["Fantasy", "LitRPG", "Romance"]


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
    Test adding a new web novel. The endpoint returns immediately with a pending record
    and enqueues the actual download onto the app-scoped worker queue.
    """
    queue = mocker.Mock()
    queue.enqueue = mocker.AsyncMock(return_value=True)

    mocker.patch("backend.app.routers.web_novels.get_web_import_queue", return_value=queue)

    payload = {"url": "http://example.com/story/123"}
    response = client.post("/api/books/add_web_novel", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["download_status"] == "pending"
    assert data["source_url"] == "http://example.com/story/123"
    assert data["immutable_path"] is None
    assert data["current_path"] is None
    queue.enqueue.assert_awaited_once_with(data["id"], "http://example.com/story/123")

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
async def test_library_validate_classifies_failed_web_import_placeholders(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Download failed",
                author="Pending",
                source_url="https://example.com/story/failed",
                source_type=models.SourceType.web,
                download_status="error",
            ),
        )

    response = client.get("/api/library/validate")

    assert response.status_code == 200
    data = response.json()
    assert data["issues_count"] == 1
    assert data["issues"] == [
        {
            "book_id": 1,
            "title": "Download failed",
            "author": "Pending",
            "issue": "failed_web_import",
            "source_url": "https://example.com/story/failed",
        }
    ]


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


class FakeRequestsResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


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
async def test_storage_cleanup_removes_failed_web_import_placeholders_and_orphans(db_session, tmp_path, monkeypatch):
    from backend.app.routers import storage as storage_router

    library_path = (tmp_path / "library").resolve()
    monkeypatch.setattr(storage_router, "LIBRARY_PATH", library_path)
    library_path.mkdir(parents=True, exist_ok=True)
    orphan_path = library_path / "orphan.epub"
    orphan_path.write_bytes(b"orphan")

    valid_author_dir = library_path / "Valid Author"
    valid_author_dir.mkdir(parents=True, exist_ok=True)
    valid_immutable = valid_author_dir / "immutable_Keep Me.epub"
    valid_current = valid_author_dir / "Keep Me.epub"
    create_dummy_epub(valid_immutable, "Keep Me", "Valid Author")
    create_dummy_epub(valid_current, "Keep Me", "Valid Author")

    async with AsyncTestingSessionLocal() as session:
        failed_book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Download failed",
                author="Pending",
                source_url="https://example.com/story/failed-cleanup",
                source_type=models.SourceType.web,
                download_status="error",
            ),
        )
        match = models.BookMetadataMatch(
            book_id=failed_book.id,
            status="pending",
            source="open_library",
            remote_title="Remote Failed Story",
            remote_author="Pending",
        )
        session.add(match)
        await session.flush()
        session.add(
            models.MetadataProposal(
                book_id=failed_book.id,
                match_id=match.id,
                status="open",
                proposed_genre_tags=["Fantasy"],
                possible_missing_series_books=[],
                note=None,
            )
        )
        keep_book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Keep Me",
                author="Valid Author",
                immutable_path=str(valid_immutable.relative_to(library_path.parent)),
                current_path=str(valid_current.relative_to(library_path.parent)),
                source_type=models.SourceType.epub,
            ),
        )

    preview_response = client.post("/api/storage/cleanup?dry_run=true")

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["dry_run"] is True
    assert preview["files"] == [{"path": "library/orphan.epub", "size_bytes": 6}]
    assert preview["books"] == [
        {
            "book_id": 1,
            "title": "Download failed",
            "author": "Pending",
            "source_url": "https://example.com/story/failed-cleanup",
            "issue": "failed_web_import",
        }
    ]

    delete_response = client.post("/api/storage/cleanup?dry_run=false")

    assert delete_response.status_code == 200
    deleted = delete_response.json()
    assert deleted["dry_run"] is False
    assert deleted["files"] == [{"path": "library/orphan.epub", "size_bytes": 6}]
    assert len(deleted["books"]) == 1
    assert not orphan_path.exists()

    books_response = client.get("/api/books")
    assert books_response.status_code == 200
    books = books_response.json()
    assert len(books) == 1
    assert books[0]["id"] == keep_book.id
    assert books[0]["title"] == "Keep Me"

    async with AsyncTestingSessionLocal() as session:
        remaining_match = await crud.get_metadata_match_by_book_id(session, failed_book.id)
        remaining_proposal = await crud.get_metadata_proposal_by_book_id(session, failed_book.id)
        assert remaining_match is None
        assert remaining_proposal is None


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


def test_get_next_run_time_for_interrupted_task_runs_soon():
    now = datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc)
    task = models.UpdateTask(status="interrupted", total_books=30, completed_books=14)
    task.started_at = now - timedelta(minutes=15)
    task.completed_at = now - timedelta(seconds=5)

    next_run = update_scheduler.get_next_run_time_for_task(task, now=now)

    assert next_run == now + update_scheduler.OVERDUE_RUN_DELAY


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
    assert data["schedule_mode"] == "interval"
    assert data["schedule_time_local"] is None
    assert data["schedule_timezone"] is None
    assert data["last_run_status"] == "completed"
    assert data["last_run_started_at"] is not None
    assert data["last_run_completed_at"] is not None


@pytest.mark.asyncio
async def test_update_scheduler_config_persists_daily_time_and_reschedules(db_session, mocker):
    class DummyJob:
        next_run_time = datetime(2026, 3, 20, 10, 30, tzinfo=timezone.utc)

    schedule_mock = mocker.patch(
        "backend.app.routers.scheduler.update_scheduler.schedule_next_web_novel_update",
        return_value=DummyJob.next_run_time,
    )
    mocker.patch("backend.app.routers.scheduler.update_scheduler.get_scheduled_job", return_value=DummyJob())
    mocker.patch("backend.app.routers.scheduler.update_scheduler.is_scheduler_running", return_value=True)
    mocker.patch("backend.app.routers.scheduler.update_scheduler.is_update_running", return_value=False)

    response = client.put(
        "/api/scheduler/config",
        json={"time_local": "06:30", "timezone": "America/New_York"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["schedule"] == "Daily at 6:30 AM (America/New_York)"
    assert data["schedule_mode"] == "daily_time"
    assert data["schedule_time_local"] == "06:30"
    assert data["schedule_timezone"] == "America/New_York"
    assert data["next_run_at"] == "2026-03-20T10:30:00Z"
    schedule_mock.assert_awaited_once()

    async with AsyncTestingSessionLocal() as session:
        settings = await crud.get_scheduler_settings(session)
        assert settings is not None
        assert settings.web_novel_schedule_hour == 6
        assert settings.web_novel_schedule_minute == 30
        assert settings.web_novel_schedule_timezone == "America/New_York"


@pytest.mark.asyncio
async def test_update_web_novels_counts_and_logs_book_failures(db_session, mocker):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Broken Book A",
                author="Author",
                immutable_path="broken_a.epub",
                current_path="broken_a_current.epub",
                source_type=models.SourceType.web,
                source_url="https://example.com/broken-a",
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Broken Book B",
                author="Author",
                immutable_path="broken_b.epub",
                current_path="broken_b_current.epub",
                source_type=models.SourceType.web,
                source_url="https://example.com/broken-b",
            ),
        )

    mocker.patch("backend.app.services.web_novel.get_epub_word_and_chapter_count", return_value=(1000, 10))
    mocker.patch(
        "backend.app.services.web_novel.download_web_novel",
        side_effect=HTTPException(status_code=500, detail="boom"),
    )
    mocker.patch("backend.app.services.web_novel.SessionLocal", AsyncTestingSessionLocal)

    await web_novel.update_web_novels()

    async with AsyncTestingSessionLocal() as session:
        task = await crud.get_latest_update_task(session)
        assert task is not None
        assert task.total_books == 2
        assert task.completed_books == 2
        assert task.status == "failed"

        logs = await crud.get_book_logs_for_task(session, task.id)
        _, rows = logs
        assert rows is not None
        assert len(rows) == 2
        assert {row[0].entry_type for row in rows} == {"error"}


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
async def test_search_books_by_series_orders_by_series_index_then_title(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Later Title",
                author="Author A",
                series="Series X",
                series_index=2,
                immutable_path="sx2i",
                current_path="sx2c",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Earlier Title",
                author="Author A",
                series="Series X",
                series_index=1,
                immutable_path="sx1i",
                current_path="sx1c",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="No Number",
                author="Author A",
                series="Series X",
                immutable_path="sxni",
                current_path="sxnc",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.get("/api/books/search/series/Series X")
    assert response.status_code == 200
    data = response.json()
    assert [book["title"] for book in data] == ["Earlier Title", "Later Title", "No Number"]


@pytest.mark.asyncio
async def test_reorder_series_persists_series_index(db_session):
    async with AsyncTestingSessionLocal() as session:
        first = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book One",
                author="Author A",
                series="Series X",
                immutable_path="r1i",
                current_path="r1c",
                source_type=models.SourceType.epub,
            ),
        )
        second = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book Two",
                author="Author A",
                series="Series X",
                immutable_path="r2i",
                current_path="r2c",
                source_type=models.SourceType.epub,
            ),
        )
        third = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book Three",
                author="Author A",
                series="Series X",
                immutable_path="r3i",
                current_path="r3c",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.post(
        "/api/series/Series%20X/reorder",
        json={"ordered_book_ids": [third.id, first.id, second.id]},
    )
    assert response.status_code == 200
    assert response.json()["updated"] == 3

    response = client.get("/api/books/search/series/Series X")
    assert response.status_code == 200
    data = response.json()
    assert [(book["id"], book["series_index"]) for book in data] == [
        (third.id, 1),
        (first.id, 2),
        (second.id, 3),
    ]


@pytest.mark.asyncio
async def test_update_book_clears_series_index_when_series_removed(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book One",
                author="Author A",
                series="Series X",
                series_index=2.5,
                immutable_path="u1i",
                current_path="u1c",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.put(f"/api/books/{book.id}", json={"series": None})
    assert response.status_code == 200
    data = response.json()
    assert data["series"] is None
    assert data["series_index"] is None


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
async def test_scheduler_history_task_logs_includes_error_entries(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Errored Book",
                author="Author",
                immutable_path="err_i",
                current_path="err_c",
                source_type=models.SourceType.web,
                source_url="http://example.com/err",
            ),
        )
        task = await crud.create_update_task(session, total_books=1)
        await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book.id,
                entry_type="error",
                previous_chapter_count=12,
                new_chapter_count=12,
                words_added=0,
            ),
        )
        await crud.fail_update_task(session, task)

    response = client.get(f"/api/scheduler/history/{task.id}/logs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["entry_type"] == "error"
    assert data[0]["book_title"] == "Errored Book"


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
                series="Reader Cycle",
                series_index=1.5,
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
    assert payload[0]["series"] == "Reader Cycle"
    assert payload[0]["series_index"] == 1.5


@pytest.mark.asyncio
async def test_reader_series_api_and_opds_feeds(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Arcane Saga 1",
                author="Author A",
                series="Arcane Saga",
                series_index=1,
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
                series_index=2,
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
    assert [book["series_index"] for book in books_payload] == [1.0, 2.0]

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
                series="Collections",
                series_index=4,
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
    assert payload[0]["series_index"] == 4.0
    assert payload[1]["series_index"] is None
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


@pytest.mark.asyncio
async def test_get_series_genres_endpoint(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Genre Book",
                author="Author",
                series="Test Series",
                immutable_path="genre-immutable.epub",
                current_path="genre.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.set_series_user_genre_tags(session, "Test Series", ["Fantasy", "Adventure"])

    response = client.get("/api/series/Test%20Series/genres")
    assert response.status_code == 200
    data = response.json()
    assert data["series_name"] == "Test Series"
    assert data["user_genre_tags"] == ["Adventure", "Fantasy"]


@pytest.mark.asyncio
async def test_get_series_genres_returns_404_for_unknown_series(db_session):
    response = client.get("/api/series/Nonexistent/genres")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_rename_series_merges_metadata(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Old Book",
                author="Author",
                series="Old Series",
                immutable_path="old-immutable.epub",
                current_path="old.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="New Book",
                author="Author",
                series="New Series",
                immutable_path="new-immutable.epub",
                current_path="new.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.set_series_user_genre_tags(session, "Old Series", ["Fantasy"])
        await crud.set_series_user_genre_tags(session, "New Series", ["Adventure"])

    response = client.put("/api/series/Old%20Series", json={"new_name": "New Series"})
    assert response.status_code == 200

    genres_response = client.get("/api/series/New%20Series/genres")
    assert genres_response.status_code == 200
    tags = genres_response.json()["user_genre_tags"]
    assert "Adventure" in tags
    assert "Fantasy" in tags


@pytest.mark.asyncio
async def test_rename_series_preserves_metadata_when_target_has_none(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Rename Book",
                author="Author",
                series="Rename Me",
                immutable_path="rename-immutable.epub",
                current_path="rename.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.set_series_user_genre_tags(session, "Rename Me", ["Sci-Fi"])

    response = client.put("/api/series/Rename%20Me", json={"new_name": "Renamed"})
    assert response.status_code == 200

    genres_response = client.get("/api/series/Renamed/genres")
    assert genres_response.status_code == 200
    assert genres_response.json()["user_genre_tags"] == ["Sci-Fi"]


@pytest.mark.asyncio
async def test_merge_series_merges_metadata(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Source Book",
                author="Author",
                series="Source Series",
                immutable_path="source-immutable.epub",
                current_path="source.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Target Book",
                author="Author",
                series="Target Series",
                immutable_path="target-immutable.epub",
                current_path="target.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.set_series_user_genre_tags(session, "Source Series", ["Fantasy", "Dark Fantasy"])
        await crud.set_series_user_genre_tags(session, "Target Series", ["Fantasy", "Adventure"])

    response = client.post(
        "/api/series/merge",
        json={"source": "Source Series", "target": "Target Series"},
    )
    assert response.status_code == 200

    genres_response = client.get("/api/series/Target%20Series/genres")
    assert genres_response.status_code == 200
    tags = genres_response.json()["user_genre_tags"]
    assert "Adventure" in tags
    assert "Dark Fantasy" in tags
    assert "Fantasy" in tags


@pytest.mark.asyncio
async def test_merge_series_moves_metadata_when_target_has_none(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Source Only Book",
                author="Author",
                series="Has Tags",
                immutable_path="has-tags-immutable.epub",
                current_path="has-tags.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="No Tags Book",
                author="Author",
                series="No Tags",
                immutable_path="no-tags-immutable.epub",
                current_path="no-tags.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.set_series_user_genre_tags(session, "Has Tags", ["Progression Fantasy"])

    response = client.post(
        "/api/series/merge",
        json={"source": "Has Tags", "target": "No Tags"},
    )
    assert response.status_code == 200

    genres_response = client.get("/api/series/No%20Tags/genres")
    assert genres_response.status_code == 200
    assert genres_response.json()["user_genre_tags"] == ["Progression Fantasy"]


@pytest.mark.asyncio
async def test_orphaned_series_metadata_cleaned_up_on_book_delete(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Orphan Book",
                author="Author",
                series="Orphan Series",
                immutable_path="orphan-immutable.epub",
                current_path="orphan.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await crud.set_series_user_genre_tags(session, "Orphan Series", ["Fantasy"])
        book_id = book.id

    # Verify metadata exists
    genres_response = client.get("/api/series/Orphan%20Series/genres")
    assert genres_response.status_code == 200
    assert genres_response.json()["user_genre_tags"] == ["Fantasy"]

    # Delete the only book in the series
    client.delete(f"/api/books/{book_id}")

    # Metadata should be cleaned up
    genres_response = client.get("/api/series/Orphan%20Series/genres")
    assert genres_response.status_code == 404


@pytest.mark.asyncio
async def test_tag_validation_rejects_too_many_tags(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Validation Book",
                author="Author",
                series="Validation Series",
                immutable_path="validation-immutable.epub",
                current_path="validation.epub",
                source_type=models.SourceType.epub,
            ),
        )

    tags = [f"Tag {i}" for i in range(21)]
    response = client.put(
        "/api/series/Validation%20Series/genres",
        json={"user_genre_tags": tags},
    )
    assert response.status_code == 400
    assert "Maximum 20" in response.json()["detail"]


@pytest.mark.asyncio
async def test_tag_validation_rejects_too_long_tags(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Long Tag Book",
                author="Author",
                series="Long Tag Series",
                immutable_path="longtag-immutable.epub",
                current_path="longtag.epub",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.put(
        "/api/series/Long%20Tag%20Series/genres",
        json={"user_genre_tags": ["x" * 51]},
    )
    assert response.status_code == 400
    assert "50 characters" in response.json()["detail"]


@pytest.mark.asyncio
async def test_catalog_includes_effective_series_genre_tags_from_books(db_session):
    """When a series has no explicit tags, effective_series_genre_tags falls back to book-level tags."""
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book A",
                author="Author",
                series="Fallback Series",
                immutable_path="fallback-a-immutable.epub",
                current_path="fallback-a.epub",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy", "Adventure"],
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Book B",
                author="Author",
                series="Fallback Series",
                immutable_path="fallback-b-immutable.epub",
                current_path="fallback-b.epub",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy", "Romance"],
            ),
        )

    response = client.get("/api/books/catalog")
    assert response.status_code == 200
    data = response.json()
    series_books = [b for b in data if b["series"] == "Fallback Series"]
    assert len(series_books) == 2
    # Fantasy appears in both books (2/2 >= ceil(2/2)=1), Adventure and Romance in 1 each
    effective_series = series_books[0]["effective_series_genre_tags"]
    assert "Fantasy" in effective_series
    assert "Adventure" in effective_series
    assert "Romance" in effective_series


@pytest.mark.asyncio
async def test_catalog_effective_series_genre_tags_uses_explicit_when_set(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Explicit Book",
                author="Author",
                series="Explicit Series",
                immutable_path="explicit-immutable.epub",
                current_path="explicit.epub",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy", "Adventure", "Romance"],
            ),
        )
        await crud.set_series_user_genre_tags(session, "Explicit Series", ["Sci-Fi"])

    response = client.get("/api/books/catalog")
    assert response.status_code == 200
    data = response.json()
    book = [b for b in data if b["series"] == "Explicit Series"][0]
    assert book["effective_series_genre_tags"] == ["Sci-Fi"]
