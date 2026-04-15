import zipfile
from pathlib import Path

import pytest
from ebooklib import epub
from lxml import etree

from backend.app.services import web_novel


def create_dummy_epub(filepath: Path, title: str, author: str):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    book = epub.EpubBook()
    book.set_identifier("test-id")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)

    chapter = epub.EpubHtml(title="Chapter 1", file_name="chap_1.xhtml", lang="en")
    chapter.content = "<h1>Chapter 1</h1><p>Hello world</p>"
    book.add_item(chapter)
    book.spine = ["nav", chapter]
    book.toc = (chapter,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(filepath), book, {})


def set_dc_source(filepath: Path, source_url: str):
    with zipfile.ZipFile(filepath) as archive:
        container = etree.fromstring(archive.read("META-INF/container.xml"))
        rootfile_path = container.xpath(
            "/u:container/u:rootfiles/u:rootfile",
            namespaces={"u": "urn:oasis:names:tc:opendocument:xmlns:container"},
        )[0].get("full-path")
        package = etree.fromstring(archive.read(rootfile_path))
        package_bytes_by_name = {info.filename: archive.read(info.filename) for info in archive.infolist()}
        infos = archive.infolist()

    metadata = package.xpath(
        "/opf:package/opf:metadata",
        namespaces={"opf": "http://www.idpf.org/2007/opf"},
    )[0]
    source_nodes = package.xpath(
        "/opf:package/opf:metadata/dc:source",
        namespaces={
            "opf": "http://www.idpf.org/2007/opf",
            "dc": "http://purl.org/dc/elements/1.1/",
        },
    )
    if source_nodes:
        source_node = source_nodes[0]
    else:
        source_node = etree.SubElement(metadata, "{http://purl.org/dc/elements/1.1/}source")
    source_node.text = source_url
    package_bytes_by_name[rootfile_path] = etree.tostring(package, encoding="utf-8", xml_declaration=True)

    temp_path = filepath.with_suffix(".tmp.epub")
    with zipfile.ZipFile(temp_path, "w") as archive:
        for info in infos:
            archive.writestr(info, package_bytes_by_name[info.filename])
    temp_path.replace(filepath)


@pytest.mark.asyncio
async def test_download_web_novel_existing_epub_uses_update_mode_and_user_config(tmp_path, monkeypatch, mocker):
    library_path = tmp_path / "library"
    library_path.mkdir()
    monkeypatch.setattr(web_novel, "LIBRARY_PATH", library_path)

    user_ini = tmp_path / "user-personal.ini"
    user_ini.write_text("[defaults]\nslow_down_sleep_time: 1\n", encoding="utf-8")
    monkeypatch.setenv("FFF_USER_CONFIG_PATH", str(user_ini))

    existing_epub = library_path / "existing.epub"
    create_dummy_epub(existing_epub, "Before", "Author")
    set_dc_source(existing_epub, "https://www.royalroadcdn.com/public/covers-large/33600-stray-cat-strut.jpg?time=1666088451")

    captured_args = {}
    repaired_source = {}

    def fake_fff_main(args):
        captured_args["args"] = list(args)
        repaired_source["value"] = web_novel._get_epub_source_url(existing_epub)
        create_dummy_epub(existing_epub, "After", "Updated Author")
        return 0

    mocker.patch("backend.app.services.web_novel._run_fff_main", side_effect=fake_fff_main)

    result = await web_novel.download_web_novel(
        "https://example.com/story/1",
        existing_epub_path=existing_epub,
    )

    assert result is not None
    epub_path, metadata = result
    assert epub_path == existing_epub
    assert metadata == {"title": "After", "author": "Updated Author", "series": None}

    args = captured_args["args"]
    assert args.count("-c") == 2
    assert str(web_novel.APP_DIR / "personal.ini") in args
    assert str(user_ini) in args
    assert "-u" in args
    assert "-U" not in args
    assert str(existing_epub) == args[-1]
    assert repaired_source["value"] == "https://example.com/story/1"


@pytest.mark.asyncio
async def test_download_web_novel_new_download_uses_story_manager_output_path(tmp_path, monkeypatch, mocker):
    library_path = tmp_path / "library"
    library_path.mkdir()
    monkeypatch.setattr(web_novel, "LIBRARY_PATH", library_path)
    monkeypatch.delenv("FFF_USER_CONFIG_PATH", raising=False)

    expected_output = library_path / "Fresh Title-rr_123.epub"
    captured_args = {}

    def fake_fff_main(args):
        captured_args["args"] = list(args)
        create_dummy_epub(expected_output, "Fresh Title", "Fresh Author")
        return 0

    mocker.patch("backend.app.services.web_novel._run_fff_main", side_effect=fake_fff_main)

    result = await web_novel.download_web_novel("https://www.royalroad.com/fiction/123")

    assert result is not None
    epub_path, metadata = result
    assert epub_path == expected_output
    assert metadata == {"title": "Fresh Title", "author": "Fresh Author", "series": None}

    args = captured_args["args"]
    output_arg = f"output_filename={library_path.resolve()}/${{title}}-${{siteabbrev}}_${{storyId}}${{formatext}}"
    assert output_arg in args
    assert "https://www.royalroad.com/fiction/123" == args[-1]
