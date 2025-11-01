import asyncio
from backend.app.database import SessionLocal
from backend.app import crud, schemas, models
from ebooklib import epub
from pathlib import Path

def create_dummy_epub(filepath: Path, title: str, author: str, series: str = None):
    """Creates a dummy EPUB file for testing."""
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    if series:
        book.add_metadata("calibre", "series", series)
    # Add a dummy chapter
    c1 = epub.EpubHtml(title="Intro", file_name="chap_1.xhtml", lang="en")
    c1.content = "<h1>Introduction</h1><p>Introduction text.</p>"
    book.add_item(c1)
    book.toc = (epub.Link("chap_1.xhtml", "Introduction", "intro"),)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1]
    epub.write_epub(filepath, book, {})

async def main():
    library_path = Path("./library").resolve()
    library_path.mkdir(exist_ok=True)
    epub_filepath = library_path / "test.epub"
    create_dummy_epub(epub_filepath, "Test Book", "Test Author")

    db = SessionLocal()
    book = schemas.BookCreate(
        title="Test Book",
        author="Test Author",
        epub_path="library/test.epub",
        source_type=models.SourceType.epub,
    )
    await crud.create_book(db, book)
    await db.close()

if __name__ == "__main__":
    asyncio.run(main())
