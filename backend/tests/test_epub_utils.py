import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

from backend.app.services.epub_utils import (
    PROSE_BLOCK_MAX_CHARS,
    get_and_save_epub_cover,
    get_epub_genre_tags,
    get_epub_source_tags,
    normalize_xhtml_prose_blocks,
)


def write_minimal_epub(epub_path: Path, opf: str, entries: dict[str, bytes] | None = None) -> None:
    epub_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(epub_path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
        )
        archive.writestr("content.opf", opf)
        for name, content in (entries or {}).items():
            archive.writestr(name, content)


def _paragraph_texts(content: bytes) -> list[str]:
    soup = BeautifulSoup(content, "html.parser")
    return [p.get_text(" ", strip=True) for p in soup.find_all("p")]


def test_normalize_xhtml_prose_blocks_leaves_normal_paragraphs_unchanged():
    html = b"<html><body><p>First paragraph.</p><p><em>Second</em> paragraph.</p></body></html>"

    normalized, changed = normalize_xhtml_prose_blocks(html)

    assert changed is False
    assert normalized == html


def test_normalize_xhtml_prose_blocks_splits_double_br_paragraph_breaks():
    parts = [
        "First sentence. " * 80,
        "Second sentence. " * 80,
        "Third sentence. " * 80,
    ]
    html = f"<html><body><p class='chapter'>{'<br/><br/>'.join(parts)}</p></body></html>"

    normalized, changed = normalize_xhtml_prose_blocks(html)

    soup = BeautifulSoup(normalized, "html.parser")
    paragraphs = soup.find_all("p")
    assert changed is True
    assert len(paragraphs) == 3
    assert [p.get("class") for p in paragraphs] == [["chapter"], ["chapter"], ["chapter"]]
    assert _paragraph_texts(normalized) == [part.strip() for part in parts]
    assert all(len(text) <= PROSE_BLOCK_MAX_CHARS for text in _paragraph_texts(normalized))


def test_normalize_xhtml_prose_blocks_splits_simple_prose_at_sentence_boundaries():
    text = " ".join(f"This is sentence number {index} with enough words to make the paragraph long." for index in range(180))
    html = f"<html><body><p>{text}</p></body></html>"

    normalized, changed = normalize_xhtml_prose_blocks(html)

    paragraphs = _paragraph_texts(normalized)
    assert changed is True
    assert len(paragraphs) > 1
    assert " ".join(paragraphs) == text
    assert all(len(text) <= PROSE_BLOCK_MAX_CHARS for text in paragraphs)


def test_normalize_xhtml_prose_blocks_preserves_inline_formatting_when_splitting_on_breaks():
    first = "<em>First emphasized sentence.</em> " + ("More first text. " * 120)
    second = "<strong>Second bold sentence.</strong> <span>More second text.</span> " + ("Tail text. " * 130)
    html = f"<html><body><p>{first}<br/><br/>{second}</p></body></html>"

    normalized, changed = normalize_xhtml_prose_blocks(html)

    soup = BeautifulSoup(normalized, "html.parser")
    paragraphs = soup.find_all("p")
    assert changed is True
    assert len(paragraphs) == 2
    assert paragraphs[0].find("em").get_text(strip=True) == "First emphasized sentence."
    assert paragraphs[1].find("strong").get_text(strip=True) == "Second bold sentence."
    assert paragraphs[1].find("span").get_text(strip=True) == "More second text."


def test_normalize_xhtml_prose_blocks_skips_risky_and_non_prose_structures():
    long_text = "Risky sentence. " * 260
    html = f"""<html><body>
<p>{long_text}<a href="chapter.xhtml">linked text</a><br/><br/>{long_text}</p>
<p>{long_text}<code>code text</code><br/><br/>{long_text}</p>
<pre>{long_text}<br/><br/>{long_text}</pre>
<table><tr><td>{long_text}</td></tr></table>
</body></html>"""

    normalized, changed = normalize_xhtml_prose_blocks(html)

    soup = BeautifulSoup(normalized, "html.parser")
    assert changed is False
    assert len(soup.find_all("p")) == 2
    assert len(soup.find_all("pre")) == 1
    assert len(soup.find_all("table")) == 1


def test_get_and_save_epub_cover_uses_epub3_cover_image_property(tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    monkeypatch.setattr("backend.app.config.LIBRARY_PATH", library_path)
    cover_bytes = b"fake-jpeg-cover"
    epub_path = tmp_path / "with-cover.epub"
    write_minimal_epub(
        epub_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Cover Book</dc:title>
  </metadata>
  <manifest>
    <item id="cover-img" href="Images/front.jpg" media-type="image/jpeg" properties="cover-image"/>
    <item id="chap-1" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap-1"/>
  </spine>
</package>
""",
        {"Images/front.jpg": cover_bytes},
    )

    cover_path = get_and_save_epub_cover(epub_path, book_id=42)

    assert cover_path == library_path / "covers" / "42.jpg"
    assert cover_path.read_bytes() == cover_bytes


def test_get_and_save_epub_cover_returns_none_when_epub_has_no_images(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.config.LIBRARY_PATH", tmp_path / "library")
    epub_path = tmp_path / "no-cover.epub"
    write_minimal_epub(
        epub_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>No Cover Book</dc:title>
  </metadata>
  <manifest>
    <item id="chap-1" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap-1"/>
  </spine>
</package>
""",
    )

    assert get_and_save_epub_cover(epub_path, book_id=7) is None


def test_get_epub_tags_split_fff_title_page_category_and_genre(tmp_path):
    epub_path = tmp_path / "metadata.epub"
    write_minimal_epub(
        epub_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Tagged Book</dc:title>
    <dc:subject>Last Update: 2026/04/15</dc:subject>
    <dc:subject>In-Progress</dc:subject>
  </metadata>
  <manifest>
    <item id="title_page" href="OEBPS/title_page.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap-1" href="OEBPS/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="title_page"/>
    <itemref idref="chap-1"/>
  </spine>
</package>
""",
        {"OEBPS/title_page.xhtml": b"""<html><body>
<b>Category:</b> Awkward Protagonist, Character Growth<br />
<b>Genre:</b> Action, Comedy, Action<br />
</body></html>"""},
    )

    assert get_epub_genre_tags(epub_path) == [
        "Action",
        "Comedy",
    ]
    assert get_epub_source_tags(epub_path) == [
        "Awkward Protagonist",
        "Character Growth",
    ]


def test_get_epub_genre_tags_falls_back_to_dc_subjects(tmp_path):
    epub_path = tmp_path / "subjects.epub"
    write_minimal_epub(
        epub_path,
        """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Subject Book</dc:title>
    <dc:subject>FanFiction</dc:subject>
    <dc:subject>Adventure</dc:subject>
    <dc:subject>Character Growth</dc:subject>
    <dc:subject>Last Update Year/Month: 2026/04</dc:subject>
    <dc:subject>Completed</dc:subject>
    <dc:subject>Adventure</dc:subject>
    <dc:source>https://www.scribblehub.com/series/123/example/</dc:source>
  </metadata>
  <manifest>
    <item id="chap-1" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap-1"/>
  </spine>
</package>
""",
    )

    assert get_epub_genre_tags(epub_path) == ["FanFiction", "Adventure"]
    assert get_epub_source_tags(epub_path) == ["Character Growth"]
