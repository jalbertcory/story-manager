"""Registered source-site cover collectors."""

import logging
from pathlib import Path
from typing import Optional

from . import royalroad, scribblehub

logger = logging.getLogger(__name__)

COLLECTORS = (
    royalroad,
    scribblehub,
)


async def collect_cover(source_url: str, book_id: int) -> Optional[Path]:
    """Collect a cover from the first registered source-site collector that supports the URL."""
    for collector in COLLECTORS:
        if not collector.supports(source_url):
            continue
        try:
            return await collector.collect(source_url, book_id)
        except Exception as e:
            logger.error("Failed to collect cover from %s with %s: %s", source_url, collector.__name__, e)
            continue
    return None
