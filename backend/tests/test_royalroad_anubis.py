"""Exercise the real FFF adapter/writer with a simulated Royal Road transport."""

import hashlib
import json
from email.message import Message
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from argon2.low_level import Type, hash_secret_raw
from fanficfare import cli
from fanficfare.epubutils import get_update_data

from backend.app.services import royalroad_anubis as anubis, web_novel

STORY = "https://www.royalroad.com/fiction/123"
CHALLENGE_ID = "01a17a83-4622-7b35-baef-0c2c41931e93"
RANDOM_DATA = "abcdef0123456789" * 8
AUTH = "techaro.lol-anubis-auth-test"
CLOUDFLARE = '<title>Just a moment...</title><script src="/cdn-cgi/challenge-platform/check.js"></script>'


def challenge_html(algorithm="fast", difficulty=2, extensions=None):
    data = {
        "rules": {"algorithm": algorithm, "difficulty": difficulty, "extensions": extensions or []},
        "challenge": {"id": CHALLENGE_ID, "randomData": RANDOM_DATA},
    }
    return '<title>Making sure you\'re not a bot!</title><script id="anubis_challenge">' + json.dumps(data) + "</script>"


def response_for(request, body, status=200, cookie=None):
    result = requests.Response()
    result.request = request
    result.url = request.url
    result.status_code = status
    result._content = body.encode()
    result._content_consumed = True
    result.headers["Content-Type"] = "text/html"
    headers = Message()
    if cookie:
        headers.add_header("Set-Cookie", cookie + "; Path=/; Secure; Max-Age=3600")
    # Exercise Requests' normal cookie extraction, including verification cookies
    # on the challenge/CSS responses and auth cookies on the pass response.
    result.raw = SimpleNamespace(_original_response=SimpleNamespace(msg=headers), release_conn=lambda: None)
    requests.cookies.extract_cookies_to_jar(result.cookies, request, result.raw)
    return result


def story_html(chapters):
    metadata = {
        "name": "Preservation test",
        "author": {"name": "Author", "url": "https://www.royalroad.com/profile/1"},
        "description": "Test description",
        "datePublished": "2026-10-01T12:00:00",
        "dateModified": "2026-10-28T12:00:00",
    }
    chapter_data = [
        {
            "id": chapter,
            "title": f"Chapter {chapter}",
            "date": "2026-10-28T12:00:00",
            "isUnlocked": True,
            "url": f"/fiction/123/test/chapter/{chapter}/chapter-{chapter}",
        }
        for chapter in chapters
    ]
    return (
        '<a href="/home/reverttolegacyui">Legacy</a>'
        f'<script type="application/ld+json">{json.dumps(metadata)}</script>'
        f"<script>\nwindow.chapters = {json.dumps(chapter_data)};\n</script>"
        '<meta property="books:rating:value" content="5"/><div id="chapterHeroData"></div>'
    )


