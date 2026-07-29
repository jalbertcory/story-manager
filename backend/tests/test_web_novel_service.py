import zipfile
from pathlib import Path

import pytest
from ebooklib import epub
from lxml import etree

from backend.app.services import fanficfare_config, web_novel


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


def test_build_lossless_chapter_merge_preserves_stubbed_chapters_and_appends_new_ones():
    existing_urls = [f"https://example.com/chapter/{chapter}" for chapter in range(1, 7)]
    existing_data = {url: {"chapterorigtitle": f"Chapter {index}"} for index, url in enumerate(existing_urls, start=1)}
    remote_chapters = [
        {"title": f"Chapter {chapter}", "url": f"https://example.com/chapter/{chapter}"} for chapter in (1, 2, 5, 6, 7)
    ]

    merge = web_novel._build_lossless_chapter_merge(
        existing_urls=existing_urls,
        existing_data=existing_data,
        remote_chapters=remote_chapters,
        normalize_url=lambda url: url,
    )

    assert [chapter["url"] for chapter in merge.chapters] == [
        f"https://example.com/chapter/{chapter}" for chapter in range(1, 8)
    ]
    assert len(merge.historical_ids) == 2
    assert len(merge.new_ids) == 1


def test_build_lossless_chapter_merge_refuses_unrelated_source():
    with pytest.raises(web_novel.LosslessChapterUpdateError, match="no chapters in common"):
        web_novel._build_lossless_chapter_merge(
            existing_urls=["https://example.com/chapter/1"],
            existing_data={},
            remote_chapters=[{"title": "Other", "url": "https://other.example/chapter/2"}],
            normalize_url=lambda url: url,
        )


def test_realign_adapter_chapter_index_after_historical_insert():
    class IndexedAdapter:
        def __init__(self):
            self.chapterUrls = [
                {"url": "https://example.com/chapter/1"},
                {"url": "https://example.com/chapter/3"},
            ]
            self.chapterURLIndex = {"1": 0, "3": 1}

        def normalize_chapterurl(self, url):
            chapter_id = url.rsplit("/", 1)[-1]
            index = self.chapterURLIndex.get(chapter_id)
            return self.chapterUrls[index]["url"] if index is not None else url

    adapter = IndexedAdapter()
    remote = list(adapter.chapterUrls)
    merged = [
        remote[0],
        {"url": "https://example.com/chapter/2"},
        remote[1],
    ]

    web_novel._realign_adapter_chapter_index(adapter, remote, merged)

    assert adapter.chapterURLIndex == {"1": 0, "3": 2}


@pytest.mark.asyncio
async def test_download_web_novel_existing_epub_uses_lossless_updater_and_user_config(tmp_path, monkeypatch, mocker):
    library_path = tmp_path / "library"
    library_path.mkdir()
    monkeypatch.setattr(web_novel, "LIBRARY_PATH", library_path)

    user_ini = tmp_path / "user-personal.ini"
    user_ini.write_text("[defaults]\nslow_down_sleep_time: 1\n", encoding="utf-8")
    monkeypatch.setenv("FFF_USER_CONFIG_PATH", str(user_ini))

    existing_epub = library_path / "existing.epub"
    create_dummy_epub(existing_epub, "Before", "Author")
    set_dc_source(existing_epub, "https://www.royalroadcdn.com/public/covers-large/33600-stray-cat-strut.jpg?time=1666088451")

    captured_update = {}
    repaired_source = {}

    def fake_lossless_update(source_url, epub_path, config_paths, overwrite):
        captured_update["source_url"] = source_url
        captured_update["epub_path"] = epub_path
        captured_update["config_paths"] = list(config_paths)
        captured_update["overwrite"] = overwrite
        repaired_source["value"] = web_novel._get_epub_source_url(existing_epub)
        create_dummy_epub(existing_epub, "After", "Updated Author")
        return web_novel._LosslessUpdateResult(
            changed=True,
            preserved_chapter_count=0,
            new_chapter_count=1,
        )

    mocker.patch("backend.app.services.web_novel._run_fff_lossless_update", side_effect=fake_lossless_update)
    normalize_mock = mocker.patch("backend.app.services.web_novel.normalize_epub_prose_blocks")

    result = await web_novel.download_web_novel(
        "https://example.com/story/1",
        existing_epub_path=existing_epub,
    )

    assert result is not None
    epub_path, metadata = result
    assert epub_path == existing_epub
    assert metadata == {"title": "After", "author": "Updated Author", "series": None}

    assert captured_update == {
        "source_url": "https://example.com/story/1",
        "epub_path": existing_epub.resolve(),
        "config_paths": [fanficfare_config.APP_DIR / "personal.ini", user_ini],
        "overwrite": False,
    }
    assert repaired_source["value"] == "https://example.com/story/1"
    normalize_mock.assert_called_once_with(existing_epub)


@pytest.mark.asyncio
async def test_download_web_novel_unchanged_lossless_update_returns_none(tmp_path, monkeypatch, mocker):
    library_path = tmp_path / "library"
    library_path.mkdir()
    monkeypatch.setattr(web_novel, "LIBRARY_PATH", library_path)
    monkeypatch.delenv("FFF_USER_CONFIG_PATH", raising=False)

    existing_epub = library_path / "existing.epub"
    create_dummy_epub(existing_epub, "Before", "Author")
    set_dc_source(existing_epub, "https://example.com/story/1")

    mocker.patch(
        "backend.app.services.web_novel._run_fff_lossless_update",
        return_value=web_novel._LosslessUpdateResult(
            changed=False,
            preserved_chapter_count=3,
            new_chapter_count=0,
        ),
    )
    normalize_mock = mocker.patch("backend.app.services.web_novel.normalize_epub_prose_blocks")

    result = await web_novel.download_web_novel(
        "https://example.com/story/1",
        existing_epub_path=existing_epub,
    )

    assert result is None
    normalize_mock.assert_not_called()


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
    normalize_mock = mocker.patch("backend.app.services.web_novel.normalize_epub_prose_blocks")

    result = await web_novel.download_web_novel("https://www.royalroad.com/fiction/123")

    assert result is not None
    epub_path, metadata = result
    assert epub_path == expected_output
    assert metadata == {"title": "Fresh Title", "author": "Fresh Author", "series": None}

    args = captured_args["args"]
    output_arg = f"output_filename={library_path.resolve()}/${{title}}-${{siteabbrev}}_${{storyId}}${{formatext}}"
    assert output_arg in args
    assert "https://www.royalroad.com/fiction/123" == args[-1]
    normalize_mock.assert_called_once_with(expected_output)


def test_get_fff_config_paths_prefers_local_repo_override(tmp_path, monkeypatch):
    app_dir = tmp_path / "backend" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "personal.ini").write_text("[defaults]\nwrite_raw_metadata: true\n", encoding="utf-8")

    local_user_ini = tmp_path / "config" / "fanficfare" / "personal.ini"
    local_user_ini.parent.mkdir(parents=True)
    local_user_ini.write_text("[defaults]\nslow_down_sleep_time: 1\n", encoding="utf-8")

    monkeypatch.setattr(fanficfare_config, "APP_DIR", app_dir)
    monkeypatch.setattr(
        fanficfare_config,
        "_DEFAULT_USER_PERSONAL_INI_CANDIDATES",
        (
            local_user_ini,
            tmp_path / "missing-docker-path.ini",
        ),
    )
    monkeypatch.delenv("FFF_USER_CONFIG_PATH", raising=False)

    config_paths = fanficfare_config.get_fff_config_paths()

    assert config_paths == [app_dir / "personal.ini", local_user_ini]
