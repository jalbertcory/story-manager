"""Exercise the proxy JSON boundary before values reach HTTP/image handling."""

import base64
from types import SimpleNamespace

import pytest

from backend.app.services import cover_images


@pytest.fixture
def proxy(mocker):
    mocker.patch.object(cover_images, "validate_remote_cover_url")
    post = mocker.patch.object(cover_images.http_requests, "post")

    def respond(solution):
        post.return_value = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"status": "ok", "solution": solution})

    return respond


@pytest.mark.parametrize(
    "field,value",
    [
        ("headers", {"Content-Type": []}),
        ("headers", []),
        ("cookies", [{"name": "token", "value": {}}]),
        ("cookies", [{"name": "token", "value": "x", "domain": 3}]),
        ("cookies", [None]),
        ("response", {}),
        ("response", [256]),
        ("response", [True]),
        ("userAgent", []),
        ("status", "200"),
    ],
)
def test_rejects_malformed_proxy_fields(proxy, field, value):
    proxy({"status": 200, field: value})
    with pytest.raises(ValueError):
        cover_images.request_via_flaresolverr("https://example.com", {})


@pytest.mark.parametrize("encode", [lambda data: base64.b64encode(data).decode(), list])
def test_download_supports_base64_and_compatible_byte_arrays(proxy, encode):
    image = b"RIFF\x10\x00\x00\x00WEBPfake"
    proxy({"status": 200, "response": encode(image), "headers": {"Content-Type": "image/webp"}})
    assert cover_images.fetch_binary_via_flaresolverr("https://example.com", {}) == ("image/webp", image)


def test_cookie_domains_and_empty_values_preserve_browser_context(proxy):
    proxy(
        {
            "status": 200,
            "cookies": [
                {"name": "token", "value": "", "domain": ".example.com"},
                {"name": "unrelated", "value": "secret", "domain": "another.example"},
            ],
        }
    )
    solution = cover_images.request_via_flaresolverr("https://example.com", {})
    assert cover_images.cookie_header_from_solution(solution, "https://cdn.example.com/image") == "token="


def test_proxy_failure_reports_message(mocker):
    mocker.patch.object(cover_images, "validate_remote_cover_url")
    mocker.patch.object(
        cover_images.http_requests,
        "post",
        return_value=SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"status": "error", "message": "Challenge timed out"}
        ),
    )
    with pytest.raises(ValueError, match="Challenge timed out"):
        cover_images.fetch_page_via_flaresolverr("https://example.com", {})