class RoyalRoadServer:
    def __init__(self):
        self.chapters = [1, 2, 3]
        self.generation = 1
        self.pass_count = 0
        self.requests = []
        self.block = None
        self.expire_on_chapter = None
        self.cloudflare = False
        self.browser_failure = None
        self.browser_calls = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        if urlsplit(request.url).hostname == "localhost":
            assert request.url == "http://localhost:8191/v1" and request.method == "POST"
            payload = json.loads(request.body)
            assert payload["cmd"] == "request.get" and 0 < payload["maxTimeout"] <= 60000
            assert "cookies" not in payload and "session" not in payload
            self.browser_calls.append(payload["url"])
            if self.browser_failure == "timeout":
                raise requests.Timeout("Browser timed out")
            body = self.content(urlsplit(payload["url"]).path)
            failure = self.browser_failure
            if failure == "challenge":
                body = CLOUDFLARE
            if failure == "anubis":
                body = challenge_html()
            if failure == "empty":
                body = ""
            return response_for(
                request,
                json.dumps(
                    {
                        "status": "error" if failure == "error" else "ok",
                        "solution": {
                            "status": 403 if failure == "status" else 200,
                            "url": "https://example.com/" if failure == "redirect" else payload["url"],
                            "response": body,
                        },
                    }
                ),
            )
        assert urlsplit(request.url).hostname == "www.royalroad.com", "Unexpected network access, including FlareSolverr"
        path = urlsplit(request.url).path
        if self.cloudflare:
            return response_for(request, CLOUDFLARE, status=403)
        if path.endswith("/css-load/" + CHALLENGE_ID):
            assert "verification=present" in request.headers.get("Cookie", "")
            return response_for(request, "", cookie="css=loaded")
        if path.endswith("/pass-challenge"):
            assert "css=loaded" in request.headers.get("Cookie", "")
            params = parse_qs(urlsplit(request.url).query)
            digest = hashlib.sha256((RANDOM_DATA + params["nonce"][0]).encode()).hexdigest()
            assert digest == params["response"][0] and digest.startswith("00")
            assert params["id"] == [CHALLENGE_ID]
            assert params["redir"][0].startswith(STORY)
            self.pass_count += 1
            return response_for(request, "cleared", cookie=f"{AUTH}={self.generation}")
        if self.expire_on_chapter and f"/chapter/{self.expire_on_chapter}/" in path:
            self.generation += 1
            self.expire_on_chapter = None
        if self.block == "reject" or f"{AUTH}={self.generation}" not in request.headers.get("Cookie", ""):
            body = challenge_html(algorithm="unknown" if self.block == "unknown" else "fast", extensions=["css-load"])
            return response_for(request, body, status=403, cookie="verification=present")
        return response_for(request, self.content(path))

    def content(self, path):
        if path == "/fiction/123":
            return story_html(self.chapters)
        chapter = int(path.split("/chapter/")[1].split("/")[0])
        assert chapter in self.chapters, "Attempted to fetch a removed chapter"
        return f'<div class="chapter-inner chapter-content"><p>Saved prose {chapter}.</p></div>'


@pytest.fixture
def server(monkeypatch):
    anubis._auth_cookies.clear()
    server = RoyalRoadServer()
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", lambda adapter, request, **kw: server.send(request, **kw))
    yield server
    anubis._auth_cookies.clear()


@pytest.fixture
def ini(tmp_path):
    path = tmp_path / "personal.ini"
    path.write_text(
        "[defaults]\nuse_flaresolverr_proxy:true\nuse_browser_cache:true\n"
        "continue_on_chapter_error:true\ninclude_images:false\nslow_down_sleep_time:0\n"
        "[www.royalroad.com]\nslow_down_sleep_time:0\nuser_agent:Preservation-test/1\n"
    )
    return path


def download(path, ini):
    assert web_novel._run_fff_main(["-c", str(ini), "--non-interactive", "-o", f"output_filename={path}", STORY]) == 0
    assert path.is_file()


@pytest.mark.parametrize("overwrite", [False, True])
def test_real_fff_update_preserves_removed_chapter_and_appends_new_chapter(tmp_path, server, ini, overwrite):
    path = tmp_path / "story.epub"
    download(path, ini)
    original = get_update_data(path)[7]
    assert len(original) == 3
    assert server.pass_count == 1
    server.requests.clear()
    server.chapters = [1, 3, 4]  # Chapter 2 is now stubbed/removed from Royal Road.
    server.expire_on_chapter = 4  # Re-challenge halfway through the update.

    result = web_novel._run_fff_lossless_update(STORY, path, [ini], overwrite)

    updated = get_update_data(path)[7]
    assert result == web_novel._LosslessUpdateResult(True, 1, 1)
    assert len(updated) == 4
    assert list(updated) == [f"https://www.royalroad.com/fiction/123/test/chapter/{n}/chapter-{n}" for n in (1, 2, 3, 4)]
    for url, chapter in original.items():
        assert updated[url].get_text() == chapter.get_text()
    assert "Saved prose 4." in list(updated.values())[-1].get_text()
    assert server.pass_count == 2
    assert not any("/chapter/2/" in request.url for request in server.requests)
    assert {request.headers["User-Agent"] for request in server.requests} == {"Preservation-test/1"}
    assert not list(tmp_path.glob(".*.update-*.epub"))


