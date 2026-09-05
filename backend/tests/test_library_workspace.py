import pytest

from backend.app import models
from backend.app.crud.series import merge_series, rename_series
from backend.app.services.catalog import build_book_catalog_page
from backend.app.services.library import library_groups


@pytest.mark.asyncio
async def test_universe_membership_groups_filters_and_rename(db, app_client):
    books = [
        models.Book(title="First", author="Writer", series="One", series_index=2, source_type=models.SourceType.epub),
        models.Book(title="Second", author="Writer", series="Two", source_type=models.SourceType.epub),
        models.Book(title="Standalone", author="Writer", source_type=models.SourceType.web),
        models.Book(title="Unassigned", author="Other", source_type=models.SourceType.epub),
    ]
    db.add_all(books)
    await db.commit()
    response = app_client.put("/api/library/universe-membership", json={"series": "One", "name": "Cosmere"})
    assert response.status_code == 200, response.text
    uid = response.json()["universe_id"]
    assert (
        app_client.put("/api/library/universe-membership", json={"series": "Two", "name": " cosmere "}).json()["universe_id"]
        == uid
    )
    assert (
        app_client.put("/api/library/universe-membership", json={"book_id": books[2].id, "name": "Cosmere"}).status_code == 200
    )
    assert (
        app_client.put("/api/library/universe-membership", json={"book_id": books[0].id, "name": "Other"}).status_code == 409
    )
    assert app_client.put("/api/library/universe-membership", json={"series": "Missing", "name": "Phantom"}).status_code == 404
    assert len(app_client.get("/api/library/universes").json()) == 1

    grouped = await library_groups(db, group_by="universe", q="", universe=None, source=None)
    assert [(g["name"], g["book_count"]) for g in grouped] == [("Cosmere", 3), (None, 1)]
    page = await build_book_catalog_page(db, view="all", universe=uid, limit=1)
    assert page.total_count == 3 and page.next_cursor
    ids = {page.items[0].id}
    while page.next_cursor:
        page = await build_book_catalog_page(db, view="all", universe=uid, limit=1, cursor=page.next_cursor)
        ids.update(item.id for item in page.items)
    assert ids == {b.id for b in books[:3]}
    assert (await build_book_catalog_page(db, view="all", q="cosmere")).total_count == 3
    children = await library_groups(db, group_by="series", q="", universe=uid, source=None)
    assert [(g["name"], g["book_count"]) for g in children] == [("One", 1), ("Two", 1), (None, 1)]
    assert (await build_book_catalog_page(db, view="all", universe=uid, source="web")).items[0].id == books[2].id
    assert (await build_book_catalog_page(db, view="all", series="")).total_count == 2
    await rename_series(db, "One", "Renamed")
    assert (await build_book_catalog_page(db, view="all", series="Renamed")).items[0].universe_name == "Cosmere"
    await merge_series(db, "Renamed", "Two")
    assert (await build_book_catalog_page(db, view="all", universe=uid)).total_count == 3
    assert books[0].series_index == 2


@pytest.mark.asyncio
async def test_audio_availability_requires_playable_media(db):
    enabled = models.Book(title="Enabled only", author="A", source_type=models.SourceType.epub, audiobook_enabled=True)
    playable = models.Book(title="Playable", author="A", source_type=models.SourceType.epub, audiobook_enabled=True)
    db.add_all([enabled, playable])
    await db.flush()
    db.add(
        models.AudiobookChapter(
            book_id=playable.id,
            chapter_number=1,
            content_file_name="chapter.xhtml",
            audio_file_path="chapter.mp3",
            needs_reassembly=False,
        )
    )
    await db.commit()
    page = await build_book_catalog_page(db, view="all")
    assert {b.title: b.audio_playable for b in page.items} == {"Enabled only": False, "Playable": True}


@pytest.mark.asyncio
async def test_different_universes_cannot_be_silently_merged(db, app_client):
    db.add_all([models.Book(title=n, author="A", series=n, source_type=models.SourceType.epub) for n in ["A", "B"]])
    await db.commit()
    for name in ["A", "B"]:
        assert app_client.put("/api/library/universe-membership", json={"series": name, "name": name}).status_code == 200
    response = app_client.post("/api/series/merge", json={"source": "A", "target": "B"})
    assert response.status_code == 409
    assert len(app_client.get("/api/series").json()) == 2


@pytest.mark.asyncio
async def test_latest_web_check_does_not_use_metadata_timestamp(db, app_client):
    book = models.Book(title="Web", author="A", source_type=models.SourceType.web)
    db.add(book)
    await db.flush()
    db.add_all([models.BookLog(book_id=book.id, entry_type="error"), models.BookLog(book_id=book.id, entry_type="checked")])
    await db.commit()
    checks = app_client.get("/api/library/web-checks").json()
    assert len(checks) == 1
    assert checks[0]["entry_type"] == "checked"


