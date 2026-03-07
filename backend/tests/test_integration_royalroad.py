"""
Integration test: downloads a real Royal Road story and validates the full pipeline.

Requires:
  - Network access
  - backend/app/personal.ini configured for FanFicFare
  - Run with: pytest -m integration
  (excluded from `make test` by default)
"""

import pytest

from ebooklib import epub as ebooklib_epub

from backend.app.main import _download_and_parse_web_novel
from backend.app import epub_editor

ROYALROAD_URL = "https://www.royalroad.com/fiction/153080/blackflame-mage-litrpg-regressor-isekai"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_royalroad_download_and_validate():
    """
    Downloads Blackflame Mage from Royal Road via FanFicFare and validates that:
    - Metadata is populated (title, author)
    - The EPUB file exists and is non-empty
    - The book has a substantial word count (> 10 000)
    - The book has multiple chapters, each with a title and filename
    - The EPUB can be parsed by ebooklib and has valid DC metadata
    - The title contains "Blackflame" (smoke test against wrong story)
    """
    epub_path, metadata = await _download_and_parse_web_novel(ROYALROAD_URL)

    try:
        # ── Metadata ──────────────────────────────────────────────────────────
        assert metadata["title"], "title should be non-empty"
        assert metadata["author"], "author should be non-empty"
        assert "blackflame" in metadata["title"].lower(), f"Expected 'blackflame' in title, got: {metadata['title']!r}"

        # ── File on disk ──────────────────────────────────────────────────────
        assert epub_path.exists(), f"EPUB not found at {epub_path}"
        assert (
            epub_path.stat().st_size > 100_000
        ), f"EPUB is suspiciously small ({epub_path.stat().st_size} bytes); download may have failed"

        # ── Word count ────────────────────────────────────────────────────────
        word_count = epub_editor.get_word_count(str(epub_path))
        assert word_count > 10_000, (
            f"Expected at least 10 000 words, got {word_count}. " "The download may be incomplete or the wrong story."
        )

        # ── Chapters ──────────────────────────────────────────────────────────
        chapters = epub_editor.get_chapters(str(epub_path))
        assert len(chapters) > 0, "Should have at least one chapter"
        for ch in chapters:
            assert ch["title"], f"Chapter missing title: {ch}"
            assert ch["filename"], f"Chapter missing filename: {ch}"

        # ── ebooklib round-trip ───────────────────────────────────────────────
        book = ebooklib_epub.read_epub(epub_path)
        dc_titles = book.get_metadata("DC", "title")
        assert dc_titles, "EPUB missing DC:title metadata"
        assert dc_titles[0][0], "DC:title should be non-empty"

        dc_creators = book.get_metadata("DC", "creator")
        assert dc_creators, "EPUB missing DC:creator (author) metadata"

    finally:
        epub_path.unlink(missing_ok=True)
