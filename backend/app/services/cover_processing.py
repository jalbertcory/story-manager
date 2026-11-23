"""Background cover extraction with source-page and catalogue fallbacks."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import LIBRARY_PATH
from ..metadata_types import searchable_identifiers
from ..models import Book
from .cover_collectors import collect_cover
from .cover_images import save_cover_from_url
from .epub_utils import get_and_save_epub_cover

OPEN_LIBRARY_COVERS_URL = "https://covers.openlibrary.org/b"


def metadata_cover_urls(book: Book) -> list[str]:
    """Cover addresses implied by a book's matched catalogue metadata, best first."""
    urls: list[str] = []
    details = book.metadata_details if isinstance(book.metadata_details, dict) else {}
    stored = details.get("cover_url")
    if isinstance(stored, str) and stored.strip().startswith(("http://", "https://")):
        urls.append(stored.strip())

    # ``default=false`` makes Open Library answer 404 rather than a blank image.
    remote_ids = searchable_identifiers(book.metadata_remote_ids)
    for key in ("isbn_13", "isbn_10"):
        isbn = "".join(character for character in remote_ids.get(key, "") if character.isalnum())
        if isbn:
            urls.append(f"{OPEN_LIBRARY_COVERS_URL}/isbn/{isbn}-L.jpg?default=false")
    edition = remote_ids.get("open_library_edition_key", "").rstrip("/").rsplit("/", 1)[-1]
    if edition.isalnum():
        urls.append(f"{OPEN_LIBRARY_COVERS_URL}/olid/{edition}-L.jpg?default=false")
    return list(dict.fromkeys(urls))


async def collect_metadata_cover(book: Book) -> Path | None:
    for url in metadata_cover_urls(book):
        cover_path = await save_cover_from_url(url, book.id)
        if cover_path is not None:
            return cover_path
    return None


async def reextract_book_cover(book: Book, db: AsyncSession) -> None:
    if not book.immutable_path:
        raise ValueError("Book has no EPUB file to extract cover from.")

    epub_path = LIBRARY_PATH.parent / book.immutable_path
    cover_path = get_and_save_epub_cover(epub_path=epub_path, book_id=book.id)
    if cover_path is None and book.source_url:
        cover_path = await collect_cover(book.source_url, book.id)
    if cover_path is None:
        cover_path = await collect_metadata_cover(book)
    if cover_path is None:
        raise ValueError("Could not find a cover in the EPUB, on its source page or in its matched metadata.")

    book.cover_path = str(cover_path.relative_to(LIBRARY_PATH.parent))
    await db.commit()
