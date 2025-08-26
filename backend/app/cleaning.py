import logging
from pathlib import Path
from typing import List

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from . import models

logger = logging.getLogger(__name__)


def clean_epub(epub_path: Path, config: models.CleaningConfig) -> Path:
    """Create a cleaned copy of an EPUB based on the given configuration."""
    try:
        book = epub.read_epub(epub_path)
        items_to_remove: List = []
        chapter_selectors = config.chapter_selectors or []
        content_selectors = config.content_selectors or []

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            remove_chapter = any(soup.select(sel) for sel in chapter_selectors)
            if remove_chapter:
                items_to_remove.append(item)
                continue

            for sel in content_selectors:
                for elem in soup.select(sel):
                    elem.decompose()
            item.set_content(str(soup).encode("utf-8"))

        for item in items_to_remove:
            try:
                book.remove_item(item)
            except Exception:
                pass

        cleaned_path = epub_path.with_name(epub_path.stem + ".clean.epub")
        epub.write_epub(cleaned_path, book)
        return cleaned_path
    except Exception as e:
        logger.error(f"Failed to clean {epub_path}: {e}")
        return epub_path
