import logging
import filecmp
from pathlib import Path
from tempfile import NamedTemporaryFile

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import re

logger = logging.getLogger(__name__)


def _files_match(left: Path, right: Path) -> bool:
    if not left.is_file() or not right.is_file():
        return False
    if left.stat().st_size != right.stat().st_size:
        return False
    return filecmp.cmp(str(left), str(right), shallow=False)


def _spine_entry_name(book: epub.EpubBook, spine_entry) -> str | None:
    item_ref = spine_entry[0] if isinstance(spine_entry, tuple) else spine_entry
    if hasattr(item_ref, "get_name"):
        return item_ref.get_name()
    if isinstance(item_ref, str):
        item = book.get_item_with_id(item_ref)
        return item.get_name() if item is not None else None
    return None


def _toc_item_href(item) -> str | None:
    if isinstance(item, epub.Link):
        return item.href.split("#")[0]
    if isinstance(item, epub.Section):
        href = getattr(item, "href", None)
        return href.split("#")[0] if href else None
    if hasattr(item, "get_name"):
        return item.get_name().split("#")[0]
    return None


def _filter_toc(items, chapters_to_remove: set[str]):
    filtered = []
    for item in items:
        if isinstance(item, tuple):
            section, children = item
            filtered_children = _filter_toc(children, chapters_to_remove)
            href = _toc_item_href(section)
            if href in chapters_to_remove and not filtered_children:
                continue
            filtered.append((section, filtered_children))
            continue

        href = _toc_item_href(item)
        if href and href in chapters_to_remove:
            continue
        filtered.append(item)

    return tuple(filtered) if isinstance(items, tuple) else filtered


def _merge_cleaning_rules(book, configs) -> tuple[list[str], list[str], list[str]]:
    chapter_selectors: list[str] = []
    content_selectors: list[str] = []
    for cfg in configs:
        chapter_selectors += list(cfg.chapter_selectors or [])
        content_selectors += list(cfg.content_selectors or [])
    content_selectors += list(book.content_selectors or [])
    removed_chapters = list(book.removed_chapters or [])
    return removed_chapters, content_selectors, chapter_selectors


def _match_cleaning_configs(book, cleaning_configs) -> list:
    if not book.source_url:
        return []
    return [cfg for cfg in cleaning_configs if re.search(cfg.url_pattern, str(book.source_url))]


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
    return _compute_word_count(book)


def _compute_word_count(book: epub.EpubBook) -> int:
    """Count words across all document items in an in-memory EpubBook."""
    word_count = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        if isinstance(item, (epub.EpubNav, epub.EpubNcx)):
            continue
        content = item.get_content()
        soup = BeautifulSoup(content, "html.parser")
        word_count += len(re.findall(r"\S+", soup.get_text()))
    return word_count


def process_epub(
    immutable_path: str,
    current_path: str,
    removed_chapters: list[str],
    content_selectors: list[str],
    chapter_selectors: list[str] = [],
) -> int | None:
    """Process an epub, returning the new word count if changed, or None if unchanged."""
    book = epub.read_epub(immutable_path)
    new_book = epub.EpubBook()

    # Copy metadata, filtering out Calibre custom columns (e.g. "user_metadata:#sort")
    # that cause ValueError in ebooklib when serialising to XML.
    for ns, values in book.metadata.items():
        if ns:
            new_book.metadata[ns] = values
        else:
            new_book.metadata[ns] = {name: vals for name, vals in values.items() if not name.startswith("user_metadata:")}

    # Build the set of chapters to remove: explicit list + CSS-selector matches
    chapters_to_remove = set(removed_chapters)
    if chapter_selectors:
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content().decode("utf-8", "ignore"), "html.parser")
            if any(soup.select(sel) for sel in chapter_selectors):
                chapters_to_remove.add(item.get_name())

    for item in book.items:
        if item is None:
            continue
        if item.get_name() not in chapters_to_remove:
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                content = item.get_content().decode("utf-8", "ignore")
                soup = BeautifulSoup(content, "html.parser")
                for selector in content_selectors:
                    for elem in soup.select(selector):
                        elem.decompose()
                item.set_content(str(soup).encode("utf-8"))
            new_book.add_item(item)

    # Rebuild spine and TOC without assuming every spine entry is a tuple
    new_book.spine = [
        spine_entry
        for spine_entry in book.spine
        if (entry_name := _spine_entry_name(book, spine_entry)) is None or entry_name not in chapters_to_remove
    ]
    new_book.toc = _filter_toc(book.toc, chapters_to_remove)

    current_path_obj = Path(current_path)
    current_path_obj.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(suffix=".epub", dir=str(current_path_obj.parent), delete=False) as temp_file:
            temporary_path = Path(temp_file.name)
        epub.write_epub(str(temporary_path), new_book, {})
        if _files_match(temporary_path, current_path_obj):
            return None
        temporary_path.replace(current_path_obj)
        return _compute_word_count(new_book)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


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


async def apply_book_cleaning(book, db, force: bool = False, cleaning_configs: list | None = None) -> bool:
    """Apply all cleaning rules (site-wide configs + per-book settings) to a book.

    Looks up all matching CleaningConfigs for the book's source URL, merges their
    selectors with the book's own settings, then rewrites current_path from
    immutable_path and updates current_word_count in the DB.

    Books with no applicable rules are always skipped. If force=True, rewrites
    even when the output would match the current file.
    """
    from . import crud

    if cleaning_configs is None:
        configs = []
        if book.source_url:
            configs = await crud.get_all_matching_cleaning_configs(db, str(book.source_url))
    else:
        configs = _match_cleaning_configs(book, cleaning_configs)

    removed_chapters, content_selectors, chapter_selectors = _merge_cleaning_rules(book, configs)

    has_rules = bool(chapter_selectors or content_selectors or removed_chapters)

    # Nothing to do — skip the (potentially expensive) epub rewrite
    if not has_rules:
        return False

    if not book.immutable_path or not book.current_path:
        logger.warning(
            "Book %r (id=%s) is missing epub paths (immutable=%s, current=%s), skipping cleaning",
            book.title,
            book.id,
            book.immutable_path,
            book.current_path,
        )
        return False

    library_path = (Path(__file__).parent.resolve() / ".." / ".." / "library").resolve()
    immutable_path = library_path.parent / book.immutable_path
    current_path = library_path.parent / book.current_path

    try:
        word_count = process_epub(
            str(immutable_path),
            str(current_path),
            removed_chapters,
            content_selectors,
            chapter_selectors,
        )
        if word_count is None:
            if force:
                await crud.touch_book_content(db, book)
                await db.commit()
                await db.refresh(book)
                return True
            return False
        book.current_word_count = word_count
        await crud.touch_book_content(db, book)
        await db.commit()
        await db.refresh(book)
        return True
    except Exception as e:
        logger.error("Failed to apply cleaning to %s: %s", book.title, e, exc_info=True)
        return False