@pytest.mark.asyncio
async def test_series_case_variants_stay_together_and_membership_can_be_removed(db, app_client):
    books = [
        models.Book(title=n, author="A", series=n, source_type=models.SourceType.epub, cover_path=f"{n}.jpg")
        for n in ["Saga", "saga"]
    ]
    db.add_all(books)
    await db.commit()
    assert app_client.put("/api/library/universe-membership", json={"series": "Saga", "name": "Shared"}).status_code == 200
    groups = await library_groups(db, group_by="series", q="", universe=None, source=None)
    assert len(groups) == 1 and groups[0]["book_count"] == 2
    assert set(groups[0]["cover_ids"]) == {b.id for b in books}
    assert (await build_book_catalog_page(db, view="all", series="SAGA")).total_count == 2
    assert app_client.put("/api/library/universe-membership", json={"series": "saga", "name": None}).status_code == 200
    assert (await build_book_catalog_page(db, view="all", universe=0)).total_count == 2


@pytest.mark.asyncio
async def test_imported_audio_needs_a_playable_edition_with_tracks(db):
    book = models.Book(title="Narrated", author="A", source_type=models.SourceType.epub, audiobook_enabled=False)
    db.add(book)
    await db.flush()
    edition = models.ImportedAudiobook(book_id=book.id, name="Narration", status="ready")
    db.add(edition)
    await db.commit()
    assert not (await build_book_catalog_page(db, view="all")).items[0].audio_playable
    db.add(
        models.ImportedAudiobookTrack(
            imported_audiobook_id=edition.id,
            sequence_order=1,
            title="Opening",
            audio_file_path="chapter.mp3",
            media_type="audio/mpeg",
            source_end_ms=1000,
            duration_ms=1000,
        )
    )
    await db.commit()
    assert (await build_book_catalog_page(db, view="all")).items[0].audio_playable
    edition.status = "error"
    await db.commit()
    assert not (await build_book_catalog_page(db, view="all")).items[0].audio_playable


@pytest.mark.asyncio
async def test_group_pages_preserve_filters_counts_covers_and_snapshot(db, app_client):
    for series in ["A", "B", "C", None]:
        db.add(
            models.Book(
                title=series or "Solo",
                author="Same",
                series=series,
                source_type=models.SourceType.web,
                refresh_status="error",
                genre_tags=["Fantasy"],
                cover_path="cover.jpg",
            )
        )
    db.add(models.Book(title="Excluded", author="Same", series="A", source_type=models.SourceType.epub))
    await db.commit()
    params = dict(limit=2, source="web", review="refresh-error", genre="Fantasy", sort_by="author")
    response = app_client.get("/api/library/groups", params=params)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["total_count"] == 4
    assert [g["name"] for g in first["items"]] == ["A", "B"]
    assert all(g["book_count"] == 1 and len(g["cover_ids"]) == 1 for g in first["items"])
    assert first["facets"]["genres"] == [{"name": "Fantasy", "count": 4}]
    db.add(
        models.Book(
            title="Later",
            author="Same",
            series="D",
            source_type=models.SourceType.web,
            refresh_status="error",
            genre_tags=["Fantasy"],
        )
    )
    await db.commit()
    second = app_client.get("/api/library/groups", params={**params, "cursor": first["next_cursor"]}).json()
    assert [g["name"] for g in second["items"]] == ["C", None]
    assert second["next_cursor"] is None and second["total_count"] == 4
    assert (
        app_client.get("/api/library/groups", params={**params, "genre": "Other", "cursor": first["next_cursor"]}).status_code
        == 400
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("sort_order", ["asc", "desc"])
async def test_series_order_pages_handle_ties_and_unindexed_books(db, sort_order):
    for i, index in enumerate([2, 1, None, 1, -1, 1.5]):
        db.add(
            models.Book(title=f"Book {i}", author="A", series="Saga", series_index=index, source_type=models.SourceType.epub)
        )
    await db.commit()
    kwargs = dict(view="all", series="Saga", sort_by="series_index", sort_order=sort_order, limit=2)
    page = await build_book_catalog_page(db, **kwargs)
    items = list(page.items)
    while page.next_cursor:
        page = await build_book_catalog_page(db, **kwargs, cursor=page.next_cursor)
        items.extend(page.items)
    assert len({item.id for item in items}) == 6
    expected = [-1, 1, 1, 1.5, 2, None] if sort_order == "asc" else [None, 2, 1.5, 1, 1, -1]
    assert [item.series_index for item in items] == expected


@pytest.mark.asyncio
async def test_playable_filter_matches_group_and_book_results(db, app_client):
    books = [
        models.Book(title=str(i), author="A", series="Saga", source_type=models.SourceType.epub, audiobook_enabled=True)
        for i in range(2)
    ]
    db.add_all(books)
    await db.flush()
    db.add(
        models.AudiobookChapter(
            book_id=books[0].id,
            chapter_number=1,
            content_file_name="1.xhtml",
            audio_file_path="audio.mp3",
            needs_reassembly=False,
        )
    )
    await db.commit()
    for state, index in [("playable", 0), ("unplayable", 1)]:
        page = await build_book_catalog_page(db, view="all", audiobook=state)
        assert [b.id for b in page.items] == [books[index].id]
        response = app_client.get("/api/library/groups", params={"audiobook": state, "limit": 30})
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["book_count"] == 1
