"""Uploads must never replace or delete files that belong to another book."""

from io import BytesIO
from unittest.mock import AsyncMock

from ebooklib import epub
import pytest
from sqlalchemy import func, select

from backend.app import config, models
from backend.app.routers import upload
from backend.app.services import library_paths


def epub_bytes(title: str, author: str, source_url: str | None = None) -> bytes:
    book = epub.EpubBook()
    book.set_identifier(f"{title}-{author}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    if source_url:
        book.add_metadata("DC", "source", source_url)
    chapter = epub.EpubHtml(title="Chapter 1", file_name="chapter.xhtml", lang="en")
    chapter.content = "<h1>Chapter 1</h1><p>Uploaded content.</p>"
    book.add_item(chapter)
    book.toc = (epub.Link("chapter.xhtml", "Chapter 1", "chapter-1"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    output = BytesIO()
    epub.write_epub(output, book)
    return output.getvalue()


@pytest.fixture
def library(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    for module in (upload, library_paths, config):
        monkeypatch.setattr(module, "LIBRARY_PATH", library)
    monkeypatch.setattr(upload, "queue_metadata_sync_job", AsyncMock())
    return library


@pytest.mark.asyncio
async def test_upload_matching_web_book_coexists_without_touching_its_files(db, app_client, library):
    # The web book's files sit exactly where the upload would land by name.
    immutable, current = library_paths.build_book_paths("Web Story - Web Author.epub", "Web Author")
    immutable.write_bytes(b"original web immutable")
    current.write_bytes(b"original web current")
    web_book = models.Book(
        title="Web Story",
        author="Web Author",
        source_type=models.SourceType.web,
        source_url="https://example.com/s/1",
        immutable_path=str(immutable.relative_to(library.parent)),
        current_path=str(current.relative_to(library.parent)),
    )
    db.add(web_book)
    await db.commit()

    response = app_client.post(
        "/api/books/upload_epub",
        files={"file": ("story.epub", epub_bytes("Web Story", "Web Author"))},
    )

    assert response.status_code == 201, response.text
    assert response.json()["id"] != web_book.id
    assert response.json()["current_path"].endswith("Web Story - Web Author - 2.epub")
    assert immutable.read_bytes() == b"original web immutable"
    assert current.read_bytes() == b"original web current"
    assert await db.scalar(select(func.count(models.Book.id))) == 2
    assert not list((library / ".staging").glob("tmp_*"))


@pytest.mark.asyncio
async def test_new_upload_does_not_replace_untracked_file_at_target_path(db, app_client, library):
    immutable, current = library_paths.build_book_paths("New Story - Some Author.epub", "Some Author")
    current.write_bytes(b"someone else's file")

    response = app_client.post(
        "/api/books/upload_epub",
        files={"file": ("new.epub", epub_bytes("New Story", "Some Author"))},
    )

    assert response.status_code == 201, response.text
    assert current.read_bytes() == b"someone else's file"
    assert not immutable.exists()
    body = response.json()
    assert body["current_path"].endswith("New Story - Some Author - 2.epub")
    assert (library.parent / body["current_path"]).read_bytes().startswith(b"PK")


def test_reserve_book_paths_skips_taken_names(library):
    first = library_paths.reserve_book_paths("Title - Author.epub", "Author")
    second = library_paths.reserve_book_paths("Title - Author.epub", "Author")

    assert first[1].name == "Title - Author.epub"
    assert second[1].name == "Title - Author - 2.epub"
    assert second[0].name == "immutable_Title - Author - 2.epub"
    assert all(path.exists() for path in (*first, *second))
