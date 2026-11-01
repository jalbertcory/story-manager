"""Series routes, series genre metadata and title-based series detection."""

import pytest

from backend.app import crud, models, schemas
from backend.app.services.series import SeriesBook, detect_series_from_books, detect_series_from_titles
from api_harness import AsyncTestingSessionLocal, client


@pytest.mark.asyncio
async def test_book_catalog_series_pages_keep_groups_complete_and_report_facets(db_session):
    async with AsyncTestingSessionLocal() as session:
        for series in ["Alpha Saga", "Beta Saga", "Gamma Saga"]:
            for index in range(2):
                await crud.create_book(
                    session,
                    schemas.BookCreate(
                        title=f"{series} {index + 1}",
                        author="Series Author",
                        series=series,
                        immutable_path=f"{series}-{index}-source.epub",
                        current_path=f"{series}-{index}.epub",
                        source_type=models.SourceType.epub,
                        genre_tags=["Fantasy"],
                    ),
                )
        await crud.create_book(
            session,
            schemas.BookCreate(
                title="Standalone",
                author="Solo Author",
                immutable_path="standalone-facet-source.epub",
                current_path="standalone-facet.epub",
                source_type=models.SourceType.epub,
            ),
        )

    response = client.get("/api/books/catalog?view=series&limit=2")
    assert response.status_code == 200
    page = response.json()
    assert page["total_count"] == 3
    assert {book["series"] for book in page["items"]} == {"Alpha Saga", "Beta Saga"}
    assert len(page["items"]) == 4
    assert page["facets"]["series"] == 3
    assert page["facets"]["standalone"] == 1
    assert page["facets"]["genres"] == [{"name": "Fantasy", "count": 6}]
    assert page["next_cursor"]

    second = client.get(
        "/api/books/catalog",
        params={"view": "series", "limit": 2, "cursor": page["next_cursor"]},
    )
    assert second.status_code == 200
    assert {book["series"] for book in second.json()["items"]} == {"Gamma Saga"}
    assert second.json()["next_cursor"] is None


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
    data = response.json()["items"]
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
    catalog_data = catalog_response.json()["items"]
    assert catalog_data[0]["series_user_genre_tags"] == ["Fantasy", "Progression Fantasy"]
    assert catalog_data[0]["effective_genre_tags"] == ["Fantasy", "Progression Fantasy"]


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

    indexed_books = {(book["author"], book["title"]): book["series_index"] for book in response.json()}
    assert indexed_books[("Will Wight", "Soulsmith (Cradle Book 2)")] == 2.0
    assert indexed_books[("William D. Arand", "Cultivating Chaos 3")] == 3.0


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
    data = response.json()["items"]
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
    data = response.json()["items"]
    book = [b for b in data if b["series"] == "Explicit Series"][0]
    assert book["effective_series_genre_tags"] == ["Sci-Fi"]