def test_no_new_chapters_keeps_epub_byte_identical_and_reuses_clearance(tmp_path, server, ini):
    path = tmp_path / "story.epub"
    download(path, ini)
    before = path.read_bytes()
    server.chapters = [1, 3]
    result = web_novel._run_fff_lossless_update(STORY, path, [ini], False)
    assert not result.changed
    assert result.preserved_chapter_count == 1
    assert path.read_bytes() == before
    assert server.pass_count == 1


def test_cloudflare_fallback_download_and_lossless_update(tmp_path, server, ini):
    server.cloudflare = True
    path = tmp_path / "story.epub"
    download(path, ini)
    original = get_update_data(path)[7]
    server.chapters = [1, 3, 4]
    server.browser_calls.clear()
    result = web_novel._run_fff_lossless_update(STORY, path, [ini], False)
    updated = get_update_data(path)[7]
    assert result == web_novel._LosslessUpdateResult(True, 1, 1)
    assert len(updated) == 4
    assert list(updated)[:3] == list(original)
    for url, chapter in original.items():
        assert updated[url].get_text() == chapter.get_text()
    assert "Saved prose 4." in list(updated.values())[-1].get_text()
    assert server.browser_calls == [STORY, list(updated)[-1]]
    assert server.pass_count == 0


@pytest.mark.parametrize("failure", ["timeout", "error", "status", "redirect", "empty", "challenge", "anubis"])
@pytest.mark.parametrize("at_chapter", [False, True])
def test_browser_failure_preserves_epub(tmp_path, server, ini, monkeypatch, failure, at_chapter):
    path = tmp_path / "story.epub"
    download(path, ini)
    before = path.read_bytes()
    server.chapters = [1, 3, 4]
    server.browser_failure = failure
    if at_chapter:
        send = server.send

        def challenge_new_chapter(request, **kwargs):
            if "/chapter/4/" in request.url:
                server.cloudflare = True
            return send(request, **kwargs)

        monkeypatch.setattr(server, "send", challenge_new_chapter)
    else:
        server.cloudflare = True
    with pytest.raises(anubis.RoyalRoadChallengeError):
        web_novel._run_fff_lossless_update(STORY, path, [ini], False)
    assert path.read_bytes() == before
    assert len(server.browser_calls) == 1
    assert not list(tmp_path.glob(".*.update-*.epub"))


def test_cloudflare_without_configured_browser_keeps_epub(tmp_path, server, ini):
    path = tmp_path / "story.epub"
    download(path, ini)
    before = path.read_bytes()
    ini.write_text(ini.read_text().replace("use_flaresolverr_proxy:true", "use_flaresolverr_proxy:false"))
    server.cloudflare = True
    with pytest.raises(anubis.RoyalRoadChallengeError, match="Configure use_flaresolverr_proxy"):
        web_novel._run_fff_lossless_update(STORY, path, [ini], False)
    assert not server.browser_calls
    assert path.read_bytes() == before


def test_cloudflare_non_get_never_replayed(server):
    session = requests.Session()
    anubis._install_handler(session, "test", anubis._FlareSolverr("http://localhost:8191/v1", 1000))
    server.cloudflare = True
    with pytest.raises(anubis.RoyalRoadChallengeError, match="non-GET"):
        session.post(STORY)
    assert not server.browser_calls


@pytest.mark.parametrize("classes", ["hidden-content", "description-content", ""])
def test_legacy_description_markup_compatibility(classes):
    request = requests.Request("GET", STORY).prepare()
    html = (
        '<meta property="books:author" content="Author"><table id="chapters"></table>'
        f'<div class="description"><div class="{classes}"><p>Story résumé.</p></div></div>'
    )
    response = response_for(request, html)
    result = anubis._legacy_description_compatibility(response)
    from bs4 import BeautifulSoup

    description = BeautifulSoup(result.content, "html.parser").select_one("div.description div.hidden-content")
    assert description.get_text() == "Story résumé."
    if classes == "hidden-content":
        assert result.content == html.encode()


def test_description_compatibility_does_not_change_chapter_prose():
    request = requests.Request("GET", STORY + "/chapter/1").prepare()
    html = '<meta property="books:author" content="Author"><div class="description"><div>Prose</div></div>'
    assert anubis._legacy_description_compatibility(response_for(request, html)).content == html.encode()


