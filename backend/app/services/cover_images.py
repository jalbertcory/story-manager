"""Generic cover image fetching and persistence helpers."""

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests as http_requests
from bs4 import BeautifulSoup

from ..config import LIBRARY_PATH
from .fanficfare_config import is_enabled_config_value

logger = logging.getLogger(__name__)

IMAGE_SIGNATURES = (
    b"\xff\xd8\xff",
    b"\x89PNG\r\n\x1a\n",
    b"GIF87a",
    b"GIF89a",
    b"RIFF",
    b"<svg",
    b"<?xml",
)


def fetch_page_direct(url: str) -> str:
    response = http_requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.text


def request_via_flaresolverr(url: str, site_config: dict[str, str], *, download: bool = False) -> dict[str, Any]:
    proxy_url = (
        f"{site_config.get('flaresolverr_proxy_protocol', 'http')}://"
        f"{site_config.get('flaresolverr_proxy_address', 'localhost')}:"
        f"{site_config.get('flaresolverr_proxy_port', '8191')}/v1"
    )
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": int(site_config.get("flaresolverr_proxy_timeout", "59000")),
    }
    if download:
        payload["download"] = True
    response = http_requests.post(
        proxy_url,
        timeout=70,
        headers={"Content-Type": "application/json"},
        json=payload,
    )
    response.raise_for_status()
    data = response.json()
    solution = data.get("solution") or {}
    if data.get("status") != "ok" or solution.get("status") != 200:
        raise ValueError(data.get("message") or f"FlareSolverr failed with status {solution.get('status')}")
    return solution


def fetch_page_via_flaresolverr(url: str, site_config: dict[str, str]) -> str:
    solution = request_via_flaresolverr(url, site_config)
    return solution.get("response") or ""


def fetch_binary_via_flaresolverr(url: str, site_config: dict[str, str]) -> tuple[str, bytes]:
    solution = request_via_flaresolverr(url, site_config, download=True)
    headers = solution.get("headers") or {}
    content_type = headers.get("content-type") or headers.get("Content-Type") or ""
    response_body = solution.get("response") or ""
    if isinstance(response_body, str):
        try:
            image_bytes = base64.b64decode(response_body, validate=True)
            if looks_like_image(content_type, image_bytes):
                return content_type, image_bytes
        except Exception:
            pass

        response_text = response_body.strip()
        if response_text.startswith("<"):
            context_download = fetch_image_from_flaresolverr_context(url, response_text, solution)
            if context_download:
                return context_download
        return content_type, response_body.encode("utf-8")

    image_bytes = bytes(response_body)
    return content_type, image_bytes


def looks_like_image(content_type: str | None, data: bytes) -> bool:
    stripped = data.lstrip()
    if stripped[:20].lower().startswith((b"<!doctype html", b"<html")):
        return False
    normalized_type = (content_type or "").split(";")[0].strip().casefold()
    if normalized_type.startswith("image/"):
        return True
    return any(stripped.startswith(signature) for signature in IMAGE_SIGNATURES)


def cookie_header_from_solution(solution: dict[str, Any], target_url: str) -> str | None:
    target_host = urlparse(target_url).hostname or ""
    pairs = []
    for cookie in solution.get("cookies") or []:
        domain = (cookie.get("domain") or "").lstrip(".")
        if domain and target_host != domain and not target_host.endswith(f".{domain}"):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if name and value is not None:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs) if pairs else None


def fetch_image_from_flaresolverr_context(
    original_url: str,
    response_text: str,
    solution: dict[str, Any],
) -> tuple[str, bytes] | None:
    soup = BeautifulSoup(response_text, "html.parser")
    image = soup.select_one("img[src]")
    if not image or not image.get("src"):
        return None

    image_url = urljoin(original_url, image["src"])
    headers = {
        "User-Agent": solution.get("userAgent") or "Mozilla/5.0",
        "Referer": original_url,
    }
    cookie_header = cookie_header_from_solution(solution, image_url)
    if cookie_header:
        headers["Cookie"] = cookie_header

    response = http_requests.get(image_url, timeout=30, headers=headers, stream=True)
    response.raise_for_status()
    data = b""
    for chunk in response.iter_content(8192):
        data += chunk
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("Image exceeds 10 MB limit")

    content_type = response.headers.get("Content-Type", "")
    if not looks_like_image(content_type, data):
        return None
    return content_type, data


async def save_cover_from_url(
    url: str,
    book_id: int,
    *,
    referer: str | None = None,
    flaresolverr_config: dict[str, str] | None = None,
) -> Optional[Path]:
    """Downloads an image from a URL and saves it as the book cover. Returns the path or None."""
    covers_path = (LIBRARY_PATH / "covers").resolve()
    covers_path.mkdir(parents=True, exist_ok=True)

    def fetch():
        headers = {"User-Agent": "Mozilla/5.0"}
        if referer:
            headers["Referer"] = referer
        r = http_requests.get(url, timeout=30, headers=headers, stream=True)
        r.raise_for_status()
        data = b""
        for chunk in r.iter_content(8192):
            data += chunk
            if len(data) > 10 * 1024 * 1024:
                raise ValueError("Image exceeds 10 MB limit")
        return r.headers.get("Content-Type", ""), data

    try:
        loop = asyncio.get_running_loop()
        try:
            content_type, image_bytes = await loop.run_in_executor(None, fetch)
        except Exception:
            if not flaresolverr_config or not is_enabled_config_value(flaresolverr_config.get("use_flaresolverr_proxy")):
                raise
            logger.info("Direct cover download failed for %s; retrying through FlareSolverr.", url)
            content_type, image_bytes = await loop.run_in_executor(
                None,
                fetch_binary_via_flaresolverr,
                url,
                flaresolverr_config,
            )
            if len(image_bytes) > 10 * 1024 * 1024:
                raise ValueError("Image exceeds 10 MB limit")
        if not looks_like_image(content_type, image_bytes):
            raise ValueError("Downloaded cover payload was not an image")
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        ext = ext_map.get(content_type.split(";")[0].strip()) or Path(url.split("?")[0]).suffix or ".jpg"
        save_path = covers_path / f"{book_id}{ext}"
        with open(save_path, "wb") as f:
            f.write(image_bytes)
        return save_path
    except Exception as e:
        logger.error(f"Failed to download cover from {url}: {e}")
        return None
