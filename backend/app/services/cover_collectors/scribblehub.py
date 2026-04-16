"""ScribbleHub cover collector."""

import asyncio
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..cover_images import fetch_page_direct, fetch_page_via_flaresolverr, save_cover_from_url
from ..fanficfare_config import get_fff_site_config, is_enabled_config_value

logger = logging.getLogger(__name__)

DOMAIN = "www.scribblehub.com"
DOMAINS = {DOMAIN, "scribblehub.com"}
SELECTOR = ".fic_image img"


def supports(source_url: str) -> bool:
    return urlparse(source_url).netloc.casefold() in DOMAINS


def _fetch_page(source_url: str, site_config: dict[str, str]) -> str:
    if is_enabled_config_value(site_config.get("use_flaresolverr_proxy")):
        logger.info("Fetching ScribbleHub cover page through FlareSolverr proxy.")
        return fetch_page_via_flaresolverr(source_url, site_config)

    logger.info("Fetching ScribbleHub cover page directly; FlareSolverr is not enabled in FanFicFare config.")
    return fetch_page_direct(source_url)


async def collect(source_url: str, book_id: int) -> Optional[Path]:
    site_config = get_fff_site_config(DOMAIN)
    loop = asyncio.get_running_loop()
    html = await loop.run_in_executor(None, _fetch_page, source_url, site_config)
    soup = BeautifulSoup(html, "html.parser")
    img = soup.select_one(SELECTOR)
    if not img or not img.get("src"):
        return None
    return await save_cover_from_url(
        urljoin(source_url, img["src"]),
        book_id,
        referer=source_url,
        flaresolverr_config=site_config,
    )
