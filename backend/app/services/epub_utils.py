"""Lightweight EPUB helpers: word/chapter counting and cover extraction."""

import logging
import zipfile
from pathlib import Path
from typing import Optional

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from lxml import etree

logger = logging.getLogger(__name__)


def get_epub_word_and_chapter_count(epub_path: Path) -> tuple[int, int]:
    try:
        book = epub.read_epub(epub_path)
        chapters = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        word_count = 0
        for chapter in chapters:
            soup = BeautifulSoup(chapter.get_content(), "html.parser")
            text = soup.get_text()
            word_count += len(text.split())
        return word_count, len(chapters)
    except Exception as e:
        logger.error(f"Error reading epub file {epub_path}: {e}")
        return 0, 0


def get_and_save_epub_cover(epub_path: Path, book_id: int) -> Optional[Path]:
    """Extracts the cover image from an EPUB file and saves it to the covers directory."""
    from ..config import LIBRARY_PATH

    covers_path = (LIBRARY_PATH / "covers").resolve()
    covers_path.mkdir(exist_ok=True)

    try:
        with zipfile.ZipFile(epub_path) as z:
            t = etree.fromstring(z.read("META-INF/container.xml"))
            rootfile_path = t.xpath(
                "/u:container/u:rootfiles/u:rootfile",
                namespaces={"u": "urn:oasis:names:tc:opendocument:xmlns:container"},
            )[0].get("full-path")

            t = etree.fromstring(z.read(rootfile_path))
            cover_id = t.xpath(
                "//opf:metadata/opf:meta[@name='cover']",
                namespaces={"opf": "http://www.idpf.org/2007/opf"},
            )[
                0
            ].get("content")

            cover_href = t.xpath(
                "//opf:manifest/opf:item[@id='" + cover_id + "']",
                namespaces={"opf": "http://www.idpf.org/2007/opf"},
            )[0].get("href")

            cover_path_in_epub = (Path(rootfile_path).parent / cover_href).as_posix()
            cover_data = z.read(cover_path_in_epub)
            cover_extension = Path(cover_href).suffix
            save_path = covers_path / f"{book_id}{cover_extension}"

            with open(save_path, "wb") as f:
                f.write(cover_data)
            return save_path
    except Exception as e:
        logger.error(f"Error extracting cover from {epub_path}: {e}")
        return None
