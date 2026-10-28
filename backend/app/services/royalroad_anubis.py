"""Bounded Royal Road Anubis support for FanFicFare's requests transport.

Protocol reference: https://github.com/JimmXinu/FanFicFare/issues/1444
Supports argon2id/css-load and the site's SHA-256 fast/slow worker. Unknown challenges
fail closed rather than being passed to the story parser as chapter content.
"""

import copy
import hashlib
import logging
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
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


def _install_handler(session: requests.Session, user_agent: str) -> None:
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
        challenge = _read_challenge(response)
        if challenge is None:
            return response
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
        if _read_challenge(result) is not None:
            result.close()
            _auth_cookies.pop(key, None)
            raise RoyalRoadChallengeError("Royal Road rejected the Anubis solution. Try again later.")
        result.raise_for_status()
        _merge_cookies(session, result.cookies)
        _remember_clearance(session, key)
        return result

    session.hooks.setdefault("response", []).append(handle)


@contextmanager
def royalroad_access(configuration: Configuration, source_url: str) -> Iterator[None]:
    """Use direct, challenge-aware requests only for Royal Road jobs."""
    if not is_royalroad(source_url):
        yield
        return
    config = cast(_Configuration, configuration)
    for option in ("use_flaresolverr_proxy", "use_nsapa_proxy", "use_browser_cache", "use_cloudscraper"):
        config.set("overrides", option, "false")
    # FFF can otherwise turn an exception into an EPUB chapter containing an
    # error message, which would pass URL-only lossless validation.
    config.set("overrides", "continue_on_chapter_error", "false")
    config.reset_cached_config()
    fetcher = config.get_fetcher(make_new=True)
    session = fetcher.get_requests_session()
    _install_handler(session, config.getConfig("user_agent"))
    try:
        yield
    finally:
        session.close()
