"""Background cover extraction and source fallback."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import LIBRARY_PATH
from ..models import Book
from .cover_collectors import collect_cover
from .epub_utils import get_and_save_epub_cover


async def reextract_book_cover(book: Book, db: AsyncSession) -> None:
    if not book.immutable_path:
        raise ValueError("Book has no EPUB file to extract cover from.")

    epub_path = LIBRARY_PATH.parent / book.immutable_path
    cover_path = get_and_save_epub_cover(epub_path=epub_path, book_id=book.id)
    if cover_path is None and book.source_url:
        cover_path = await collect_cover(book.source_url, book.id)
    if cover_path is None:
        raise ValueError("Could not extract or scrape a cover image.")

    book.cover_path = str(cover_path.relative_to(LIBRARY_PATH.parent))
    await db.commit()
