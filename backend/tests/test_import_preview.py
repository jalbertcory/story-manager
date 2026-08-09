"""Preflight coverage for the guided import workflow."""

from pathlib import Path
import zipfile

from ebooklib import epub
import pytest
from sqlalchemy import func, select

from backend.app import crud, models, schemas


def create_epub(
    path: Path,
    *,
    title: str,
    author: str,
    series: str | None = None,
    source_url: str | None = None,
) -> bytes:
    book = epub.EpubBook()
    book.set_identifier(f"{title}-{author}")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    if series:
        book.add_metadata("calibre", "series", series)
    if source_url:
        book.add_metadata("DC", "source", source_url)
    chapter = epub.EpubHtml(title="Chapter 1", file_name="chapter.xhtml", lang="en")
    chapter.content = "<h1>Chapter 1</h1><p>Preview-only content.</p>"
    book.add_item(chapter)
    book.toc = (epub.Link("chapter.xhtml", "Chapter 1", "chapter-1"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter]
    epub.write_epub(path, book, {})
    return path.read_bytes()


@pytest.mark.asyncio
async def test_preview_epub_reports_metadata_rules_without_writing(app_client, db, tmp_path):
    db.add(
        models.CleaningConfig(
            name="Example fiction",
            url_pattern=r"example\.com/fiction",
            chapter_selectors=[".chapter"],
        )
    )
    await db.commit()
    payload = create_epub(
        tmp_path / "preview.epub",
        title="The Preview Book",
        author="A. Reader",
        series="Preflight Stories",
        source_url="https://example.com/fiction/42",
    )

    response = app_client.post(
        "/api/imports/preview",
        files={"files": ("preview.epub", payload, "application/epub+zip")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "key": "file:0",
                "input_type": "epub",
                "name": "preview.epub",
                "status": "ready",
                "title": "The Preview Book",
                "author": "A. Reader",
                "series": "Preflight Stories",
                "source_url": "https://example.com/fiction/42",
                "duplicate_book_id": None,
                "cleaning_configs": ["Example fiction"],
                "detail": None,
            }
        ],
        "ready_count": 1,
        "duplicate_count": 0,
        "unsupported_count": 0,
        "error_count": 0,
    }
    assert await db.scalar(select(func.count(models.Book.id))) == 0


@pytest.mark.asyncio
async def test_preview_marks_library_and_batch_duplicates(app_client, db, tmp_path):
    existing = await crud.create_book(
        db,
        schemas.BookCreate(
            title="Already Here",
            author="Known Author",
            immutable_path="already-here-immutable.epub",
            current_path="already-here.epub",
            source_type=models.SourceType.epub,
        ),
    )
    existing_web = await crud.create_book(
        db,
        schemas.BookCreate(
            title="Existing Web Story",
            author="Known Web Author",
            source_url="https://example.com/stories/already-here",
            source_type=models.SourceType.web,
        ),
    )
    existing_payload = create_epub(
        tmp_path / "existing.epub",
        title="Already Here",
        author="Known Author",
    )

    response = app_client.post(
        "/api/imports/preview",
        files={"files": ("existing.epub", existing_payload, "application/epub+zip")},
        data={
            "urls": [
                "https://example.com/stories/already-here",
                "https://example.com/stories/new",
                "https://example.com/stories/new",
            ]
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert [item["status"] for item in data["items"]] == [
        "duplicate",
        "duplicate",
        "ready",
        "duplicate",
    ]
    assert data["items"][0]["duplicate_book_id"] == existing.id
    assert data["items"][1]["duplicate_book_id"] == existing_web.id
    assert data["items"][3]["detail"] == "This URL appears more than once in this import."
    assert data["ready_count"] == 1
    assert data["duplicate_count"] == 3
    assert await db.scalar(select(func.count(models.Book.id))) == 2


def test_preview_reports_archives_without_epubs_and_invalid_urls(app_client, tmp_path):
    archive_path = tmp_path / "notes.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("notes.txt", "No books in this archive.")

    response = app_client.post(
        "/api/imports/preview",
        files={"files": ("notes.zip", archive_path.read_bytes(), "application/zip")},
        data={"urls": ["not a URL"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert [item["status"] for item in data["items"]] == ["unsupported", "error"]
    assert data["unsupported_count"] == 1
    assert data["error_count"] == 1
    assert data["ready_count"] == 0
