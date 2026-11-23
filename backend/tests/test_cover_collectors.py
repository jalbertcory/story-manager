from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.services.cover_collectors import collect_cover
from backend.app.services.cover_images import looks_like_image, request_remote_cover, validate_remote_cover_url


@pytest.mark.asyncio
async def test_collect_cover_uses_royalroad_collector(mocker):
    fetch_mock = mocker.patch(
        "backend.app.services.cover_collectors.royalroad.fetch_page_direct",
        return_value='<html><div class="cover-art-container"><img class="thumbnail" src="/covers/story.jpg"></div></html>',
    )
    save_mock = mocker.patch(
        "backend.app.services.cover_collectors.royalroad.save_cover_from_url",
        new_callable=AsyncMock,
        return_value=Path("/tmp/royalroad-cover.jpg"),
    )

    cover_path = await collect_cover("https://www.royalroad.com/fiction/123/example", 11)

    assert cover_path == Path("/tmp/royalroad-cover.jpg")
    fetch_mock.assert_called_once_with("https://www.royalroad.com/fiction/123/example")
    save_mock.assert_awaited_once_with(
        "https://www.royalroad.com/covers/story.jpg",
        11,
        referer="https://www.royalroad.com/fiction/123/example",
    )


@pytest.mark.asyncio
async def test_collect_cover_uses_scribblehub_selector_and_direct_fetch(mocker):
    fetch_mock = mocker.patch(
        "backend.app.services.cover_collectors.scribblehub.fetch_page_direct",
        return_value='<html><div class="fic_image"><img src="/covers/story-cover.jpg"></div></html>',
    )
    save_mock = mocker.patch(
        "backend.app.services.cover_collectors.scribblehub.save_cover_from_url",
        new_callable=AsyncMock,
        return_value=Path("/tmp/scribblehub-cover.jpg"),
    )
    mocker.patch("backend.app.services.cover_collectors.scribblehub.get_fff_site_config", return_value={})

    cover_path = await collect_cover("https://www.scribblehub.com/series/123/example/", 42)

    assert cover_path == Path("/tmp/scribblehub-cover.jpg")
    fetch_mock.assert_called_once_with("https://www.scribblehub.com/series/123/example/")
    save_mock.assert_awaited_once_with(
        "https://www.scribblehub.com/covers/story-cover.jpg",
        42,
        referer="https://www.scribblehub.com/series/123/example/",
        flaresolverr_config={},
    )


