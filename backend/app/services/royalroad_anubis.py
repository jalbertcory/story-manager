"""Bounded Royal Road challenge support for FanFicFare's requests transport.

Protocol reference: https://github.com/JimmXinu/FanFicFare/issues/1444
Supports Anubis proof of work and configured FlareSolverr fallback for Cloudflare.
Unknown challenges fail closed rather than becoming chapter content.
"""

import copy
import hashlib
import logging
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

import requests
from argon2.low_level import Type, hash_secret_raw
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError
from requests.cookies import RequestsCookieJar

from .fanficfare_types import Configuration

logger = logging.getLogger(__name__)
SOLVE_TIMEOUT = 10.0
MAX_ATTEMPTS = 1024
MAX_FAST_ATTEMPTS = 2_000_000
REQUEST_TIMEOUT = 30.0
_AUTH_PREFIX = "techaro.lol-anubis-auth"
# Session clearance only; never persist login cookies to disk or share them.
_auth_cookies: OrderedDict[tuple[str, str], RequestsCookieJar] = OrderedDict()


class RoyalRoadChallengeError(RuntimeError):
    """Royal Road could not be cleared for this download; retain the saved EPUB."""


class _Rules(BaseModel):
    algorithm: Literal["argon2id", "fast", "slow"]
    difficulty: int = Field(strict=True, ge=0, le=16)
    extensions: list[Literal["css-load"]] = Field(default_factory=list)


class _ChallengeData(BaseModel):
    id: UUID
    randomData: str = Field(pattern=r"^(?:[0-9a-fA-F]{2}){8,2048}$")


class _Challenge(BaseModel):
    rules: _Rules
    challenge: _ChallengeData


class _BrowserSolution(BaseModel):
    status: Literal[200]
    url: str
    response: str = Field(min_length=1)


class _BrowserResult(BaseModel):
    status: Literal["ok"]
    solution: _BrowserSolution


def _is_cloudflare(response: requests.Response) -> bool:
    if response.headers.get("cf-mitigated") == "challenge":
        return True
    content = response.content
    if b"Just a moment" not in content or not any(
        marker in content for marker in (b"/cdn-cgi/challenge-platform/", b"challenges.cloudflare.com")
    ):
        return False
    soup = BeautifulSoup(content, "html.parser")
    return soup.title is not None and "just a moment" in soup.title.get_text().lower()


def _legacy_description_compatibility(response: requests.Response) -> requests.Response:
    # FFF 4.62.0 expects hidden-content, but RR now also uses other classes.
    # Remove after upgrading to a release containing upstream fix 496f459d:
    # https://github.com/JimmXinu/FanFicFare/commit/496f459d99360ff8f5fc0a56c47761a60242dc87
    if b"books:author" not in response.content:
        return response
    soup = BeautifulSoup(response.content, "html.parser")
    if soup.select_one("table#chapters") is not None and soup.select_one("div.description div.hidden-content") is None:
        description = soup.select_one("div.description div")
        if description is not None:
            description["class"] = [name for name in description.get_attribute_list("class") if name is not None] + [
                "hidden-content"
            ]
            response._content = str(soup).encode("utf-8")
            response.encoding = "utf-8"
            response.headers.pop("Content-Length", None)
    return response


@dataclass(frozen=True)
class _FlareSolverr:
    endpoint: str
    timeout_ms: int

    def fetch(self, response: requests.Response) -> requests.Response:
        # Retrieve public HTML in the browser. Do not export login cookies or
        # copy browser clearance into requests, whose TLS identity is different.
        logger.info("Fetching Royal Road Cloudflare challenge through configured FlareSolverr.")
        try:
            with requests.Session() as browser:
                with browser.post(
                    self.endpoint,
                    json={"cmd": "request.get", "url": response.url, "maxTimeout": self.timeout_ms},
                    timeout=self.timeout_ms / 1000 + 5,
                    allow_redirects=False,
                ) as reply:
                    reply.raise_for_status()
                    solved = _BrowserResult.model_validate_json(reply.content).solution
        except (requests.RequestException, ValidationError) as exc:
            raise RoyalRoadChallengeError(
                "Royal Road Cloudflare check failed through FlareSolverr. The saved EPUB was retained."
            ) from exc
        if not is_royalroad(solved.url) or urlsplit(solved.url).scheme != "https":
            raise RoyalRoadChallengeError("FlareSolverr redirected outside Royal Road; refusing the response.")
        result = requests.Response()
        result.status_code = 200
        result.url = solved.url
        result.request = response.request
        result.headers["Content-Type"] = "text/html; charset=utf-8"
        result.encoding = "utf-8"
        result._content = solved.response.encode("utf-8")
        # A successful proxy response can still contain a challenge. Never give
        # that page to the adapter or recursively invoke the browser.
        if _is_cloudflare(result) or _read_challenge(result) is not None:
            raise RoyalRoadChallengeError("FlareSolverr returned another Royal Road bot challenge. Try again later.")
        response.close()
        return _legacy_description_compatibility(result)


