"""Reader keys, reader JSON routes and OPDS feeds."""

import pytest

from backend.app import crud, models, schemas
from api_harness import AsyncTestingSessionLocal, client


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
                download_status="pending",
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
async def test_reader_opds_and_json_include_web_book_source_url(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Web Reader Story",
                author="Author W",
                immutable_path="library/immutable_web_reader.epub",
                current_path="library/web_reader.epub",
                source_type=models.SourceType.web,
                source_url="https://example.com/story/reader",
                current_word_count=1500,
            ),
        )

    key_response = client.post("/api/reader-keys", json={"label": "Web Reader"})
    assert key_response.status_code == 201
    token = key_response.json()["token"]

    books_response = client.get("/reader/books/all", auth=("reader", token))
    assert books_response.status_code == 200
    assert books_response.json()[0]["source_url"] == "https://example.com/story/reader"

    import xml.etree.ElementTree as ET

    ATOM = "{http://www.w3.org/2005/Atom}"
    opds_response = client.get("/reader/opds/catalog", auth=("reader", token))
    assert opds_response.status_code == 200
    root = ET.fromstring(opds_response.content)
    entry = root.find(f"{ATOM}entry")
    assert entry is not None
    alternate_links = [link for link in entry.findall(f"{ATOM}link") if link.get("rel") == "alternate"]
    assert len(alternate_links) == 1
    assert alternate_links[0].get("href") == "https://example.com/story/reader"
    assert alternate_links[0].get("type") == "text/html"


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
                download_status="pending",
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