@pytest.mark.asyncio
async def test_collect_cover_uses_flaresolverr_for_scribblehub_when_configured(tmp_path, mocker):
    site_config = {
        "use_flaresolverr_proxy": "true",
        "flaresolverr_proxy_protocol": "http",
        "flaresolverr_proxy_address": "192.168.1.151",
        "flaresolverr_proxy_port": "8191",
    }
    mocker.patch("backend.app.services.cover_collectors.scribblehub.get_fff_site_config", return_value=site_config)
    mocker.patch("backend.app.services.cover_images.LIBRARY_PATH", tmp_path / "library")
    mocker.patch("backend.app.services.cover_images.validate_remote_cover_url")

    page_response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "status": "ok",
            "solution": {
                "status": 200,
                "response": '<html><div class="fic_image"><img src="https://cdn.example.test/cover.webp"></div></html>',
            },
        },
    )
    image_bytes = b"RIFF\x10\x00\x00\x00WEBPfake"
    image_response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "status": "ok",
            "solution": {
                "status": 200,
                "userAgent": "FlareSolverr Browser",
                "cookies": [{"name": "cf_clearance", "value": "token", "domain": ".example.test"}],
                "response": '<html><body><img src="https://cdn.example.test/cover.webp"></body></html>',
            },
        },
    )

    class ForbiddenResponse:
        def raise_for_status(self):
            raise RuntimeError("403 forbidden")

        def iter_content(self, _chunk_size):
            return iter(())

    class ImageResponse:
        headers = {"Content-Type": "image/webp"}

        def raise_for_status(self):
            return None

        def iter_content(self, _chunk_size):
            return iter([image_bytes])

    post_mock = mocker.patch(
        "backend.app.services.cover_images.http_requests.post",
        side_effect=[page_response, image_response],
    )
    get_mock = mocker.patch(
        "backend.app.services.cover_images.http_requests.get",
        side_effect=[ForbiddenResponse(), ImageResponse()],
    )

    cover_path = await collect_cover("https://www.scribblehub.com/series/123/example/", 7)

    assert cover_path == tmp_path / "library" / "covers" / "7.webp"
    assert cover_path.read_bytes() == image_bytes
    assert get_mock.call_count == 2
    get_mock.assert_any_call(
        "https://cdn.example.test/cover.webp",
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.scribblehub.com/series/123/example/"},
        stream=True,
        allow_redirects=False,
    )
    get_mock.assert_any_call(
        "https://cdn.example.test/cover.webp",
        timeout=30,
        headers={
            "User-Agent": "FlareSolverr Browser",
            "Referer": "https://cdn.example.test/cover.webp",
            "Cookie": "cf_clearance=token",
        },
        stream=True,
        allow_redirects=False,
    )
    assert post_mock.call_count == 2
    post_mock.assert_any_call(
        "http://192.168.1.151:8191/v1",
        timeout=70,
        headers={"Content-Type": "application/json"},
        json={
            "cmd": "request.get",
            "url": "https://www.scribblehub.com/series/123/example/",
            "maxTimeout": 59000,
        },
    )
    post_mock.assert_any_call(
        "http://192.168.1.151:8191/v1",
        timeout=70,
        headers={"Content-Type": "application/json"},
        json={
            "cmd": "request.get",
            "url": "https://cdn.example.test/cover.webp",
            "maxTimeout": 59000,
            "download": True,
        },
    )


def test_remote_cover_url_rejects_loopback():
    with pytest.raises(ValueError, match="private or non-routable"):
        validate_remote_cover_url("http://127.0.0.1/internal-cover.jpg")


def test_remote_cover_url_rejects_credentials():
    with pytest.raises(ValueError, match="credentials"):
        validate_remote_cover_url("https://user:secret@example.com/cover.jpg")


def test_svg_is_not_treated_as_a_cover_image():
    assert looks_like_image("image/svg+xml", b"<svg><script>alert(1)</script></svg>") is False


def test_remote_cover_redirects_are_revalidated(mocker):
    response = SimpleNamespace(
        status_code=302,
        headers={"Location": "http://127.0.0.1/private.jpg"},
        close=mocker.Mock(),
    )
    get_mock = mocker.patch("backend.app.services.cover_images.http_requests.get", return_value=response)
    validate_mock = mocker.patch(
        "backend.app.services.cover_images.validate_remote_cover_url",
        side_effect=[None, ValueError("private destination")],
    )

    with pytest.raises(ValueError, match="private destination"):
        request_remote_cover("https://covers.example.com/cover.jpg", headers={})

    assert validate_mock.call_count == 2
    get_mock.assert_called_once()


@pytest.mark.asyncio
async def test_collect_cover_falls_back_to_share_image_for_other_sites(mocker):
    from backend.app.services.cover_collectors import opengraph

    page = """
    <html><head>
      <meta property="og:image" content="/static/site-logo.png">
      <meta name="twitter:image" content="//cdn.example.test/covers/story.jpg">
      <link rel="image_src" href="https://cdn.example.test/covers/vector.svg">
    </head></html>
    """
    assert opengraph.share_image_urls(page, "https://novels.example.test/story/9") == [
        "https://cdn.example.test/covers/story.jpg"
    ]

    mocker.patch("backend.app.services.cover_collectors.opengraph.get_fff_site_config", return_value={})
    fetch_mock = mocker.patch("backend.app.services.cover_collectors.opengraph.fetch_page_direct", return_value=page)
    save_mock = mocker.patch(
        "backend.app.services.cover_collectors.opengraph.save_cover_from_url",
        new_callable=AsyncMock,
        return_value=Path("/tmp/share-cover.jpg"),
    )

    cover_path = await collect_cover("https://novels.example.test/story/9", 5)

    assert cover_path == Path("/tmp/share-cover.jpg")
    fetch_mock.assert_called_once_with("https://novels.example.test/story/9")
    save_mock.assert_awaited_once_with(
        "https://cdn.example.test/covers/story.jpg",
        5,
        referer="https://novels.example.test/story/9",
        flaresolverr_config={},
    )