class _RequestsFetcher(Protocol):
    def get_requests_session(self) -> requests.Session: ...


class _Configuration(Configuration, Protocol):
    def getConfig(self, key: str, default: str = "") -> str: ...
    def get_fetcher(self, make_new: bool = False) -> _RequestsFetcher: ...
    def reset_cached_config(self) -> None: ...


def is_royalroad(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"royalroad.com", "www.royalroad.com", "royalroadl.com", "www.royalroadl.com"}
        and parsed.port in {None, 80 if parsed.scheme == "http" else 443}
    )


def royalroad_cli_options(source_url: str) -> list[str]:
    # CLI configuration initializes browser caches before royalroad_access can
    # replace the fetcher. Disable that path before reading the configuration.
    return ["-o", "use_browser_cache=false"] if is_royalroad(source_url) else []


def _read_challenge(response: requests.Response) -> _Challenge | None:
    # Do not parse binary covers or ordinary chapters on every request.
    content = response.content
    if b"anubis_challenge" not in content:
        if b"Making sure" in content or b"Just a moment" in content:
            soup = BeautifulSoup(content, "html.parser")
            title = soup.title.get_text().lower() if soup.title else ""
            if ("making sure" in title and "bot" in title) or "just a moment" in title:
                raise RoyalRoadChallengeError("Royal Road returned an unsupported bot challenge. Try again later.")
        return None
    soup = BeautifulSoup(content, "html.parser")
    tag = soup.find("script", id="anubis_challenge")
    if tag is None:
        return None
    try:
        return _Challenge.model_validate_json(tag.get_text())
    except ValidationError as exc:
        raise RoyalRoadChallengeError("Royal Road changed its Anubis challenge; the handler needs updating.") from exc


def _solve(challenge: _Challenge) -> tuple[str, int, int]:
    data = bytes.fromhex(challenge.challenge.randomData)
    byteorder: Literal["little", "big"] = "little" if data[-1] >= 128 else "big"
    started = time.monotonic()
    fast = challenge.rules.algorithm in {"fast", "slow"}
    # The JS worker hashes the hex *text* followed by a decimal nonce; its
    # difficulty counts hex zeroes. Argon2 uses decoded bytes and zero bits.
    difficulty_bits = challenge.rules.difficulty * (4 if fast else 1)
    for nonce in range(MAX_FAST_ATTEMPTS if fast else MAX_ATTEMPTS):
        if time.monotonic() - started >= SOLVE_TIMEOUT:
            break
        if fast:
            digest = hashlib.sha256((challenge.challenge.randomData + str(nonce)).encode("ascii")).digest()
        else:
            digest = hash_secret_raw(
                secret=data,
                salt=nonce.to_bytes(8, byteorder),
                time_cost=2,
                memory_cost=19456,
                parallelism=1,
                hash_len=32,
                type=Type.ID,
                version=0x13,
            )
        if int.from_bytes(digest, "big") >> (256 - difficulty_bits) == 0:
            elapsed = int((time.monotonic() - started) * 1000)
            return digest.hex(), nonce, elapsed
    raise RoyalRoadChallengeError("Royal Road Anubis proof of work exceeded the time or attempt limit. Try again later.")


def _remember_clearance(session: requests.Session, key: tuple[str, str]) -> None:
    jar = RequestsCookieJar()
    for cookie in session.cookies:
        if cookie.name.startswith(_AUTH_PREFIX) and cookie.domain.lstrip(".") in {"royalroad.com", "www.royalroad.com"}:
            if not cookie.is_expired():
                jar.set_cookie(copy.copy(cookie))
    _auth_cookies[key] = jar
    _auth_cookies.move_to_end(key)
    while len(_auth_cookies) > 16:
        _auth_cookies.popitem(last=False)


def _merge_cookies(session: requests.Session, cookies: CookieJar) -> None:
    # FFF uses an LWPCookieJar, which lacks RequestsCookieJar.update().
    for cookie in cookies:
        session.cookies.set_cookie(copy.copy(cookie))


