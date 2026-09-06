"""HTTP clients for online book metadata providers."""

from __future__ import annotations

import threading
import time
from typing import Optional
from .responses import response_object

import requests
from requests import exceptions as requests_exceptions

from ...config import (
    AMAZON_METADATA_DOMAIN,
    AMAZON_METADATA_ENABLED,
    GOOGLE_BOOKS_ALLOW_UNAUTHENTICATED,
    GOOGLE_BOOKS_API_KEY,
)

OPEN_LIBRARY_BASE_URL = "https://openlibrary.org"
OPEN_LIBRARY_CONNECT_TIMEOUT_SECONDS = 3
OPEN_LIBRARY_READ_TIMEOUT_SECONDS = 10
OPEN_LIBRARY_RETRY_ATTEMPTS = 2
OPEN_LIBRARY_MIN_REQUEST_INTERVAL_SECONDS = 0.4
OPEN_LIBRARY_USER_AGENT = "story-manager/0.1 (+https://openlibrary.org)"
GOOGLE_BOOKS_BASE_URL = "https://www.googleapis.com/books/v1"
GOOGLE_BOOKS_CONNECT_TIMEOUT_SECONDS = 3
GOOGLE_BOOKS_READ_TIMEOUT_SECONDS = 10
GOOGLE_BOOKS_RETRY_ATTEMPTS = 2
GOOGLE_BOOKS_MIN_REQUEST_INTERVAL_SECONDS = 0.25
GOOGLE_BOOKS_USER_AGENT = "story-manager/0.1 (+https://developers.google.com/books)"
AMAZON_CONNECT_TIMEOUT_SECONDS = 4
AMAZON_READ_TIMEOUT_SECONDS = 12
AMAZON_MIN_REQUEST_INTERVAL_SECONDS = 1.0
AMAZON_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_request_lock = threading.Lock()
_last_open_library_request_at = 0.0
_last_google_books_request_at = 0.0
_last_amazon_request_at = 0.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _respect_open_library_rate_limit() -> None:
    global _last_open_library_request_at

    with _request_lock:
        now = time.monotonic()
        wait_seconds = OPEN_LIBRARY_MIN_REQUEST_INTERVAL_SECONDS - (now - _last_open_library_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_open_library_request_at = time.monotonic()


def _respect_google_books_rate_limit() -> None:
    global _last_google_books_request_at

    with _request_lock:
        now = time.monotonic()
        wait_seconds = GOOGLE_BOOKS_MIN_REQUEST_INTERVAL_SECONDS - (now - _last_google_books_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_google_books_request_at = time.monotonic()


def _retry_delay(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After") if hasattr(response, "headers") else None
    try:
        return min(5.0, max(0.25, float(retry_after))) if retry_after else 0.5 * attempt
    except (TypeError, ValueError):
        return 0.5 * attempt


def request_open_library_json(path: str, *, params: Optional[dict[str, str | int | None]] = None) -> dict[str, object]:
    last_error: Optional[Exception] = None

    for attempt in range(1, OPEN_LIBRARY_RETRY_ATTEMPTS + 1):
        try:
            _respect_open_library_rate_limit()
            response = requests.get(
                f"{OPEN_LIBRARY_BASE_URL}{path}",
                params=params,
                timeout=(OPEN_LIBRARY_CONNECT_TIMEOUT_SECONDS, OPEN_LIBRARY_READ_TIMEOUT_SECONDS),
                headers={"User-Agent": OPEN_LIBRARY_USER_AGENT},
            )
            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < OPEN_LIBRARY_RETRY_ATTEMPTS:
                time.sleep(_retry_delay(response, attempt))
                continue
            response.raise_for_status()
            payload = response.json()
            return response_object(payload)
        except (requests_exceptions.Timeout, requests_exceptions.ConnectionError) as exc:
            last_error = exc
            if attempt < OPEN_LIBRARY_RETRY_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            raise

    if last_error is not None:
        raise last_error
    return {}


def google_books_enabled() -> bool:
    return bool(GOOGLE_BOOKS_API_KEY) or GOOGLE_BOOKS_ALLOW_UNAUTHENTICATED


def request_google_books_json(path: str, *, params: Optional[dict[str, str | int | None]] = None) -> dict[str, object]:
    if not google_books_enabled():
        return {}

    request_params: dict[str, str | int | None] = {}
    if GOOGLE_BOOKS_API_KEY:
        request_params["key"] = GOOGLE_BOOKS_API_KEY
    if params:
        request_params.update(params)

    last_error: Optional[Exception] = None
    for attempt in range(1, GOOGLE_BOOKS_RETRY_ATTEMPTS + 1):
        try:
            _respect_google_books_rate_limit()
            response = requests.get(
                f"{GOOGLE_BOOKS_BASE_URL}{path}",
                params=request_params,
                timeout=(GOOGLE_BOOKS_CONNECT_TIMEOUT_SECONDS, GOOGLE_BOOKS_READ_TIMEOUT_SECONDS),
                headers={"User-Agent": GOOGLE_BOOKS_USER_AGENT},
            )
            if response.status_code in _RETRYABLE_STATUS_CODES and attempt < GOOGLE_BOOKS_RETRY_ATTEMPTS:
                time.sleep(_retry_delay(response, attempt))
                continue
            response.raise_for_status()
            payload = response.json()
            return response_object(payload)
        except (requests_exceptions.Timeout, requests_exceptions.ConnectionError) as exc:
            last_error = exc
            if attempt < GOOGLE_BOOKS_RETRY_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            raise

    if last_error is not None:
        raise last_error
    return {}


def amazon_metadata_enabled() -> bool:
    return AMAZON_METADATA_ENABLED


def amazon_base_url() -> str:
    return f"https://www.amazon.{AMAZON_METADATA_DOMAIN}"


def request_amazon_html(path: str, *, params: Optional[dict[str, str | int | None]] = None) -> str:
    """Fetch a public Amazon page without making Amazon a hard dependency."""

    global _last_amazon_request_at

    if not amazon_metadata_enabled():
        return ""

    with _request_lock:
        now = time.monotonic()
        wait_seconds = AMAZON_MIN_REQUEST_INTERVAL_SECONDS - (now - _last_amazon_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_amazon_request_at = time.monotonic()

    response = requests.get(
        f"{amazon_base_url()}{path}",
        params=params,
        timeout=(AMAZON_CONNECT_TIMEOUT_SECONDS, AMAZON_READ_TIMEOUT_SECONDS),
        headers={
            "User-Agent": AMAZON_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    response.raise_for_status()
    return response.text
