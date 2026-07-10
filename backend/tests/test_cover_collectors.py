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