def _install_handler(session: requests.Session, user_agent: str, browser: _FlareSolverr | None = None) -> None:
    # Keep clearance separate for different user agents and network routes.
    settings = session.merge_environment_settings("https://www.royalroad.com/", {}, False, None, None)
    key = (user_agent, repr(sorted(settings["proxies"].items())))
    cached = _auth_cookies.get(key)
    if cached is not None:
        for cookie in cached:
            if not cookie.is_expired():
                session.cookies.set_cookie(copy.copy(cookie))

    # Requests supplies transport options to response hooks as arbitrary kwargs.
    # Forward those options unchanged except for bounded challenge timeouts.
    def handle(response: requests.Response, **kwargs: Any) -> requests.Response:
        parsed = urlsplit(response.url)
        # FFF normalizes legacy source URLs to this HTTPS host before fetching.
        if (
            not is_royalroad(response.url)
            or parsed.scheme != "https"
            or parsed.hostname
            not in {
                "www.royalroad.com",
                "royalroad.com",
            }
        ):
            return response
        if _is_cloudflare(response):
            if response.request.method != "GET":
                raise RoyalRoadChallengeError("Royal Road challenged a non-GET request; refusing to replay it.")
            if browser is None:
                raise RoyalRoadChallengeError(
                    "Royal Road now requires a Cloudflare browser check. Configure use_flaresolverr_proxy:true "
                    "and a reachable FlareSolverr server. The saved EPUB was retained."
                )
            return browser.fetch(response)
        challenge = _read_challenge(response)
        if challenge is None:
            return _legacy_description_compatibility(response)
        if response.request.method != "GET":
            raise RoyalRoadChallengeError("Royal Road challenged a non-GET request; refusing to replay it.")
        _merge_cookies(session, response.cookies)
        origin = f"https://{urlsplit(response.url).hostname}"
        base = origin + "/.within.website/x/cmd/anubis/"
        headers = {"User-Agent": response.request.headers.get("User-Agent", user_agent)}
        transport = {**kwargs, "timeout": REQUEST_TIMEOUT, "stream": False}

        def get(url: str, params: dict[str, str] | None = None) -> requests.Response:
            prepared = session.prepare_request(requests.Request("GET", url, headers=headers, params=params))
            prepared.hooks = {"response": []}  # Never recursively solve a challenge.
            result = session.send(prepared, **transport)
            result.raise_for_status()
            return result

        logger.info("Solving Royal Road Anubis challenge.")
        if "css-load" in challenge.rules.extensions:
            get(base + "ext/css-load/" + str(challenge.challenge.id)).close()
        digest, nonce, elapsed = _solve(challenge)
        cleared = get(
            base + "api/pass-challenge",
            {
                "id": str(challenge.challenge.id),
                "response": digest,
                "nonce": str(nonce),
                "redir": response.url,
                "elapsedTime": str(elapsed),
            },
        )
        _merge_cookies(session, cleared.cookies)
        cleared.close()
        # Retry exactly once, with the same headers, User-Agent and current cookies.
        retry = response.request.copy()
        retry.headers.pop("Cookie", None)
        retry.prepare_cookies(session.cookies)
        retry.hooks = {"response": []}
        response.close()
        result = session.send(retry, **transport)
        if _is_cloudflare(result) and browser is not None:
            return browser.fetch(result)
        if _read_challenge(result) is not None:
            result.close()
            _auth_cookies.pop(key, None)
            raise RoyalRoadChallengeError("Royal Road rejected the Anubis solution. Try again later.")
        result.raise_for_status()
        _merge_cookies(session, result.cookies)
        _remember_clearance(session, key)
        return _legacy_description_compatibility(result)

    session.hooks.setdefault("response", []).append(handle)


@contextmanager
def royalroad_access(configuration: Configuration, source_url: str) -> Iterator[None]:
    """Use direct requests with a configured browser fallback for Royal Road."""
    if not is_royalroad(source_url):
        yield
        return
    config = cast(_Configuration, configuration)
    browser = None
    if str(config.getConfig("use_flaresolverr_proxy")).lower() in {"true", "withimages", "directimages"}:
        endpoint = (
            config.getConfig("flaresolverr_proxy_protocol", "http")
            + "://"
            + config.getConfig("flaresolverr_proxy_address", "localhost")
            + ":"
            + config.getConfig("flaresolverr_proxy_port", "8191")
            + "/v1"
        )
        timeout_ms = max(1, min(int(config.getConfig("flaresolverr_proxy_timeout", "59000")), 60000))
        browser = _FlareSolverr(endpoint, timeout_ms)
    for option in ("use_flaresolverr_proxy", "use_nsapa_proxy", "use_browser_cache", "use_cloudscraper"):
        config.set("overrides", option, "false")
    # FFF can otherwise turn an exception into an EPUB chapter containing an
    # error message, which would pass URL-only lossless validation.
    config.set("overrides", "continue_on_chapter_error", "false")
    config.reset_cached_config()
    fetcher = config.get_fetcher(make_new=True)
    session = fetcher.get_requests_session()
    _install_handler(session, config.getConfig("user_agent"), browser)
    try:
        yield
    finally:
        session.close()
