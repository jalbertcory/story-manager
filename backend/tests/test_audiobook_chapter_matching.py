"""Regressions for publisher TOC labels and untitled EPUB front matter."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from ebooklib import epub

from backend.app.models import AudiobookChapter
from backend.app.services.audiobook_chapter_titles import chapter_identity, numbered_title, same_chapter
from backend.app.services.audiobook_import import TrackSpec, _chapter_match
from backend.app.services.audiobook_ingestion import _chapter_title


@pytest.mark.parametrize("title", ["[ 1 ]", "[87]", "( 12 )", "[\u00a009\u00a0]"])
def test_decorated_number_matches_spoken_chapter(title):
    number = int(title.strip("[]() \u00a0"))
    assert chapter_identity(title) == chapter_identity(f"Chapter {number}")


@pytest.mark.parametrize("title", ["[ PART 1 ] THE CEASEFIRE", "Report 8", "[ 1 ] Appendix", "(2024) Notes"])
def test_numbers_in_named_sections_do_not_become_chapter_numbers(title):
    identity = chapter_identity(title)
    assert identity is not None
    assert identity[0] == "named"


@pytest.mark.parametrize(
    ("title", "same_as"),
    [
        ("One", "Chapter 1"),
        ("Thirty-Seven", "Chapter 37"),
        ("Twenty one", "Chapter 21"),
        ("One Hundred and Five", "Chapter 105"),
        ("Chapter One: Feyre", "Chapter 1"),
        ("CHAPTER TWELVE", "Chapter 12"),
        ("Chapter I Chade Fallstar", "Chapter I"),
        ("Chapter XLII. The Siege", "Chapter 42"),
        ("1. Aftermath", "Chapter 1: Aftermath"),
        ("1: Warlords", "Chapter 1"),
        ("12) The Door", "Chapter 12"),
        ("12 \u2013 The Door", "Chapter 12"),
        ("Nine - The Door", "Chapter 9"),
        ("Chapter 0", "[ 0 ]"),
        ("Chapter Thirty\u2013Seven", "Chapter 37"),
        ("Thirty \u2013 Seven", "Chapter 37"),
        ("Twenty - One", "Chapter 21"),
        ("Chapter 12-A", "Chapter 12"),
        ("02 - Chapter 1", "Chapter 1"),
    ],
)
def test_spelled_roman_and_subtitled_numbers_match_chapter_number(title, same_as):
    assert chapter_identity(title) == chapter_identity(same_as)
    assert chapter_identity(title)[0] == "chapter"


@pytest.mark.parametrize(
    "title",
    [
        "Part I",
        "Part I: Bow",
        "Book One: Dusk",
        "7 Days Later",
        "1945: The End",
        "1.5",
        "One Last Thing",
        "Two-Face: Origins",
        "I Am Legend",
        "Chapter Mix",
        "Chapter Interlude",
        "Chapter Two and Three",
        "Chapter IIII",
        "Twelve hundred",
        "Section 4",
        "Chapter Twenty-First",
        "CHAPTER MIX",
        "Chapter I'm Home",
    ],
)
def test_titles_that_only_start_with_a_number_stay_named(title):
    identity = chapter_identity(title)
    assert identity is not None
    assert identity[0] == "named"


def test_spelled_out_track_matches_numbered_chapter():
    chapters = [
        AudiobookChapter(id=1, chapter_number=1, title="Section 4"),
        AudiobookChapter(id=2, chapter_number=2, title="Chapter One"),
        AudiobookChapter(id=3, chapter_number=3, title="Chapter Two"),
    ]

    assert _chapter_match(TrackSpec(1, "One", Path("audio.m4b"), 0, 1000, "audio/mp4"), chapters) is chapters[1]
    assert _chapter_match(TrackSpec(2, "2. Arrival", Path("audio.m4b"), 1000, 2000, "audio/mp4"), chapters) is chapters[2]


@pytest.mark.parametrize(
    ("title", "same_as"),
    [
        ("01 - Prologue", "Prologue"),
        ("45 - Epilogue", "Epilogue"),
        ("03 - Interlude", "Interlude"),
        ("05 - Part Two", "Part Two"),
    ],
)
def test_track_index_before_a_section_name_is_not_a_chapter_number(title, same_as):
    assert numbered_title(title) is None
    assert chapter_identity(title) == chapter_identity(same_as)


def test_leading_number_before_a_subtitle_may_be_a_track_index():
    # With a prologue as track 01, "02 - Title 1" is chapter 1, so it must not
    # take chapter 2 when chapter 2 has a different subtitle.
    assert numbered_title("02 - Title 1").indexed
    assert not numbered_title("Chapter 2: Title 2").indexed
    assert not same_chapter("02 - Title 1", "Chapter 2: Title 2")
    assert same_chapter("02 - Title 1", "Chapter 2")
    assert same_chapter("1. Awakening", "Chapter 1: The Awakening")
    assert same_chapter("1", "1: Warlords")
    # Stated chapter numbers still match whatever their subtitles say.
    assert same_chapter("Chapter 5: Foo", "Chapter 5: Bar")


def test_parts_that_restart_numbering_match_by_exact_title():
    chapters = [
        AudiobookChapter(id=1, chapter_number=1, title="Part One: Chapter One"),
        AudiobookChapter(id=2, chapter_number=2, title="Part Two: Chapter One"),
    ]
    track = TrackSpec(1, "Part Two: Chapter One", Path("audio.m4b"), 0, 1000, "audio/mp4")

    assert _chapter_match(track, chapters) is chapters[1]


def test_track_index_offset_by_a_prologue_does_not_shift_matches():
    titles = ["Prologue", *(f"Chapter {i}: Title {i}" for i in range(1, 6)), "Epilogue"]
    chapters = [AudiobookChapter(id=i, chapter_number=i, title=title) for i, title in enumerate(titles, 1)]
    tracks = ["01 - Prologue", *(f"{i + 1:02d} - Title {i}" for i in range(1, 6)), "07 - Epilogue"]

    matched = [
        _chapter_match(TrackSpec(i, title, Path("a.mp3"), 0, 1000, "audio/mpeg"), chapters)
        for i, title in enumerate(tracks, 1)
    ]

    assert matched[0] is chapters[0]
    assert matched[-1] is chapters[-1]
    # The indexes are off by one, so the subtitles disagree and nothing in
    # between is matched to the wrong chapter; it is left for review.
    assert all(chapter is None for chapter in matched[1:-1])


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
