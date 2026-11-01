"""Metadata sync, match inbox and background metadata job routes."""

import pytest

from backend.app import crud, models, schemas
from api_harness import AsyncTestingSessionLocal, client, FakeRequestsResponse, _assert_single_processing_job


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

    mocker.patch("backend.app.services.metadata.clients.requests.get", side_effect=fake_open_library_get)

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

    mocker.patch("backend.app.services.metadata.clients.requests.get", side_effect=fake_open_library_get)

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
    assert [item["title"] for item in response.json()["items"]] == ["Dragon Saga 1"]


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

    mocker.patch("backend.app.services.metadata.clients.requests.get", side_effect=fake_open_library_get)

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

    mocker.patch("backend.app.services.metadata.clients.GOOGLE_BOOKS_API_KEY", "test-key")
    mocker.patch("backend.app.services.metadata.clients.requests.get", side_effect=fake_requests_get)

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

    mocker.patch("backend.app.services.metadata.clients.GOOGLE_BOOKS_API_KEY", "test-key")
    mocker.patch("backend.app.services.metadata.clients.requests.get", side_effect=fake_requests_get)

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

    mocker.patch("backend.app.services.metadata.clients.requests.get", side_effect=fake_open_library_get)

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

    response = client.post("/api/metadata/jobs", json={"book_ids": [book.id], "trigger": "manual"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["total_books"] == 1
    await _assert_single_processing_job("metadata_sync", data["id"])


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
    assert data[0]["candidate_matches"][0]["id"] == match.id
    assert data[0]["proposed_genre_tags"] == ["Fantasy"]


@pytest.mark.asyncio
async def test_metadata_job_keeps_close_match_candidates_for_human_selection(db_session, mocker):
    from backend.app.services.metadata_jobs import process_metadata_sync_job

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Dragon Saga 7",
                author="Alice Smith",
                series="Dragon Saga",
                immutable_path="dragon-7-immutable.epub",
                current_path="dragon-7.epub",
                source_type=models.SourceType.epub,
            ),
        )
        job = await crud.create_metadata_sync_job(session, trigger="manual", book_ids=[book.id])

    def fake_open_library_get(url, params=None, timeout=None, headers=None):
        if url == "https://openlibrary.org/search.json":
            return FakeRequestsResponse(
                {
                    "docs": [
                        {
                            "key": "/works/OL6W",
                            "title": "Dragon Saga 6",
                            "author_name": ["Alice Smith"],
                            "author_key": ["OLA1A"],
                        },
                        {
                            "key": "/works/OL8W",
                            "title": "Dragon Saga 8",
                            "author_name": ["Alice Smith"],
                            "author_key": ["OLA1A"],
                        },
                    ]
                }
            )
        if url in {"https://openlibrary.org/works/OL6W.json", "https://openlibrary.org/works/OL8W.json"}:
            return FakeRequestsResponse({"subjects": ["Fantasy"]})
        if url == "https://openlibrary.org/authors/OLA1A/works.json":
            return FakeRequestsResponse({"entries": [{"title": "Dragon Saga 6"}, {"title": "Dragon Saga 8"}]})
        raise AssertionError(f"Unexpected URL: {url}")

    mocker.patch("backend.app.services.metadata.clients.requests.get", side_effect=fake_open_library_get)

    async with AsyncTestingSessionLocal() as session:
        await process_metadata_sync_job(session, job.id)

    response = client.get("/api/metadata/inbox")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    candidate_titles = {candidate["remote_title"] for candidate in data[0]["candidate_matches"]}
    assert candidate_titles == {"Dragon Saga 6", "Dragon Saga 8"}
    assert data[0]["match"]["status"] == "pending"


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
async def test_reject_metadata_match_keeps_proposal_open_for_other_candidates(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Candidate Book",
                author="Candidate Author",
                immutable_path="candidate-immutable.epub",
                current_path="candidate.epub",
                source_type=models.SourceType.epub,
            ),
        )
        first_match = models.BookMetadataMatch(
            book_id=book.id,
            status="pending",
            source="open_library",
            match_confidence=0.9,
            remote_title="Candidate Book 6",
            remote_author="Candidate Author",
            remote_ids={"open_library_work_key": "/works/OL6W"},
        )
        second_match = models.BookMetadataMatch(
            book_id=book.id,
            status="pending",
            source="open_library",
            match_confidence=0.89,
            remote_title="Candidate Book 8",
            remote_author="Candidate Author",
            remote_ids={"open_library_work_key": "/works/OL8W"},
        )
        session.add_all([first_match, second_match])
        await session.flush()
        session.add(
            models.MetadataProposal(
                book_id=book.id,
                match_id=first_match.id,
                status="open",
                proposed_genre_tags=["Fantasy"],
                possible_missing_series_books=[],
            )
        )
        await session.commit()

    response = client.post(f"/api/metadata/matches/{first_match.id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    async with AsyncTestingSessionLocal() as session:
        stored_proposal = await crud.get_metadata_proposal_by_book_id(session, book.id)
        assert stored_proposal.status == "open"
        assert stored_proposal.match_id == second_match.id
