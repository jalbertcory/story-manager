"""Generic cover collector for any story page that advertises a share image.

Most web-novel sites without a dedicated collector still publish their cover as
the page's Open Graph or Twitter card image. This collector is registered last,
so site-specific collectors always win.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..cover_images import fetch_page_direct, fetch_page_via_flaresolverr, save_cover_from_url
from ..fanficfare_config import get_fff_site_config, is_enabled_config_value

logger = logging.getLogger(__name__)

# In order of preference. ``content``/``href`` holds the image address.
SELECTORS: tuple[tuple[str, str], ...] = (
    ('meta[property="og:image:secure_url"]', "content"),
    ('meta[property="og:image"]', "content"),
    ('meta[name="og:image"]', "content"),
    ('meta[name="twitter:image"]', "content"),
    ('meta[property="twitter:image"]', "content"),
    ('meta[name="twitter:image:src"]', "content"),
    ('link[rel="image_src"]', "href"),
)
# Sites that have no per-story art fall back to their own branding.
_BRANDING_HINTS = ("logo", "favicon", "apple-touch-icon", "default", "placeholder", "sprite", "avatar")


def supports(source_url: str) -> bool:
    parsed = urlparse(source_url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def share_image_urls(html: str, page_url: str) -> list[str]:
    """Candidate cover addresses advertised by a page, best first."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for selector, attribute in SELECTORS:
        for element in soup.select(selector):
            value = element.get(attribute)
            if not isinstance(value, str) or not value.strip():
                continue
            url = urljoin(page_url, value.strip())
            name = urlparse(url).path.rsplit("/", 1)[-1].casefold()
            if urlparse(url).scheme not in {"http", "https"} or name.endswith(".svg"):
                continue
            if any(hint in name for hint in _BRANDING_HINTS):
                continue
            if url not in urls:
                urls.append(url)
    return urls


def _fetch_page(source_url: str, site_config: dict[str, str]) -> str:
    if is_enabled_config_value(site_config.get("use_flaresolverr_proxy")):
        return fetch_page_via_flaresolverr(source_url, site_config)
    return fetch_page_direct(source_url)


async def collect(source_url: str, book_id: int) -> Optional[Path]:
    site_config = get_fff_site_config(urlparse(source_url).netloc.casefold())
    loop = asyncio.get_running_loop()
    html = await loop.run_in_executor(None, _fetch_page, source_url, site_config)
    for url in share_image_urls(html, source_url)[:3]:
        cover_path = await save_cover_from_url(url, book_id, referer=source_url, flaresolverr_config=site_config)
        if cover_path is not None:
            logger.info("Collected a cover for book %s from the share image of %s.", book_id, source_url)
            return cover_path
    return None
