"""Opt-in live smoke test; only three public chapter bodies are downloaded.

RUN_ROYALROAD_LIVE_TEST=1 .venv/bin/python -m pytest -m integration \
    backend/tests/test_royalroad_anubis_live.py

The chapter list is deliberately limited to simulate a new chapter and a stub.
HTTP, challenge handling, metadata parsing, chapter bodies, and EPUB writing are
real. Files stay in pytest's temporary directory; the user's library is untouched.
"""

import os
from urllib.parse import urlsplit

import pytest
from fanficfare.adapters.adapter_royalroadcom import RoyalRoadAdapter
from fanficfare.epubutils import get_update_data

from backend.app.services import royalroad_anubis as anubis, web_novel


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_ROYALROAD_LIVE_TEST") != "1", reason="Live Royal Road test is opt-in")
def test_live_challenged_download_and_lossless_update(tmp_path, monkeypatch):
    source = "https://www.royalroad.com/fiction/74983"
    ini = tmp_path / "live.ini"
    ini.write_text(
        "[defaults]\ninclude_images:false\nuse_flaresolverr_proxy:true\n"
        "[www.royalroad.com]\nusername:\npassword:\nslow_down_sleep_time:1\nconnect_timeout:30\n"
    )
    browser_url = os.getenv("ROYALROAD_FLARESOLVERR_URL")
    if browser_url:
        parsed = urlsplit(browser_url)
        assert parsed.scheme in {"http", "https"} and parsed.hostname
        with ini.open("a") as config:
            config.write(
                f"flaresolverr_proxy_protocol:{parsed.scheme}\n"
                f"flaresolverr_proxy_address:{parsed.hostname}\n"
                f"flaresolverr_proxy_port:{parsed.port or (443 if parsed.scheme == 'https' else 80)}\n"
            )
    path = tmp_path / "live.epub"
    selected = [0, 1]
    extract = RoyalRoadAdapter.extractChapterUrlsAndMetadata

    def limited_metadata(adapter):
        extract(adapter)
        remote = adapter.chapterUrls
        assert len(remote) >= 3
        kept = [remote[index] for index in selected]
        old_index = adapter.chapterURLIndex
        adapter.chapterURLIndex = {key: selected.index(index) for key, index in old_index.items() if index in selected}
        adapter.chapterUrls = kept
        adapter.story.setMetadata("numChapters", len(kept))

    monkeypatch.setattr(RoyalRoadAdapter, "extractChapterUrlsAndMetadata", limited_metadata)
    anubis._auth_cookies.clear()
    try:
        assert web_novel._run_fff_main(["-c", str(ini), "--non-interactive", "-o", f"output_filename={path}", source]) == 0
        original = get_update_data(path)[7]
        assert len(original) == 2
        assert all(chapter.get_text().strip() for chapter in original.values())
        selected[:] = [0, 2]  # Simulate chapter 2 removed and chapter 3 newly published.
        result = web_novel._run_fff_lossless_update(source, path, [ini], False)
        updated = get_update_data(path)[7]
        assert result == web_novel._LosslessUpdateResult(True, 1, 1)
        assert len(updated) == 3
        assert list(updated)[:2] == list(original)
        for url, chapter in original.items():
            assert updated[url].get_text() == chapter.get_text()
        assert list(updated.values())[-1].get_text().strip()
    finally:
        anubis._auth_cookies.clear()
