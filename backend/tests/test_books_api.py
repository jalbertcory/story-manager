"""Book list, catalog, search, details, revisions, recycle bin and static cover routes."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app import crud, models, schemas
from backend.app.services import library_paths
from api_harness import AsyncTestingSessionLocal, client, create_dummy_epub


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

    response = client.get("/api/books/catalog?view=all")
    assert response.status_code == 200
    data = response.json()["items"]
    assert len(data) == 1
    assert data[0]["title"] == "Catalog Book"
    assert data[0]["author"] == "Catalog Author"
    assert data[0]["series"] == "Catalog Saga"
    assert data[0]["current_word_count"] == 321
    assert data[0]["cover_path"] == f"library/covers/{book.id}.jpg"
    assert "immutable_path" not in data[0]
    assert "current_path" not in data[0]
    assert "notes" not in data[0]
    assert "source_tags" not in data[0]


@pytest.mark.asyncio
async def test_book_catalog_includes_generated_and_human_audiobook_types(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Two Audio Editions",
                author="Catalog Author",
                immutable_path="two-audio-source.epub",
                current_path="two-audio.epub",
                source_type=models.SourceType.epub,
                audiobook_enabled=True,
            ),
        )
        session.add(
            models.ImportedAudiobook(
                book_id=book.id,
                name="Human edition",
                status="ready",
            )
        )
        await session.commit()

    response = client.get("/api/books/catalog?view=all")

    assert response.status_code == 200
    assert response.json()["items"][0]["audiobook_types"] == [
        "ai_generated",
        "human_narrated",
    ]


@pytest.mark.asyncio
async def test_book_catalog_sorts_audiobook_enabled_first(db_session):
    async with AsyncTestingSessionLocal() as session:
        enabled = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Audio Book",
                author="Catalog Author",
                immutable_path="audio-sort-enabled-source.epub",
                current_path="audio-sort-enabled.epub",
                source_type=models.SourceType.epub,
            ),
        )
        enabled.audiobook_enabled = True
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Text Book",
                author="Catalog Author",
                immutable_path="audio-sort-disabled-source.epub",
                current_path="audio-sort-disabled.epub",
                source_type=models.SourceType.epub,
            ),
        )
        await session.commit()

    response = client.get("/api/books/catalog?view=all&sort_by=audiobook_enabled&sort_order=desc")

    assert response.status_code == 200
    assert [book["title"] for book in response.json()["items"]] == ["Audio Book", "Text Book"]


@pytest.mark.asyncio
async def test_book_catalog_cursor_is_stable_when_new_books_are_added(db_session):
    async with AsyncTestingSessionLocal() as session:
        for index, title in enumerate(["Alpha", "Bravo", "Charlie", "Delta", "Echo"], start=1):
            await crud.create_book(
                session,
                schemas.BookCreate(
                    title=title,
                    author="Cursor Author",
                    immutable_path=f"cursor-{index}-source.epub",
                    current_path=f"cursor-{index}.epub",
                    source_type=models.SourceType.epub,
                ),
            )

    first = client.get("/api/books/catalog?view=standalone&limit=2")
    assert first.status_code == 200
    first_page = first.json()
    assert [book["title"] for book in first_page["items"]] == ["Alpha", "Bravo"]
    mismatched = client.get(
        "/api/books/catalog",
        params={
            "view": "standalone",
            "limit": 2,
            "sort_order": "desc",
            "cursor": first_page["next_cursor"],
        },
    )
    assert mismatched.status_code == 400

    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Between pages",
                author="Cursor Author",
                immutable_path="cursor-new-source.epub",
                current_path="cursor-new.epub",
                source_type=models.SourceType.epub,
            ),
        )

    titles = [book["title"] for book in first_page["items"]]
    cursor = first_page["next_cursor"]
    while cursor:
        response = client.get(
            "/api/books/catalog",
            params={"view": "standalone", "limit": 2, "cursor": cursor},
        )
        assert response.status_code == 200
        page = response.json()
        titles.extend(book["title"] for book in page["items"])
        cursor = page["next_cursor"]

    assert titles == ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    assert len(titles) == len(set(titles))


@pytest.mark.asyncio
async def test_book_catalog_genre_filter_is_exact_and_keeps_other_genre_facets(db_session):
    async with AsyncTestingSessionLocal() as session:
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Tagged Book",
                author="Facet Author",
                immutable_path="tagged-fantasy-source.epub",
                current_path="tagged-fantasy.epub",
                source_type=models.SourceType.epub,
                genre_tags=["Fantasy"],
            ),
        )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Fantasy",
                author="Facet Author",
                immutable_path="title-fantasy-source.epub",
                current_path="title-fantasy.epub",
                source_type=models.SourceType.epub,
                genre_tags=["Romance"],
            ),
        )

    response = client.get("/api/books/catalog?view=standalone&genre=Fantasy")
    assert response.status_code == 200
    page = response.json()
    assert [book["title"] for book in page["items"]] == ["Tagged Book"]
    assert page["facets"]["genres"] == [
        {"name": "Fantasy", "count": 1},
        {"name": "Romance", "count": 1},
    ]

    search = client.get("/api/books/catalog?view=standalone&q=Fantasy")
    assert {book["title"] for book in search.json()["items"]} == {"Fantasy", "Tagged Book"}


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
async def test_static_cover_files_reject_active_formats(db_session):
    library_path = Path("./library").resolve()
    cover_path = library_path / "covers" / "unsafe.svg"
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')

    try:
        response = client.get("/library/covers/unsafe.svg")
    finally:
        cover_path.unlink(missing_ok=True)

    assert response.status_code == 404


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
async def test_get_book_chapters_parses_off_the_event_loop(db_session, monkeypatch):
    from backend.app.routers import books as books_router

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Threaded Book",
                author="Test Author",
                immutable_path="library/immutable_threaded.epub",
                current_path="library/threaded.epub",
                source_type=models.SourceType.epub,
            ),
        )

    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    immutable_filepath = library_path / "immutable_threaded.epub"
    create_dummy_epub(immutable_filepath, "Threaded Book", "Test Author")
    ran_on_event_loop = []

    def get_chapters(epub_path):
        try:
            asyncio.get_running_loop()
            ran_on_event_loop.append(True)
        except RuntimeError:
            ran_on_event_loop.append(False)
        return []

    monkeypatch.setattr(books_router.epub_editor, "get_chapters", get_chapters)
    try:
        response = client.get(f"/api/books/{book.id}/chapters")
    finally:
        immutable_filepath.unlink()

    assert response.status_code == 200
    assert ran_on_event_loop == [False]


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

    # Verify it's hidden from the live library and available for recovery.
    response = client.get("/api/books")
    assert response.json() == []
    recycle_bin = client.get("/api/recycle-bin").json()
    assert [item["id"] for item in recycle_bin["books"]] == [book.id]
    assert recycle_bin["books"][0]["purge_after"] is not None

    # Deleting again is idempotent (returns 204)
    response = client.delete(f"/api/books/{book.id}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_recycle_bin_restore_returns_book_to_library(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Restore Me",
                author="Author",
                source_type=models.SourceType.epub,
            ),
        )

    assert client.delete(f"/api/books/{book.id}").status_code == 204
    assert client.get(f"/api/books/{book.id}").status_code == 404

    restore_response = client.post(f"/api/recycle-bin/{book.id}/restore")

    assert restore_response.status_code == 200
    assert restore_response.json()["deleted_at"] is None
    assert client.get(f"/api/books/{book.id}").json()["title"] == "Restore Me"
    assert client.get("/api/recycle-bin").json()["books"] == []


@pytest.mark.asyncio
async def test_book_revision_can_restore_metadata(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Original Title",
                author="Original Author",
                source_type=models.SourceType.epub,
            ),
        )

    update_response = client.put(
        f"/api/books/{book.id}",
        json={"title": "Changed Title", "author": "Changed Author"},
    )
    assert update_response.status_code == 200

    revisions = client.get(f"/api/books/{book.id}/revisions").json()
    assert len(revisions) == 1
    assert revisions[0]["snapshot"]["title"] == "Original Title"

    restore_response = client.post(f"/api/books/{book.id}/revisions/{revisions[0]['id']}/restore")

    assert restore_response.status_code == 200
    assert restore_response.json()["title"] == "Original Title"
    assert restore_response.json()["author"] == "Original Author"
    assert len(client.get(f"/api/books/{book.id}/revisions").json()) == 2


@pytest.mark.asyncio
async def test_delete_book_preserves_files_until_permanent_delete(db_session):
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
    assert author_dir.exists()
    assert immutable_path.exists()
    assert current_path.exists()

    response = client.delete(f"/api/recycle-bin/{book.id}")

    assert response.status_code == 204
    assert not author_dir.exists()


@pytest.mark.asyncio
async def test_delete_book_preserves_audiobook_until_permanent_delete(db_session, tmp_path, monkeypatch):
    from backend.app.routers import books as books_router

    library_path = (tmp_path / "library").resolve()
    monkeypatch.setattr(books_router, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(library_paths, "LIBRARY_PATH", library_path)
    library_path.mkdir(parents=True)

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Delete Audio",
                author="Narrator",
                source_type=models.SourceType.epub,
            ),
        )

    audiobook_dir = library_path / "audiobooks" / str(book.id)
    source_path = audiobook_dir / "imports" / "1" / "source" / "chapter.m4b"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"large-audio-placeholder")

    response = client.delete(f"/api/books/{book.id}")

    assert response.status_code == 204
    assert audiobook_dir.exists()

    response = client.delete(f"/api/recycle-bin/{book.id}")

    assert response.status_code == 204
    assert not audiobook_dir.exists()


@pytest.mark.asyncio
async def test_permanent_delete_keeps_files_when_database_delete_fails(db_session, tmp_path, monkeypatch):
    from backend.app.routers import books as books_router

    library_path = (tmp_path / "library").resolve()
    monkeypatch.setattr(books_router, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(library_paths, "LIBRARY_PATH", library_path)
    library_path.mkdir(parents=True)

    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(title="Keep Files", author="Writer", source_type=models.SourceType.epub),
        )

    audio_path = library_path / "audiobooks" / str(book.id) / "chapter.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"audio")

    async def failing_delete(_db, book):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(books_router.crud, "delete_book", failing_delete)
    with pytest.raises(RuntimeError, match="database unavailable"):
        client.delete(f"/api/books/{book.id}?permanent=true")

    assert audio_path.exists()


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

    audiobook_path = library_path / "audiobooks" / str(alpha.id) / "imports" / "1" / "source" / "chapter.m4b"
    audiobook_path.parent.mkdir(parents=True)
    audiobook_path.write_bytes(b"audiobook")

    preview_response = client.post("/api/books/remove-all?dry_run=true")

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["dry_run"] is True
    assert preview["book_count"] == 2
    assert preview["file_count"] == 6
    assert preview["log_count"] == 3
    assert "library/Author One/Alpha.epub" in preview["paths"]
    assert str(audiobook_path.relative_to(library_path.parent)) in preview["paths"]
    assert any(book["title"] == "Alpha" and book["log_entries"] == 2 for book in preview["books"])

    delete_response = client.post("/api/books/remove-all?dry_run=false")

    assert delete_response.status_code == 200
    assert delete_response.json()["recoverable"] is True
    assert client.get("/api/books").json() == []
    recycled_books = client.get("/api/recycle-bin").json()["books"]
    assert len(recycled_books) == 2
    assert author_one_dir.exists()
    assert author_two_dir.exists()
    assert cover_path.exists()
    assert audiobook_path.exists()

    for recycled_book in recycled_books:
        assert client.delete(f"/api/recycle-bin/{recycled_book['id']}").status_code == 204
    assert not author_one_dir.exists()
    assert not author_two_dir.exists()
    assert not cover_path.exists()
    assert not audiobook_path.exists()


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
async def test_book_update_history_uses_growth_logs(db_session):
    async with AsyncTestingSessionLocal() as session:
        book = await crud.create_book(
            session,
            schemas.BookCreate(
                title="Growing Story",
                author="Author",
                immutable_path="growing_i",
                current_path="growing_c",
                source_type=models.SourceType.web,
                source_url="https://example.com/growing",
            ),
        )

        initial = await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book.id,
                entry_type="added",
                new_chapter_count=100,
                words_added=100000,
            ),
        )
        catch_up_update = await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book.id,
                entry_type="updated",
                previous_chapter_count=100,
                new_chapter_count=115,
                words_added=50000,
            ),
        )
        first_update = await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book.id,
                entry_type="updated",
                previous_chapter_count=115,
                new_chapter_count=117,
                words_added=5000,
            ),
        )
        checked = await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book.id,
                entry_type="checked",
                previous_chapter_count=117,
                new_chapter_count=117,
                words_added=0,
            ),
        )
        second_update = await crud.create_book_log(
            session,
            schemas.BookLogCreate(
                book_id=book.id,
                entry_type="updated",
                previous_chapter_count=117,
                new_chapter_count=120,
                words_added=9000,
            ),
        )

        initial.timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        catch_up_update.timestamp = datetime(2026, 1, 8, tzinfo=timezone.utc)
        first_update.timestamp = datetime(2026, 1, 15, tzinfo=timezone.utc)
        checked.timestamp = datetime(2026, 1, 17, tzinfo=timezone.utc)
        second_update.timestamp = datetime(2026, 1, 22, tzinfo=timezone.utc)
        await session.commit()

    response = client.get(f"/api/books/{book.id}/update-history")
    assert response.status_code == 200
    payload = response.json()

    assert [entry["words_added"] for entry in payload["history"]] == [100000, 50000, 5000, 9000]
    assert [entry["chapters_added"] for entry in payload["history"]] == [100, 15, 2, 3]
    assert payload["history"][0]["is_initial_sync"] is True
    assert payload["history"][0]["included_in_stats"] is False
    assert payload["history"][1]["is_catch_up_sync"] is True
    assert payload["history"][1]["included_in_stats"] is False
    assert payload["history"][2]["average_words_per_chapter"] == 2500
    assert [entry["included_in_stats"] for entry in payload["history"][2:]] == [True, True]
    assert payload["summary"]["total_update_events"] == 2
    assert payload["summary"]["total_chapters_added"] == 5
    assert payload["summary"]["total_words_added"] == 14000
    assert payload["summary"]["average_days_between_updates"] == 7
    assert payload["summary"]["predicted_next_update_at"].startswith("2026-01-29")
