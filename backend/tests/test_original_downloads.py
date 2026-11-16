"""Original downloads must preserve source bytes and stay within the book."""

from datetime import datetime, timezone
from urllib.parse import quote

import pytest

from backend.app import models
from backend.app.routers import books
from backend.app.services import library_paths


@pytest.fixture
def library(tmp_path, monkeypatch):
    path = tmp_path / "library"
    path.mkdir()
    monkeypatch.setattr(books, "LIBRARY_PATH", path)
    monkeypatch.setattr(library_paths, "LIBRARY_PATH", path)
    return path


async def create_book(db, source_type=models.SourceType.epub, **kwargs):
    book = models.Book(title="Originals", author="Author", source_type=source_type, **kwargs)
    db.add(book)
    await db.commit()
    return book


async def create_edition(db, book):
    edition = models.ImportedAudiobook(book_id=book.id, name="Narrated edition", status="ready")
    db.add(edition)
    await db.commit()
    return edition


@pytest.mark.asyncio
async def test_epub_download_preserves_original_and_current_download(db, app_client, library):
    original = library / "Original café.epub"
    original.write_bytes(b"original epub bytes")
    (library / "cleaned.epub").write_bytes(b"cleaned epub bytes")
    book = await create_book(db, immutable_path=f"library/{original.name}", current_path="library/cleaned.epub")

    response = app_client.get(f"/api/books/{book.id}/original-files")
    assert response.status_code == 200
    assert response.json() == [
        {
            "filename": original.name,
            "kind": "epub",
            "edition_name": None,
            "size_bytes": original.stat().st_size,
            "download_url": f"/api/books/{book.id}/download-original",
        }
    ]
    download = app_client.get(response.json()[0]["download_url"])
    assert download.status_code == 200
    assert download.content == original.read_bytes()
    assert download.headers["content-type"] == "application/epub+zip"
    assert download.headers["content-disposition"] == f"attachment; filename*=utf-8''{quote(original.name)}"
    assert app_client.get(f"/api/books/{book.id}/download").content == b"cleaned epub bytes"


@pytest.mark.asyncio
async def test_audio_downloads_list_all_sources_and_preserve_bytes(db, app_client, library):
    book = await create_book(db, source_type=models.SourceType.audiobook)
    edition = await create_edition(db, book)
    folder = library / "audiobooks" / str(book.id) / "imports" / str(edition.id)
    source = folder / "source"
    incoming = folder / "incoming"
    source.mkdir(parents=True)
    incoming.mkdir()
    filename = "Part 1 café & #2.m4b"
    (source / filename).write_bytes(b"original audio")
    (incoming / "Part 2.mp3").write_bytes(b"pending audio")
    (source / "manifest.json").write_text("{}")
    (source / "chapters.cue").write_text("cue markers")
    (folder / "derived").mkdir()
    (folder / "derived" / "chapter.mp3").write_bytes(b"derived audio")

    files = app_client.get(f"/api/books/{book.id}/original-files").json()
    assert {file["filename"] for file in files} == {filename, "Part 2.mp3"}
    assert all(file["kind"] == "audio" and file["edition_name"] == edition.name for file in files)
    for file in files:
        download = app_client.get(file["download_url"])
        assert download.status_code == 200
        assert download.content == (b"original audio" if file["filename"] == filename else b"pending audio")
        assert download.headers["content-disposition"].startswith("attachment;")
        assert len(download.content) == file["size_bytes"]

    # Importing moves the file, but an already-rendered download link still works.
    pending = next(file for file in files if file["filename"] == "Part 2.mp3")
    (incoming / "Part 2.mp3").rename(source / "Part 2.mp3")
    assert app_client.get(pending["download_url"]).content == b"pending audio"
    partial = app_client.get(files[0]["download_url"], headers={"Range": "bytes=0-3"})
    assert partial.status_code == 206
    assert partial.content == b"orig"


@pytest.mark.asyncio
async def test_missing_files_and_books_return_not_found(db, app_client, library):
    book = await create_book(db, immutable_path="library/missing.epub")
    edition = await create_edition(db, book)
    assert app_client.get(f"/api/books/{book.id}/original-files").json() == []
    assert app_client.get(f"/api/books/{book.id}/download-original").status_code == 404
    assert app_client.get(f"/api/books/{book.id}/original-audio/{edition.id}?filename=missing.mp3").status_code == 404
    assert app_client.get("/api/books/999999/original-files").status_code == 404
    assert app_client.get("/api/books/999999/download-original").status_code == 404


@pytest.mark.asyncio
async def test_downloads_reject_other_books_traversal_and_symlinks(db, app_client, library):
    outside = library.parent / "private.mp3"
    outside.write_bytes(b"private")
    book = await create_book(db, immutable_path=str(outside))
    other = await create_book(db)
    edition = await create_edition(db, book)
    source = library / "audiobooks" / str(book.id) / "imports" / str(edition.id) / "source"
    source.mkdir(parents=True)
    (source / "audio.mp3").write_bytes(b"original")
    (source / "escaped.mp3").symlink_to(outside)

    files = app_client.get(f"/api/books/{book.id}/original-files").json()
    assert [file["filename"] for file in files] == ["audio.mp3"]
    assert app_client.get(f"/api/books/{book.id}/download-original").status_code == 404
    assert app_client.get(f"/api/books/{other.id}/original-audio/{edition.id}?filename=audio.mp3").status_code == 404
    for filename in ("../audio.mp3", str(outside), "escaped.mp3", "manifest.json"):
        assert (
            app_client.get(f"/api/books/{book.id}/original-audio/{edition.id}", params={"filename": filename}).status_code
            == 404
        )

    book.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    assert app_client.get(f"/api/books/{book.id}/original-files").status_code == 404
    assert app_client.get(files[0]["download_url"]).status_code == 404
