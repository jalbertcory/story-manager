"""Recover semantic reading blocks from the span-injected EPUB rendition."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from bs4 import BeautifulSoup, Tag

from ..models import AudiobookChapter, Book
from .audiobook_publication import normalize_resource_href, text_reader_path

_PRIMARY_BLOCK_TAGS = {
    "p",
    "li",
    "blockquote",
    "pre",
    "dt",
    "dd",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}


@dataclass(frozen=True)
class ReadingBlock:
    index: int
    kind: str


def _block_kind(element: Tag) -> str:
    if element.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "heading"
    if element.name in {"li", "dt", "dd"} or element.find_parent(["li", "dt", "dd"]):
        return "list-item"
    if element.name == "blockquote" or element.find_parent("blockquote"):
        return "quote"
    return "paragraph"


def _epub_member(names: list[str], chapter_href: str) -> str | None:
    normalized = normalize_resource_href(chapter_href).casefold()
    exact = [name for name in names if normalize_resource_href(name).casefold() == normalized]
    if exact:
        return min(exact, key=len)
    suffix = f"/{normalized}"
    matches = [name for name in names if normalize_resource_href(name).casefold().endswith(suffix)]
    return min(matches, key=len) if matches else None


@lru_cache(maxsize=256)
def _cached_reading_blocks(
    epub_path: str,
    modified_ns: int,
    chapter_href: str,
) -> dict[str, ReadingBlock]:
    del modified_ns  # It participates in the cache key and invalidates replaced files.
    try:
        with ZipFile(epub_path) as archive:
            member = _epub_member(archive.namelist(), chapter_href)
            if member is None:
                return {}
            content = archive.read(member)
    except (BadZipFile, KeyError, OSError):
        return {}

    soup = BeautifulSoup(content, "html.parser")
    container = soup.body or soup
    blocks: dict[str, ReadingBlock] = {}
    block_indexes: dict[int, int] = {}
    next_index = 0
    for span in container.find_all("span", id=True):
        block = span.find_parent(_PRIMARY_BLOCK_TAGS)
        if block is None:
            # Some EPUB generators use one div per paragraph instead of <p>.
            block = span.find_parent("div") or span
        identity = id(block)
        if identity not in block_indexes:
            block_indexes[identity] = next_index
            next_index += 1
        blocks[str(span["id"])] = ReadingBlock(
            index=block_indexes[identity],
            kind=_block_kind(block),
        )
    return blocks


def chapter_reading_blocks(book: Book, chapter: AudiobookChapter) -> dict[str, ReadingBlock]:
    """Map stable sentence span IDs to their original EPUB block."""
    epub_path = text_reader_path(book)
    chapter_href = chapter.source_href or chapter.content_file_name
    if epub_path is None or chapter_href is None:
        return {}
    return reading_blocks_from_epub(epub_path, chapter_href)


def reading_blocks_from_epub(epub_path: Path, chapter_href: str) -> dict[str, ReadingBlock]:
    """Extract block membership for stable sentence spans in one chapter."""
    try:
        modified_ns = epub_path.stat().st_mtime_ns
    except OSError:
        return {}
    return _cached_reading_blocks(str(epub_path), modified_ns, chapter_href)
