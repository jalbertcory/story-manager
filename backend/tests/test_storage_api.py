"""Storage cleanup and library validation routes."""

import os
import time

import pytest

from backend.app import crud, models, schemas
from api_harness import AsyncTestingSessionLocal, client, create_dummy_epub


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


@pytest.mark.asyncio
async def test_storage_cleanup_removes_failed_web_import_placeholders_and_orphans(db_session, tmp_path, monkeypatch):
    from backend.app.routers import storage as storage_router

    library_path = (tmp_path / "library").resolve()
    monkeypatch.setattr(storage_router, "LIBRARY_PATH", library_path)
    library_path.mkdir(parents=True, exist_ok=True)
    orphan_path = library_path / "orphan.epub"
    orphan_path.write_bytes(b"orphan")
    old_mtime = time.time() - 2 * storage_router.RECENT_FILE_GRACE_SECONDS
    os.utime(orphan_path, (old_mtime, old_mtime))

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

    audiobook_path = library_path / "audiobooks" / str(keep_book.id) / "imports" / "1" / "source" / "chapter.m4b"
    audiobook_path.parent.mkdir(parents=True)
    audiobook_path.write_bytes(b"active-audiobook")

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
    assert audiobook_path.read_bytes() == b"active-audiobook"

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
