"""Series gap detection, release discovery and their attention cards."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from backend.app import crud, models, schemas
from backend.app.routers import dashboard as dashboard_router
from backend.app.services import series_tracking

TODAY = date(2026, 11, 13)


async def _book(db, title, series=None, index=None, author="Ann Author", source_type=models.SourceType.epub):
    return await crud.create_book(
        db,
        schemas.BookCreate(title=title, author=author, source_type=source_type, series=series, series_index=index),
    )


def _volume(title, published, *, subtitle=None, authors=("Ann Author",), link="https://books.example/v"):
    return {
        "id": title,
        "volumeInfo": {
            "title": title,
            "subtitle": subtitle,
            "authors": list(authors),
            "publishedDate": published,
            "infoLink": link,
        },
    }


@pytest.mark.parametrize(
    "owned,expected",
    [
        ({1, 2, 4}, [3]),
        ({3}, [1, 2]),
        ({1, 2, 3}, []),
        (set(), []),
        ({1, 40}, []),  # not sequential numbering; flagging 38 volumes would be noise
    ],
)
def test_missing_indexes(owned, expected):
    assert series_tracking.missing_indexes(owned) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2027-03-09", (date(2027, 3, 9), date(2027, 3, 9))),
        ("2027-02", (date(2027, 2, 1), date(2027, 2, 28))),
        ("2027", (date(2027, 1, 1), date(2027, 12, 31))),
        ("soon", None),
        ("2027-13-01", None),
        (None, None),
    ],
)
def test_parse_published_date(value, expected):
    assert series_tracking.parse_published_date(value) == expected


@pytest.mark.asyncio
async def test_gaps_ignore_deleted_books_novellas_and_case_differences(db):
    await _book(db, "One", "The Saga", 1)
    await _book(db, "Two", "the saga", 2)
    await _book(db, "Two and a half", "The Saga", 2.5)
    await _book(db, "Four", "The Saga", 4)
    deleted = await _book(db, "Three", "The Saga", 3)
    deleted.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    await _book(db, "Complete 1", "Whole", 1)
    await _book(db, "Complete 2", "Whole", 2)
    await _book(db, "Standalone")

    gaps = await series_tracking.compute_series_gaps(db)
    assert [(gap.series_name, gap.missing_indexes, gap.owned_count) for gap in gaps] == [("The Saga", [3], 4)]


@pytest.mark.asyncio
async def test_dismissed_gap_stays_hidden_until_a_new_gap_appears(db):
    await _book(db, "One", "Saga", 1)
    await _book(db, "Three", "Saga", 3)
    assert await series_tracking.dismiss_series_gaps(db, "saga") == 1
    assert await series_tracking.compute_series_gaps(db) == []

    await _book(db, "Five", "Saga", 5)
    gaps = await series_tracking.compute_series_gaps(db)
    assert [gap.missing_indexes for gap in gaps] == [[4]]


@pytest.mark.asyncio
async def test_gap_sync_reports_each_gap_once_and_forgets_filled_gaps(db):
    await _book(db, "One", "Saga", 1)
    await _book(db, "Three", "Saga", 3)

    first = await series_tracking.sync_series_gaps(db)
    assert [(gap.series_name, gap.missing_indexes) for gap in first] == [("Saga", [2])]
    assert await series_tracking.sync_series_gaps(db) == []

    await _book(db, "Two", "Saga", 2)
    assert await series_tracking.sync_series_gaps(db) == []
    assert (await db.execute(select(models.SeriesFinding))).first() is None


def test_release_selection_keeps_only_unowned_recent_volumes_of_the_series():
    series = series_tracking.TrackedSeries(
        key="the saga",
        name="The Saga",
        author="Ann Author",
        titles=["First Light", "Second Dawn"],
        book_ids=[1, 2],
        whole_indexes={1, 2},
        has_published_book=True,
    )
    volumes = [
        _volume("Third Dusk", "2027-03-09", subtitle="Book Three of the Saga"),
        _volume("Third Dusk", "2027-06-01", subtitle="The Saga, Book 3 (Deluxe)"),  # later edition
        _volume("First Light", "2027-01-01", subtitle="The Saga anniversary edition"),  # owned
        _volume("Old Tale", "2019-05-01", subtitle="A Saga story"),  # back catalogue
        _volume("Unrelated Novel", "2027-04-01"),  # same author, different series
        _volume("Saga Companion", "2027-04-01", subtitle="The Saga", authors=("Someone Else",)),
        _volume("No Date", None, subtitle="The Saga"),
    ]
    candidates = series_tracking.select_release_candidates(series, volumes, today=TODAY)
    assert [(item.title, item.release_date, item.series_index) for item in candidates] == [
        ("Third Dusk: Book Three of the Saga", date(2027, 3, 9), 3.0)
    ]


@pytest.mark.asyncio
async def test_release_sync_records_new_releases_once_and_drops_owned_ones(db, mocker):
    mocker.patch.object(series_tracking, "google_books_enabled", return_value=True)
    fetch = mocker.patch.object(
        series_tracking,
        "fetch_release_volumes",
        return_value=[_volume("Third Dusk", "2027-03-09", subtitle="Book Three of the Saga")],
    )
    await _book(db, "First Light", "The Saga", 1)
    await _book(db, "Web Serial", "Web Only", 1, source_type=models.SourceType.web)

    new, failures = await series_tracking.sync_series_releases(db, today=TODAY)
    assert failures == 0
    assert [release.title for release in new] == ["Third Dusk: Book Three of the Saga"]
    assert fetch.call_count == 1  # web-only series are not looked up
    stored = (await db.execute(select(models.SeriesFinding))).scalars().one()
    assert (stored.kind, stored.status, stored.release_date) == ("release", "open", date(2027, 3, 9))

    assert await series_tracking.dismiss_series_release(db, stored.id) is True
    again, _ = await series_tracking.sync_series_releases(db, today=TODAY)
    assert again == []
    assert (await db.execute(select(models.SeriesFinding.status))).scalar_one() == "dismissed"

    await _book(db, "Third Dusk", "The Saga", 3)
    await series_tracking.sync_series_releases(db, today=TODAY)
    assert (await db.execute(select(models.SeriesFinding))).first() is None


@pytest.mark.asyncio
async def test_release_is_dropped_when_that_volume_is_owned_under_another_title(db, mocker):
    mocker.patch.object(series_tracking, "google_books_enabled", return_value=True)
    mocker.patch.object(series_tracking, "fetch_release_volumes", return_value=[])
    await _book(db, "First Light", "The Saga", 1)
    db.add(
        models.SeriesFinding(
            kind="release",
            finding_key="release:the saga:third dusk",
            series_name="The Saga",
            title="Third Dusk: Book Three of the Saga",
            series_index=3,
            source="google_books",
        )
    )
    await db.commit()

    await series_tracking.sync_series_releases(db, today=TODAY)
    assert (await db.execute(select(models.SeriesFinding))).first() is not None

    await _book(db, "Der dritte Abend", "The Saga", 3)
    await series_tracking.sync_series_releases(db, today=TODAY)
    assert (await db.execute(select(models.SeriesFinding))).first() is None


@pytest.mark.asyncio
async def test_release_sync_does_nothing_when_google_books_is_disabled(db, mocker):
    fetch = mocker.patch.object(series_tracking, "fetch_release_volumes")
    await _book(db, "First Light", "The Saga", 1)
    assert await series_tracking.sync_series_releases(db, today=TODAY) == ([], 0)
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_series_check_announces_new_findings(db, sqlite_sessionmaker, mocker):
    mocker.patch.object(series_tracking, "SessionLocal", sqlite_sessionmaker)
    emit = mocker.patch.object(series_tracking, "emit_notification", mocker.AsyncMock(return_value=1))
    await _book(db, "One", "Saga", 1)
    await _book(db, "Three", "Saga", 3)

    detail = await series_tracking.run_series_check()
    assert "1 new gap(s) and 0 new release(s)" in detail
    assert "Google Books is disabled" in detail
    emit.assert_awaited_once_with("series_update", "Series updates", "Missing from Saga: #2")

    emit.reset_mock()
    await series_tracking.run_series_check()
    emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_attention_dashboard_lists_gaps_and_releases_and_supports_dismissal(
    app_client, sqlite_sessionmaker, tmp_path, monkeypatch
):
    library_path = tmp_path / "library"
    library_path.mkdir()
    monkeypatch.setattr(dashboard_router, "LIBRARY_PATH", library_path)
    async with sqlite_sessionmaker() as db:
        await _book(db, "One", "Saga", 1)
        await _book(db, "Three", "Saga", 3)
        db.add(
            models.SeriesFinding(
                kind="release",
                finding_key="release:saga:four",
                series_name="Saga",
                author="Ann Author",
                title="Four",
                published_date="2999-01-01",
                release_date=date(2999, 1, 1),
                source="google_books",
            )
        )
        await db.commit()

    body = app_client.get("/api/dashboard/attention").json()
    assert body["series_gaps"]["count"] == 1
    assert body["series_gaps"]["items"][0]["missing_indexes"] == [2]
    assert body["series_releases"]["count"] == 1
    release = body["series_releases"]["items"][0]
    assert (release["title"], release["upcoming"], release["release_date"]) == ("Four", True, "2999-01-01")

    assert app_client.post("/api/series-tracking/gaps/dismiss", json={"series_name": "Saga"}).status_code == 204
    assert app_client.post(f"/api/series-tracking/releases/{release['id']}/dismiss").status_code == 204
    assert app_client.post("/api/series-tracking/releases/99999/dismiss").status_code == 404

    body = app_client.get("/api/dashboard/attention").json()
    assert body["series_gaps"]["count"] == 0
    assert body["series_releases"]["count"] == 0
