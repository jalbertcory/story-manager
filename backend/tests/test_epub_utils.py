import zipfile
from pathlib import Path

from backend.app.services.epub_utils import get_and_save_epub_cover, get_epub_genre_tags, get_epub_source_tags


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
