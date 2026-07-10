"""HTTP clients for Open Library and Google Books metadata providers."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import requests
from requests import exceptions as requests_exceptions

from ...config import GOOGLE_BOOKS_API_KEY

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
GOOGLE_BOOKS_USER_AGENT = "story-manager/0.1 (+https://developers.google.com/books)"

_request_lock = threading.Lock()
_last_open_library_request_at = 0.0


def _respect_open_library_rate_limit() -> None:
    global _last_open_library_request_at

    with _request_lock:
        now = time.monotonic()
        wait_seconds = OPEN_LIBRARY_MIN_REQUEST_INTERVAL_SECONDS - (now - _last_open_library_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_open_library_request_at = time.monotonic()


def request_open_library_json(path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
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
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
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
    return bool(GOOGLE_BOOKS_API_KEY)


def request_google_books_json(path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if not google_books_enabled():
        return {}

    request_params = {"key": GOOGLE_BOOKS_API_KEY}
    if params:
        request_params.update(params)

    last_error: Optional[Exception] = None
    for attempt in range(1, GOOGLE_BOOKS_RETRY_ATTEMPTS + 1):
        try:
            response = requests.get(
                f"{GOOGLE_BOOKS_BASE_URL}{path}",
                params=request_params,
                timeout=(GOOGLE_BOOKS_CONNECT_TIMEOUT_SECONDS, GOOGLE_BOOKS_READ_TIMEOUT_SECONDS),
                headers={"User-Agent": GOOGLE_BOOKS_USER_AGENT},
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        except (requests_exceptions.Timeout, requests_exceptions.ConnectionError) as exc:
            last_error = exc
            if attempt < GOOGLE_BOOKS_RETRY_ATTEMPTS:
                time.sleep(0.5 * attempt)
                continue
            raise

    if last_error is not None:
        raise last_error
    return {}
