"""Attach purchased EPUBs to audio-only library entries without duplicating books."""

from datetime import datetime, timezone
from io import BytesIO
import zipfile
from unittest.mock import AsyncMock

from ebooklib import epub
import pytest
from sqlalchemy import func, select

from backend.app import config, models
from backend.app.routers import upload
from backend.app.services import audiobook_import, audiobook_ingestion, audiobook_publication, library_paths
from backend.app.services.book_matching import match_epub_to_audio_book


def ebook(title="Artemis Fowl", author="Eoin Colfer", identifier="test-book", number=None):
    book = epub.EpubBook()
    book.set_identifier(identifier)
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    if number is not None:
        book.add_metadata("calibre", "series_index", str(number))
    chapter = epub.EpubHtml(title="Chapter 1", file_name="chapter.xhtml", lang="en")
    chapter.content = "<h1>Chapter 1</h1><p>Artemis found the book. This is the first chapter.</p>"
    book.add_item(chapter)
    book.toc = (epub.Link("chapter.xhtml", "Chapter 1", "chapter-1"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    return book


def epub_bytes(book):
    output = BytesIO()
    epub.write_epub(output, book)
    return output.getvalue()


@pytest.fixture
def library(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    for module in (upload, library_paths, config, audiobook_import, audiobook_ingestion, audiobook_publication):
        monkeypatch.setattr(module, "LIBRARY_PATH", library)
    monkeypatch.setattr(upload, "queue_metadata_sync_job", AsyncMock())
    return library


async def audio_book(db, title="Artemis Fowl Movie Tie-In Edition: Artemis Fowl, Book 1 (Unabridged)", **kwargs):
    book = models.Book(
        title=title, author=kwargs.pop("author", "Eoin Colfer"), source_type=models.SourceType.audiobook, **kwargs
    )
    db.add(book)
    await db.flush()
    edition = models.ImportedAudiobook(
        book_id=book.id,
        name="Libation",
        status="ready",
        asin="B002V8MYYE",
        matched_content_version=book.content_version,
    )
    db.add(edition)
    await db.flush()
    track = models.ImportedAudiobookTrack(
        imported_audiobook_id=edition.id,
        title="Chapter 1",
        sequence_order=1,
        audio_file_path="library/chapter.mp3",
        source_audio_file_path="library/original.mp3",
        media_type="audio/mpeg",
        duration_ms=10000,
        source_end_ms=10000,
    )
    db.add(track)
    await db.commit()
    return book, edition, track


@pytest.mark.asyncio
async def test_bulk_epub_attaches_preserves_audio_and_queues_real_rematch(db, app_client, library):
    book, edition, track = await audio_book(
        db,
        series="Artemis Fowl",
        series_index=1,
        notes="Want the EPUB",
        cover_path="library/cover.jpg",
        metadata_remote_ids={"asin": "B002V8MYYE"},
        user_genre_tags=["Favorites"],
    )
    (library / "cover.jpg").write_bytes(b"cover")
    (library / "chapter.mp3").write_bytes(b"recorded audio")
    (library / "original.mp3").write_bytes(b"original audio")
    old_version = book.content_version
    payload = epub_bytes(ebook())
    preview = app_client.post("/api/imports/preview", files={"files": ("book.epub", payload)})
    assert preview.status_code == 200, preview.text
    assert preview.json()["items"][0]["status"] == "ready"
    assert f"book {book.id}" in preview.json()["items"][0]["detail"]
    await db.refresh(book)
    assert book.current_path is None

    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("bought/book.epub", payload)
        out.writestr("another-copy.epub", payload)
        out.writestr("new-book.epub", epub_bytes(ebook("A New Story", "Another Writer")))
    response = app_client.post(
        "/api/books/upload_epubs", files={"files": ("purchases.zip", archive.getvalue(), "application/zip")}
    )
    assert response.status_code == 200, response.text
    results = response.json()
    assert [item["status"] for item in results] == ["success", "skipped", "success"], results
    assert results[0]["book"]["id"] == book.id
    assert await db.scalar(select(func.count(models.Book.id))) == 2
    await db.refresh(book)
    await db.refresh(edition)
    await db.refresh(track)
    assert book.source_type == models.SourceType.epub
    assert book.content_version > old_version
    assert book.current_word_count > 0
    assert (library.parent / book.current_path).is_file()
    assert book.notes == "Want the EPUB" and book.user_genre_tags == ["Favorites"]
    assert book.metadata_remote_ids["asin"] == "B002V8MYYE"
    assert book.cover_path == "library/cover.jpg" and book.series_index == 1
    assert track.source_audio_file_path == "library/original.mp3"
    assert (library / "original.mp3").read_bytes() == b"original audio"
    assert edition.status == "stale"
    jobs = list(
        (
            await db.execute(select(models.ProcessingJob).where(models.ProcessingJob.job_type == "rematch_imported_audiobook"))
        ).scalars()
    )
    assert len(jobs) == 1 and jobs[0].target_id == edition.id
    assert jobs[0].target_content_version == book.content_version

    # Run the same rematch worker used in production against the actual EPUB.
    assert await audiobook_import.rematch_imported_audiobook(edition.id, db) == 1
    await db.refresh(track)
    await db.refresh(edition)
    assert edition.status == "ready" and track.matched_chapter_id is not None
    assert await db.scalar(select(func.count(models.ImportedAudiobookCue.id))) > 0
    assert track.audio_file_path == "library/chapter.mp3"
    assert app_client.get("/api/books/catalog?view=all&source=audiobook").json()["total_count"] == 0
    repeated = app_client.post("/api/imports/preview", files={"files": ("book.epub", payload)}).json()
    assert repeated["items"][0]["status"] == "duplicate"
    backup = app_client.post(
        "/api/audiobook/libation-backup/preview", json={"source_paths": ["Backup/Artemis Fowl [B002V8MYYE]/book.m4b"]}
    ).json()
    assert backup["groups"][0]["book_id"] == book.id
    assert backup["groups"][0]["status"] == "already_imported"


@pytest.mark.asyncio
async def test_ambiguous_audio_books_flagged_in_preview_and_upload(db, app_client, library):
    first, _, _ = await audio_book(db)
    second, _, _ = await audio_book(db, title="Artemis Fowl (Unabridged)")
    payload = epub_bytes(ebook())
    preview = app_client.post("/api/imports/preview", files={"files": ("book.epub", payload)}).json()
    assert preview["items"][0]["status"] == "error"
    assert "More than one audiobook" in preview["items"][0]["detail"]
    response = app_client.post("/api/books/upload_epub", files={"file": ("book.epub", payload)})
    assert response.status_code == 422
    await db.refresh(first)
    await db.refresh(second)
    assert first.current_path is None and second.current_path is None
    assert not list(library.glob("tmp*"))
    assert await db.scalar(select(func.count(models.Book.id))) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "title,author,number",
    [
        ("Artemis Fowl", "Different Author", None),
        ("Artemis Fowl: Book 2", "Eoin Colfer", 2),
        ("Artemis Fowl: Omnibus", "Eoin Colfer", None),
        ("Artemis Fowl: The Arctic Incident", "Eoin Colfer", None),
    ],
)
async def test_matching_does_not_mix_authors_volumes_or_collections(db, title, author, number):
    await audio_book(db, series="Artemis Fowl", series_index=1)
    assert await match_epub_to_audio_book(db, ebook(title, author, number=number), title, author) is None


@pytest.mark.asyncio
async def test_isbn_equivalence_can_match_missing_author_and_different_title(db):
    book, _, _ = await audio_book(db, author="Unknown author", metadata_remote_ids={"isbn_10": "0439139597"})
    match = await match_epub_to_audio_book(db, ebook(identifier="urn:isbn:9780439139595"), "Artemis Fowl", "Eoin Colfer")
    assert match.id == book.id


@pytest.mark.asyncio
async def test_deleted_audio_book_is_not_automatically_restored(db):
    await audio_book(db, deleted_at=datetime.now(timezone.utc))
    assert await match_epub_to_audio_book(db, ebook(), "Artemis Fowl", "Eoin Colfer") is None


@pytest.mark.asyncio
async def test_audio_only_filter_in_groups_series_and_pagination(db, app_client):
    first, _, _ = await audio_book(db, series="Artemis Fowl")
    second, _, _ = await audio_book(db, title="The Arctic Incident", series="Artemis Fowl")
    complete, _, _ = await audio_book(
        db, title="The Eternity Code", series="Artemis Fowl", current_path="library/complete.epub"
    )
    complete.source_type = models.SourceType.epub
    await db.commit()
    groups = app_client.get("/api/library/groups?source=audiobook").json()
    assert len(groups) == 1 and groups[0]["book_count"] == 2
    params = {"source": "audiobook", "series": "Artemis Fowl", "view": "all", "limit": 1}
    page = app_client.get("/api/books/catalog", params=params).json()
    ids = [page["items"][0]["id"]]
    assert page["total_count"] == 2 and page["next_cursor"]
    params["cursor"] = page["next_cursor"]
    page = app_client.get("/api/books/catalog", params=params).json()
    ids.append(page["items"][0]["id"])
    assert set(ids) == {first.id, second.id} and page["next_cursor"] is None
