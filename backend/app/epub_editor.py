import logging
from pathlib import Path

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import re

logger = logging.getLogger(__name__)


def get_chapters(epub_path: str):
    book = epub.read_epub(epub_path)
    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        chapters.append(
            {
                "filename": item.get_name(),
                "title": item.get_name(),
                "content": item.get_content().decode("utf-8", "ignore"),
            }
        )
    return chapters


def get_word_count(epub_path: str) -> int:
    book = epub.read_epub(epub_path)
    word_count = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content = item.get_content()
        soup = BeautifulSoup(content, "html.parser")
        text = soup.get_text()
        word_count += len(re.findall(r"\S+", text))
    return word_count


def process_epub(
    immutable_path: str,
    current_path: str,
    removed_chapters: list[str],
    content_selectors: list[str],
    chapter_selectors: list[str] = [],
):
    book = epub.read_epub(immutable_path)
    new_book = epub.EpubBook()

    # Copy metadata
    for key, value in book.metadata.items():
        new_book.metadata[key] = value

    # Build the set of chapters to remove: explicit list + CSS-selector matches
    chapters_to_remove = set(removed_chapters)
    if chapter_selectors:
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content().decode("utf-8", "ignore"), "html.parser")
            if any(soup.select(sel) for sel in chapter_selectors):
                chapters_to_remove.add(item.get_name())

    for item in book.items:
        if item.get_name() not in chapters_to_remove:
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = item.get_content().decode("utf-8", "ignore")
                soup = BeautifulSoup(content, "html.parser")
                for selector in content_selectors:
                    for elem in soup.select(selector):
                        elem.decompose()
                item.set_content(str(soup).encode("utf-8"))
            new_book.add_item(item)

    # Rebuild spine and TOC
    new_book.spine = [item for item in book.spine if book.get_item_with_id(item[0]).get_name() not in chapters_to_remove]
    new_book.toc = [
        link for link in book.toc if isinstance(link, epub.Link) and link.href.split("#")[0] not in chapters_to_remove
    ]

    epub.write_epub(current_path, new_book, {})


async def apply_book_cleaning(book, db) -> None:
    """Apply all cleaning rules (site-wide config + per-book settings) to a book.

    Looks up the matching CleaningConfig for the book's source URL, merges its
    selectors with the book's own settings, then rewrites current_path from
    immutable_path and updates current_word_count in the DB.
    """
    from . import crud

    config = None
    if book.source_url:
        config = await crud.get_matching_cleaning_config(db, str(book.source_url))

    # Merge selectors from site-wide config and per-book settings
    chapter_selectors = list(config.chapter_selectors or []) if config else []
    content_selectors = list(config.content_selectors or []) if config else []
    content_selectors += list(book.content_selectors or [])
    removed_chapters = list(book.removed_chapters or [])

    # Nothing to do — skip the (potentially expensive) epub rewrite
    if not chapter_selectors and not content_selectors and not removed_chapters:
        return

    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    immutable_path = library_path.parent / book.immutable_path
    current_path = library_path.parent / book.current_path

    try:
        process_epub(
            str(immutable_path),
            str(current_path),
            removed_chapters,
            content_selectors,
            chapter_selectors,
        )
        book.current_word_count = get_word_count(str(current_path))
        await db.commit()
        await db.refresh(book)
    except Exception as e:
        logger.error("Failed to apply cleaning to %s: %s", book.title, e)
