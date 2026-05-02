import zipfile
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub

from backend.app import epub_editor
from backend.app.services.epub_utils import PROSE_BLOCK_MAX_CHARS


def _create_epub(filepath: Path, chapter_html: str) -> None:
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title("Normalizer Test")
    book.set_language("en")
    book.add_author("Test Author")

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap_1.xhtml", lang="en")
    chapter.content = chapter_html
    book.add_item(chapter)
    book.spine = ["nav", chapter]
    book.toc = (chapter,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(filepath), book, {})


def _chapter_soup(epub_path: Path) -> BeautifulSoup:
    with zipfile.ZipFile(epub_path) as archive:
        chapter_name = next(name for name in archive.namelist() if name.endswith("chap_1.xhtml"))
        return BeautifulSoup(archive.read(chapter_name), "html.parser")


def test_process_epub_normalizes_oversized_prose_blocks(tmp_path):
    immutable_path = tmp_path / "immutable.epub"
    current_path = tmp_path / "current.epub"
    parts = ["First sentence. " * 90, "Second sentence. " * 90, "Third sentence. " * 90]
    _create_epub(immutable_path, f"<h1>Chapter 1</h1><p>{'<br/><br/>'.join(parts)}</p>")

    word_count = epub_editor.process_epub(
        str(immutable_path),
        str(current_path),
        removed_chapters=[],
        content_selectors=[],
        normalize_prose_blocks=True,
    )

    soup = _chapter_soup(current_path)
    paragraphs = soup.find_all("p")
    assert word_count is not None
    assert len(paragraphs) == 3
    assert all(len(p.get_text(" ", strip=True)) <= PROSE_BLOCK_MAX_CHARS for p in paragraphs)
