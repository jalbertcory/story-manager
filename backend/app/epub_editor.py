import logging
from pathlib import Path

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import re

logger = logging.getLogger(__name__)


def get_chapters(epub_path: str):
    book = epub.read_epub(epub_path)

    # Build filename -> title map from the TOC
    title_map: dict[str, str] = {}

    def _walk_toc(items):
        for item in items:
            if isinstance(item, epub.Link):
                href = item.href.split("#")[0]
                if href not in title_map and item.title:
                    title_map[href] = item.title
            elif isinstance(item, tuple):
                section, children = item
                if isinstance(section, epub.Section) and getattr(section, "href", None):
                    href = section.href.split("#")[0]
                    if href not in title_map and section.title:
                        title_map[href] = section.title
                _walk_toc(children)

    _walk_toc(book.toc)

    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        filename = item.get_name()
        title = title_map.get(filename)
        if not title:
            soup = BeautifulSoup(item.get_content().decode("utf-8", "ignore"), "html.parser")
            heading = soup.find(["h1", "h2", "h3"])
            if heading:
                title = heading.get_text(strip=True)
        chapters.append(
            {
                "filename": filename,
                "title": title or filename,
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


def preview_epub(
    immutable_path: str,
    removed_chapters: list[str],
    content_selectors: list[str],
    chapter_selectors: list[str] = [],
) -> dict:
    book = epub.read_epub(immutable_path)
    chapters_to_remove = set(removed_chapters)
    if chapter_selectors:
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content().decode("utf-8", "ignore"), "html.parser")
            if any(soup.select(sel) for sel in chapter_selectors):
                chapters_to_remove.add(item.get_name())
    elements_removed = 0
    estimated_word_count = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        if item.get_name() in chapters_to_remove:
            continue
        soup = BeautifulSoup(item.get_content().decode("utf-8", "ignore"), "html.parser")
        for selector in content_selectors:
            for elem in soup.select(selector):
                elements_removed += 1
                elem.decompose()
        estimated_word_count += len(re.findall(r"\S+", soup.get_text()))
    return {"elements_removed": elements_removed, "estimated_word_count": estimated_word_count}


async def apply_book_cleaning(book, db, force: bool = False) -> None:
    """Apply all cleaning rules (site-wide configs + per-book settings) to a book.

    Looks up all matching CleaningConfigs for the book's source URL, merges their
    selectors with the book's own settings, then rewrites current_path from
    immutable_path and updates current_word_count in the DB.

    If force=True, always rewrites even when no selectors are set (resets to immutable).
    """
    from . import crud

    configs = []
    if book.source_url:
        configs = await crud.get_all_matching_cleaning_configs(db, str(book.source_url))

    # Merge selectors from all matching configs and per-book settings
    chapter_selectors: list[str] = []
    content_selectors: list[str] = []
    for cfg in configs:
        chapter_selectors += list(cfg.chapter_selectors or [])
        content_selectors += list(cfg.content_selectors or [])
    content_selectors += list(book.content_selectors or [])
    removed_chapters = list(book.removed_chapters or [])

    # Nothing to do — skip the (potentially expensive) epub rewrite
    if not force and not chapter_selectors and not content_selectors and not removed_chapters:
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
        await crud.touch_book_content(db, book)
        await db.commit()
        await db.refresh(book)
    except Exception as e:
        logger.error("Failed to apply cleaning to %s: %s", book.title, e)