@pytest.mark.parametrize("failure", ["unknown", "reject", "timeout"])
@pytest.mark.parametrize("at_chapter", [False, True])
def test_challenge_failure_never_replaces_existing_epub(tmp_path, server, ini, monkeypatch, failure, at_chapter):
    path = tmp_path / "story.epub"
    download(path, ini)
    before = path.read_bytes()
    server.chapters = [1, 3, 4]
    if at_chapter:
        original_send = server.send

        def fail_at_chapter(request, **kwargs):
            if "/chapter/4/" in request.url:
                server.block = failure
            return original_send(request, **kwargs)

        monkeypatch.setattr(server, "send", fail_at_chapter)
        server.expire_on_chapter = 4
    else:
        server.block = failure
        server.generation += 1
    if failure == "timeout":
        monkeypatch.setattr(anubis, "SOLVE_TIMEOUT", 0)
    with pytest.raises(anubis.RoyalRoadChallengeError):
        web_novel._run_fff_lossless_update(STORY, path, [ini], False)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".*.update-*.epub"))
    assert server.pass_count <= 2  # Only one solve/retry per challenged request.


@pytest.mark.parametrize("algorithm", ["fast", "slow", "argon2id"])
@pytest.mark.parametrize("last_byte", ["00", "ff"])
def test_proof_matches_reference_encoding(algorithm, last_byte):
    data = "0123456789abcdef" * 7 + "0123456789abcd" + last_byte
    challenge = anubis._Challenge.model_validate(
        {"rules": {"algorithm": algorithm, "difficulty": 2}, "challenge": {"id": CHALLENGE_ID, "randomData": data}}
    )
    digest, nonce, elapsed = anubis._solve(challenge)
    if algorithm == "argon2id":
        expected = hash_secret_raw(
            bytes.fromhex(data), nonce.to_bytes(8, "little" if last_byte == "ff" else "big"), 2, 19456, 1, 32, Type.ID, 19
        ).hex()
        assert int(digest, 16) < 2**254
    else:
        expected = hashlib.sha256((data + str(nonce)).encode()).hexdigest()
        assert digest.startswith("00")
    assert digest == expected
    assert elapsed >= 0


def test_solver_attempt_limit(monkeypatch):
    monkeypatch.setattr(anubis, "MAX_FAST_ATTEMPTS", 0)
    request = requests.Request("GET", STORY).prepare()
    challenge = anubis._read_challenge(response_for(request, challenge_html()))
    with pytest.raises(anubis.RoyalRoadChallengeError, match="limit"):
        anubis._solve(challenge)


@pytest.mark.parametrize("url", ["https://example.com", "https://www.royalroad.com.evil.test", "https://royalroad.com:8443"])
def test_other_sites_untouched(url):
    class UntouchedConfig:
        def set(self, *args):
            pytest.fail("Modified unrelated site's configuration")

    with anubis.royalroad_access(UntouchedConfig(), url):
        pass


@pytest.mark.parametrize("source", ["http://royalroad.com/fiction/123", "https://www.royalroadl.com/fiction/123"])
def test_legacy_source_urls_use_https_handler(tmp_path, server, ini, source):
    path = tmp_path / "legacy.epub"
    assert web_novel._run_fff_main(["-c", str(ini), "-o", f"output_filename={path}", source]) == 0
    assert len(get_update_data(path)[7]) == 3
    assert server.pass_count == 1
    assert all(request.url.startswith("https://www.royalroad.com/") for request in server.requests)


def test_non_royalroad_download_still_uses_cli(mocker):
    main = mocker.patch("fanficfare.cli.main")
    args = ["https://example.com/story"]
    assert web_novel._run_fff_main(args) == 0
    main.assert_called_once_with(args)


def test_royalroad_configuration_keeps_overrides_local(server, ini):
    parser = cli.mkParser(False)
    options, _ = parser.parse_args(["-c", str(ini)] + anubis.royalroad_cli_options(STORY))
    config = cli.get_configuration(STORY, None, None, options)
    with anubis.royalroad_access(config, STORY):
        assert config.getConfig("use_flaresolverr_proxy") is False
        assert config.getConfig("continue_on_chapter_error") is False
    assert "use_flaresolverr_proxy:true" in ini.read_text()
