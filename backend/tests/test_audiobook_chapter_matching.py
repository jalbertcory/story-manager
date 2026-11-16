"""Regressions for publisher TOC labels and untitled EPUB front matter."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from ebooklib import epub

from backend.app.models import AudiobookChapter
from backend.app.services.audiobook_import import TrackSpec, _chapter_identity, _chapter_match
from backend.app.services.audiobook_ingestion import _chapter_title


@pytest.mark.parametrize("title", ["[ 1 ]", "[87]", "( 12 )", "[\u00a009\u00a0]"])
def test_decorated_number_matches_spoken_chapter(title):
    number = int(title.strip("[]() \u00a0"))
    assert _chapter_identity(title) == _chapter_identity(f"Chapter {number}")


@pytest.mark.parametrize("title", ["[ PART 1 ] THE CEASEFIRE", "Report 8", "[ 1 ] Appendix", "(2024) Notes"])
def test_numbers_in_named_sections_do_not_become_chapter_numbers(title):
    identity = _chapter_identity(title)
    assert identity is not None
    assert identity[0] == "named"


def test_numbered_audio_matches_decorated_toc_instead_of_untitled_front_matter():
    front_matter = epub.EpubHtml(file_name="copyright.xhtml")
    title = _chapter_title(front_matter, BeautifulSoup("<p>Copyright notice.</p>", "html.parser"), 6)
    chapters = [
        AudiobookChapter(id=1, chapter_number=6, title=title),
        AudiobookChapter(id=2, chapter_number=20, title="[ 6 ]"),
    ]
    track = TrackSpec(1, "Chapter 6", Path("audio.m4b"), 0, 1000, "audio/mp4")

    assert _chapter_match(track, chapters) is chapters[1]
    assert _chapter_match(track, chapters[:1]) is None


def test_real_chapter_title_is_preserved():
    item = epub.EpubHtml(file_name="chapter.xhtml")
    soup = BeautifulSoup("<h1>Chapter 6</h1><p>Story.</p>", "html.parser")
    assert _chapter_title(item, soup, 20) == "Chapter 6"
    assert _chapter_title(item, soup, 20, {"chapter.xhtml": "[ 6 ]"}) == "[ 6 ]"


@pytest.mark.parametrize("title", ["Copyright", "Dedication", "Epigraph"])
def test_front_matter_uses_document_title_when_it_has_no_heading(title):
    book = epub.EpubBook()
    item = epub.EpubHtml(file_name="front-matter.xhtml")
    item.content = f"<html><head><title>{title}</title></head><body><p>Text.</p></body></html>".encode()
    book.add_item(item)
    soup = BeautifulSoup(item.get_content(), "html.parser")
    assert soup.title is None
    assert _chapter_title(item, soup, 6) == title
