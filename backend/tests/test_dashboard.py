"""Tests for the aggregated Needs Attention dashboard."""

from pathlib import Path

import pytest

from backend.app import crud, models, schemas
from backend.app.routers import dashboard as dashboard_router


def _book_paths(library_path: Path, slug: str) -> tuple[str, str]:
    immutable = library_path / f"immutable_{slug}.epub"
    current = library_path / f"{slug}.epub"
    immutable.write_bytes(b"original")
    current.write_bytes(b"current")
    return (
        str(immutable.relative_to(library_path.parent)),
        str(current.relative_to(library_path.parent)),
    )


def _add_cover(library_path: Path, book: models.Book) -> None:
    cover = library_path / "covers" / f"{book.id}.jpg"
    cover.parent.mkdir(parents=True, exist_ok=True)
    cover.write_bytes(b"cover")
    book.cover_path = str(cover.relative_to(library_path.parent))


@pytest.mark.asyncio
async def test_attention_dashboard_aggregates_actionable_categories(
    app_client,
    sqlite_sessionmaker,
    tmp_path,
    monkeypatch,
):
    library_path = tmp_path / "library"
    library_path.mkdir()
    monkeypatch.setattr(dashboard_router, "LIBRARY_PATH", library_path)

    async with sqlite_sessionmaker() as db:
        refresh_paths = _book_paths(library_path, "refresh")
        refresh_book = await crud.create_book(
            db,
            schemas.BookCreate(
                title="Refresh Me",
                author="Web Author",
                source_url="https://example.com/refresh",
                source_type=models.SourceType.web,
                immutable_path=refresh_paths[0],
                current_path=refresh_paths[1],
                refresh_status="error",
            ),
        )
        _add_cover(library_path, refresh_book)

        stale_paths = _book_paths(library_path, "stale")
        stale_book = await crud.create_book(
            db,
            schemas.BookCreate(
                title="Stale Audio",
                author="Narrated Author",
                source_type=models.SourceType.epub,
                immutable_path=stale_paths[0],
                current_path=stale_paths[1],
                audiobook_enabled=True,
            ),
        )
        stale_book.audiobook_publication_state = "stale"
        _add_cover(library_path, stale_book)
        db.add(
            models.ImportedAudiobook(
                book_id=stale_book.id,
                name="Human edition",
                source_type="upload",
                status="stale",
            )
        )

        broken_book = await crud.create_book(
            db,
            schemas.BookCreate(
                title="Broken Paths",
                author="Missing Author",
                source_type=models.SourceType.epub,
                immutable_path="library/missing-original.epub",
                current_path="library/missing-current.epub",
            ),
        )
        _add_cover(library_path, broken_book)

        cover_paths = _book_paths(library_path, "coverless")
        await crud.create_book(
            db,
            schemas.BookCreate(
                title="Coverless",
                author="Cover Author",
                source_type=models.SourceType.epub,
                immutable_path=cover_paths[0],
                current_path=cover_paths[1],
            ),
        )

        db.add(
            models.ProcessingJob(
                job_type="refresh_book",
                status="error",
                book_id=refresh_book.id,
                payload={},
                progress_current=0,
                progress_total=1,
                attempt_count=1,
                cancel_requested=False,
                error="Source unavailable",
            )
        )
        db.add(
            models.MetadataProposal(
                book_id=refresh_book.id,
                status="open",
                proposed_genre_tags=["Fantasy"],
                possible_missing_series_books=[],
                note="Review the proposed genre.",
            )
        )
        await db.commit()

    response = app_client.get("/api/dashboard/attention?limit=5")

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 7
    assert data["failed_jobs"]["count"] == 1
    assert data["failed_jobs"]["items"][0]["book_title"] == "Refresh Me"
    assert data["failed_refreshes"]["count"] == 1
    assert data["stale_audiobooks"]["count"] == 1
    assert "Generated audiobook" in data["stale_audiobooks"]["items"][0]["detail"]
    assert "Human edition" in data["stale_audiobooks"]["items"][0]["detail"]
    assert data["metadata_proposals"]["count"] == 1
    assert data["broken_files"]["count"] == 2
    assert data["missing_covers"]["count"] == 1
    assert data["missing_covers"]["items"][0]["title"] == "Coverless"


@pytest.mark.asyncio
async def test_attention_dashboard_has_clear_healthy_state(app_client, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    monkeypatch.setattr(dashboard_router, "LIBRARY_PATH", library_path)

    response = app_client.get("/api/dashboard/attention")

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 0
    assert all(category["count"] == 0 for key, category in data.items() if key != "total_count")
