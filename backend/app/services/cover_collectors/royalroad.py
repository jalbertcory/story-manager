"""RoyalRoad cover collector."""

import asyncio
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..cover_images import fetch_page_direct, save_cover_from_url

DOMAINS = {"www.royalroad.com", "royalroad.com"}
SELECTOR = "div.cover-art-container img.thumbnail"


def supports(source_url: str) -> bool:
    return urlparse(source_url).netloc.casefold() in DOMAINS


async def collect(source_url: str, book_id: int) -> Optional[Path]:
    loop = asyncio.get_running_loop()
    html = await loop.run_in_executor(None, fetch_page_direct, source_url)
    soup = BeautifulSoup(html, "html.parser")
    img = soup.select_one(SELECTOR)
    if not img or not img.get("src"):
        return None
    return await save_cover_from_url(urljoin(source_url, img["src"]), book_id, referer=source_url)