@pytest.mark.asyncio
async def test_share_image_is_tried_when_the_site_collector_finds_nothing(mocker):
    mocker.patch(
        "backend.app.services.cover_collectors.royalroad.fetch_page_direct",
        return_value="<html><p>No cover here</p></html>",
    )
    mocker.patch("backend.app.services.cover_collectors.opengraph.get_fff_site_config", return_value={})
    mocker.patch(
        "backend.app.services.cover_collectors.opengraph.fetch_page_direct",
        return_value='<meta property="og:image" content="https://cdn.example.test/rr.jpg">',
    )
    save_mock = mocker.patch(
        "backend.app.services.cover_collectors.opengraph.save_cover_from_url",
        new_callable=AsyncMock,
        return_value=Path("/tmp/rr.jpg"),
    )

    assert await collect_cover("https://www.royalroad.com/fiction/1/x", 3) == Path("/tmp/rr.jpg")
    save_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_collect_cover_ignores_non_web_sources():
    assert await collect_cover("file:///library/book.epub", 1) is None


def test_metadata_cover_urls_prefer_stored_cover_then_open_library():
    from backend.app import models
    from backend.app.services.cover_processing import metadata_cover_urls

    book = models.Book(
        id=4,
        metadata_details={"cover_url": " https://books.example.test/cover.jpg "},
        metadata_remote_ids={
            "isbn_13": "978-0-441-01359-3",
            "open_library_edition_key": "/books/OL123M",
            "custom": {"nested": True},
        },
    )

    assert metadata_cover_urls(book) == [
        "https://books.example.test/cover.jpg",
        "https://covers.openlibrary.org/b/isbn/9780441013593-L.jpg?default=false",
        "https://covers.openlibrary.org/b/olid/OL123M-L.jpg?default=false",
    ]
    assert metadata_cover_urls(models.Book(id=5, metadata_details={"cover_url": "javascript:alert(1)"})) == []


@pytest.mark.asyncio
async def test_reextract_cover_falls_back_to_matched_metadata(tmp_path, mocker):
    from backend.app import models
    from backend.app.services import cover_processing

    library = tmp_path / "library"
    saved = library / "covers" / "8.jpg"
    mocker.patch("backend.app.services.cover_processing.LIBRARY_PATH", library)
    mocker.patch("backend.app.services.cover_processing.get_and_save_epub_cover", return_value=None)
    collect_mock = mocker.patch(
        "backend.app.services.cover_processing.collect_cover", new_callable=AsyncMock, return_value=None
    )
    save_mock = mocker.patch(
        "backend.app.services.cover_processing.save_cover_from_url", new_callable=AsyncMock, side_effect=[None, saved]
    )
    book = models.Book(
        id=8,
        immutable_path="library/book.epub",
        source_url="https://novels.example.test/story/8",
        metadata_details={"cover_url": "https://books.example.test/gone.jpg"},
        metadata_remote_ids={"isbn_10": "0441013597"},
    )
    db = mocker.Mock(commit=AsyncMock())

    await cover_processing.reextract_book_cover(book, db)

    collect_mock.assert_awaited_once_with("https://novels.example.test/story/8", 8)
    assert [call.args[0] for call in save_mock.await_args_list] == [
        "https://books.example.test/gone.jpg",
        "https://covers.openlibrary.org/b/isbn/0441013597-L.jpg?default=false",
    ]
    assert book.cover_path == "library/covers/8.jpg"
    db.commit.assert_awaited_once()
