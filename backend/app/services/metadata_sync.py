"""Online metadata enrichment and preview/apply flows for books."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional

import requests
from requests import exceptions as requests_exceptions
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..config import GOOGLE_BOOKS_API_KEY
from .series import detect_series_from_titles

logger = logging.getLogger(__name__)

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
AUTO_APPROVE_THRESHOLD = 0.92
PROPOSAL_THRESHOLD = 0.75

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_SEPARATOR_RE = re.compile(r"[\s\-:,_]+")
_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")
_TRAILING_SERIES_BOOK_RE = re.compile(r"\s*\([^)]*book\s+\d+[^)]*\)\s*$", re.IGNORECASE)
_TRAILING_PUNCTUATION_RE = re.compile(r"[\s:;,\-]+$")

_request_lock = threading.Lock()
_last_open_library_request_at = 0.0

_GENRE_KEYWORDS = (
    ("progression fantasy", "Progression Fantasy"),
    ("urban fantasy", "Urban Fantasy"),
    ("epic fantasy", "Epic Fantasy"),
    ("science fiction", "Science Fiction"),
    ("sci-fi", "Science Fiction"),
    ("historical fiction", "Historical Fiction"),
    ("young adult", "Young Adult"),
    ("short stories", "Short Stories"),
    ("detective", "Detective"),
    ("thriller", "Thriller"),
    ("mystery", "Mystery"),
    ("fantasy", "Fantasy"),
    ("romance", "Romance"),
    ("horror", "Horror"),
    ("adventure", "Adventure"),
    ("dystopian", "Dystopian"),
    ("dystopia", "Dystopian"),
    ("paranormal", "Paranormal"),
    ("supernatural", "Supernatural"),
    ("crime", "Crime"),
    ("literary", "Literary Fiction"),
    ("humor", "Humor"),
    ("satire", "Satire"),
    ("steampunk", "Steampunk"),
    ("cyberpunk", "Cyberpunk"),
    ("litrpg", "LitRPG"),
    ("mythology", "Mythology"),
    ("war stories", "War"),
    ("xianxia", "Xianxia"),
    ("cultivation", "Cultivation"),
)


@dataclass
class MetadataSuggestion:
    book: models.Book
    matched: bool
    source: str = "open_library"
    match_confidence: float = 0.0
    remote_title: Optional[str] = None
    remote_author: Optional[str] = None
    remote_url: Optional[str] = None
    genre_tags: list[str] | None = None
    new_genre_tags: list[str] | None = None
    possible_missing_series_books: list[str] | None = None
    note: Optional[str] = None
    remote_ids: dict[str, Any] | None = None

    def to_schema(self) -> schemas.MetadataSyncBookResult:
        return schemas.MetadataSyncBookResult(
            book_id=self.book.id,
            title=self.book.title,
            author=self.book.author,
            matched=self.matched,
            match_confidence=round(self.match_confidence, 3),
            remote_title=self.remote_title,
            remote_author=self.remote_author,
            remote_url=self.remote_url,
            genre_tags=self.genre_tags or [],
            new_genre_tags=self.new_genre_tags or [],
            possible_missing_series_books=self.possible_missing_series_books or [],
            note=self.note,
        )


@dataclass
class GoogleBooksMatch:
    volume_id: str
    title: str
    authors: list[str]
    categories: list[str]
    info_link: Optional[str]
    remote_ids: dict[str, str]
    match_confidence: float


def _normalize_text(value: str) -> str:
    return _NON_ALNUM_RE.sub(" ", value.casefold()).strip()


def _normalize_series(value: str) -> str:
    return _SEPARATOR_RE.sub(" ", value.casefold()).strip()


def _respect_open_library_rate_limit() -> None:
    global _last_open_library_request_at

    with _request_lock:
        now = time.monotonic()
        wait_seconds = OPEN_LIBRARY_MIN_REQUEST_INTERVAL_SECONDS - (now - _last_open_library_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _last_open_library_request_at = time.monotonic()


def _request_json(path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
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


def _google_books_enabled() -> bool:
    return bool(GOOGLE_BOOKS_API_KEY)


def _request_google_books_json(path: str, *, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if not _google_books_enabled():
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


def _title_similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    return SequenceMatcher(a=left_norm, b=right_norm).ratio()


def _strip_trailing_metadata(value: str) -> str:
    cleaned = _TRAILING_SERIES_BOOK_RE.sub("", value).strip()
    if cleaned != value.strip():
        return _TRAILING_PUNCTUATION_RE.sub("", cleaned).strip()
    cleaned = _TRAILING_PARENS_RE.sub("", value).strip()
    return _TRAILING_PUNCTUATION_RE.sub("", cleaned).strip()


def _title_search_variants(book: models.Book) -> list[str]:
    variants = [book.title.strip()]
    stripped = _strip_trailing_metadata(book.title)
    if stripped and _normalize_text(stripped) != _normalize_text(book.title):
        variants.append(stripped)
    if book.series and stripped:
        series_without_prefix = re.sub(
            rf"^{re.escape(book.series)}\s*(?:book\s*)?(?:#?\d+(?:\.\d+)?|[IVXLCDM]+)?\s*[:\-]?\s*",
            "",
            stripped,
            flags=re.IGNORECASE,
        ).strip()
        series_without_prefix = _TRAILING_PUNCTUATION_RE.sub("", series_without_prefix).strip()
        if series_without_prefix and _normalize_text(series_without_prefix) not in {
            _normalize_text(variant) for variant in variants
        }:
            variants.append(series_without_prefix)
    return [variant for variant in variants if variant]


def _author_similarity(book: models.Book, doc: dict[str, Any]) -> float:
    local_author = _normalize_text(book.author)
    if not local_author:
        return 0.0

    author_names = doc.get("author_name") or []
    if isinstance(author_names, str):
        author_names = [author_names]

    similarities = [_title_similarity(book.author, author_name) for author_name in author_names if author_name]
    return max(similarities, default=0.0)


def _score_search_doc(book: models.Book, doc: dict[str, Any]) -> float:
    title_score = _title_similarity(book.title, doc.get("title", ""))
    author_score = _author_similarity(book, doc)
    score = (title_score * 0.7) + (author_score * 0.3)

    if _normalize_text(book.title) == _normalize_text(doc.get("title", "")):
        score += 0.1
    if author_score > 0.95:
        score += 0.05

    return min(score, 1.0)


def _extract_subjects(doc: dict[str, Any], work_data: dict[str, Any]) -> list[str]:
    subjects: list[str] = []
    for raw_subject in (work_data.get("subjects") or doc.get("subject") or []):
        if isinstance(raw_subject, str):
            cleaned = raw_subject.strip()
            if cleaned:
                subjects.append(cleaned)

    deduped: list[str] = []
    seen: set[str] = set()
    for subject in subjects:
        normalized = _normalize_text(subject)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(subject)
    return deduped


def _derive_genre_tags(subjects: Iterable[str]) -> list[str]:
    genres: list[str] = []
    seen: set[str] = set()

    for subject in subjects:
        normalized = _normalize_text(subject)
        for keyword, canonical in _GENRE_KEYWORDS:
            if keyword in normalized and canonical.casefold() not in seen:
                seen.add(canonical.casefold())
                genres.append(canonical)

    return genres


def _merge_genre_tags(*groups: Iterable[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for tag in group:
            folded = tag.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            merged.append(tag)
    return merged


def _merge_remote_ids(*groups: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for group in groups:
        merged.update(group)
    return merged


def _title_matches_local_series(title: str, series_name: str) -> bool:
    normalized_title = _normalize_series(title)
    normalized_series = _normalize_series(series_name)
    if not normalized_title or not normalized_series:
        return False
    if normalized_title == normalized_series:
        return True
    return normalized_title.startswith(normalized_series + " ")


def _infer_possible_missing_books(
    book: models.Book,
    local_books_by_author: dict[str, list[models.Book]],
    author_work_titles: list[str],
) -> list[str]:
    if not book.series:
        return []

    normalized_series = _normalize_series(book.series)
    if not normalized_series:
        return []

    local_titles = {
        _normalize_text(local_book.title)
        for local_book in local_books_by_author.get(_normalize_text(book.author), [])
        if local_book.series and _normalize_series(local_book.series) == normalized_series
    }

    inferred_remote_series = detect_series_from_titles(author_work_titles)
    candidates: list[str] = []
    seen: set[str] = set()

    for title in author_work_titles:
        inferred_series = inferred_remote_series.get(title)
        same_series = (
            inferred_series is not None and _normalize_series(inferred_series) == normalized_series
        ) or _title_matches_local_series(title, book.series)
        normalized_title = _normalize_text(title)
        if not same_series or normalized_title in local_titles or normalized_title in seen:
            continue
        seen.add(normalized_title)
        candidates.append(title)

    return sorted(candidates)[:10]


def _select_best_doc(
    book: models.Book,
    docs: list[dict[str, Any]],
    *,
    preferred_author_keys: Optional[set[str]] = None,
) -> tuple[Optional[dict[str, Any]], float]:
    best_doc = None
    best_score = 0.0
    best_ranking_score = 0.0
    for doc in docs:
        score = _score_search_doc(book, doc)
        ranking_score = score
        doc_author_keys = doc.get("author_key") or []
        if isinstance(doc_author_keys, str):
            doc_author_keys = [doc_author_keys]
        if preferred_author_keys and any(author_key in preferred_author_keys for author_key in doc_author_keys):
            ranking_score += 0.08
        if ranking_score > best_ranking_score:
            best_doc = doc
            best_score = score
            best_ranking_score = ranking_score
    return best_doc, best_score


def _build_remote_url(doc: dict[str, Any]) -> Optional[str]:
    key = doc.get("key")
    if not key:
        return None
    return f"{OPEN_LIBRARY_BASE_URL}{key}"


def _extract_remote_ids(doc: dict[str, Any], author_key: Optional[str]) -> dict[str, str]:
    remote_ids: dict[str, str] = {}
    raw_isbns = doc.get("isbn") or []
    if isinstance(raw_isbns, str):
        raw_isbns = [raw_isbns]

    isbn_10 = next((isbn for isbn in raw_isbns if isinstance(isbn, str) and len(isbn) == 10), None)
    isbn_13 = next((isbn for isbn in raw_isbns if isinstance(isbn, str) and len(isbn) == 13), None)
    if doc.get("key"):
        remote_ids["open_library_work_key"] = str(doc["key"])
    if author_key:
        remote_ids["open_library_author_key"] = author_key
    cover_edition_key = doc.get("cover_edition_key")
    if cover_edition_key:
        remote_ids["open_library_edition_key"] = str(cover_edition_key)
    if isbn_10:
        remote_ids["isbn_10"] = isbn_10
    if isbn_13:
        remote_ids["isbn_13"] = isbn_13
    return remote_ids


def _extract_google_volume_info(volume: dict[str, Any]) -> dict[str, Any]:
    volume_info = volume.get("volumeInfo")
    return volume_info if isinstance(volume_info, dict) else {}


def _extract_google_remote_ids(volume: dict[str, Any]) -> dict[str, str]:
    remote_ids: dict[str, str] = {}
    volume_id = volume.get("id")
    if isinstance(volume_id, str) and volume_id.strip():
        remote_ids["google_books_volume_id"] = volume_id.strip()

    volume_info = _extract_google_volume_info(volume)
    identifiers = volume_info.get("industryIdentifiers") or []
    for identifier in identifiers:
        if not isinstance(identifier, dict):
            continue
        id_type = str(identifier.get("type") or "").strip().upper()
        value = str(identifier.get("identifier") or "").strip()
        if not value:
            continue
        if id_type == "ISBN_10" and "isbn_10" not in remote_ids:
            remote_ids["isbn_10"] = value
        if id_type == "ISBN_13" and "isbn_13" not in remote_ids:
            remote_ids["isbn_13"] = value

    return remote_ids


def _google_books_categories(volume: dict[str, Any]) -> list[str]:
    volume_info = _extract_google_volume_info(volume)
    raw_categories = volume_info.get("categories") or []
    if isinstance(raw_categories, str):
        raw_categories = [raw_categories]
    main_category = volume_info.get("mainCategory")
    if isinstance(main_category, str) and main_category.strip():
        raw_categories = [main_category, *raw_categories]

    deduped: list[str] = []
    seen: set[str] = set()
    for category in raw_categories:
        if not isinstance(category, str):
            continue
        cleaned = category.strip()
        if not cleaned:
            continue
        normalized = _normalize_text(cleaned)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(cleaned)
    return deduped


def _google_books_doc(volume: dict[str, Any]) -> dict[str, Any]:
    volume_info = _extract_google_volume_info(volume)
    return {
        "title": volume_info.get("title", ""),
        "author_name": volume_info.get("authors") or [],
    }


def _score_google_books_volume(book: models.Book, volume: dict[str, Any]) -> float:
    volume_doc = _google_books_doc(volume)
    title_score = _title_similarity(book.title, volume_doc.get("title", ""))
    author_score = _author_similarity(book, volume_doc)
    score = (title_score * 0.7) + (author_score * 0.3)

    if _normalize_text(book.title) == _normalize_text(volume_doc.get("title", "")):
        score += 0.12
    if author_score > 0.95:
        score += 0.05

    identifiers = _extract_google_remote_ids(volume)
    manual_remote_ids = _get_manual_remote_ids(book)
    if manual_remote_ids.get("google_books_volume_id") and identifiers.get("google_books_volume_id") == manual_remote_ids.get(
        "google_books_volume_id"
    ):
        score += 0.1
    if manual_remote_ids.get("isbn_13") and identifiers.get("isbn_13") == manual_remote_ids.get("isbn_13"):
        score += 0.08
    if manual_remote_ids.get("isbn_10") and identifiers.get("isbn_10") == manual_remote_ids.get("isbn_10"):
        score += 0.08

    return min(score, 1.0)


def _get_manual_remote_ids(book: models.Book) -> dict[str, str]:
    raw_ids = book.metadata_remote_ids or {}
    if not isinstance(raw_ids, dict):
        return {}
    return {
        key: str(value).strip()
        for key, value in raw_ids.items()
        if value is not None and str(value).strip()
    }


def _fetch_search_docs(params: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _request_json("/search.json", params=params)
    docs = payload.get("docs") or []
    return [doc for doc in docs if isinstance(doc, dict)]


def _fetch_google_books_volumes(query: str) -> list[dict[str, Any]]:
    if not _google_books_enabled():
        return []

    payload = _request_google_books_json("/volumes", params={"q": query, "maxResults": 5})
    items = payload.get("items") or []
    return [item for item in items if isinstance(item, dict)]


def _fetch_google_books_volume_by_id(volume_id: str) -> Optional[dict[str, Any]]:
    if not _google_books_enabled() or not volume_id.strip():
        return None

    payload = _request_google_books_json(f"/volumes/{volume_id.strip()}")
    return payload if payload else None


def _series_peer_author_keys(
    book: models.Book,
    local_books_by_author: dict[str, list[models.Book]],
) -> set[str]:
    if not book.series:
        return set()

    author_books = local_books_by_author.get(_normalize_text(book.author), [])
    keys: set[str] = set()
    for local_book in author_books:
        if local_book.id == book.id or not local_book.series:
            continue
        if _normalize_series(local_book.series) != _normalize_series(book.series):
            continue
        remote_ids = _get_manual_remote_ids(local_book)
        author_key = remote_ids.get("open_library_author_key")
        if author_key:
            keys.add(author_key)
    return keys


def _fetch_series_context_doc(
    book: models.Book,
    *,
    preferred_author_keys: set[str],
    author_work_cache: dict[str, list[dict[str, Any]]],
) -> tuple[Optional[dict[str, Any]], float]:
    if not preferred_author_keys:
        return None, 0.0

    candidate_entries: list[dict[str, Any]] = []
    for author_key in preferred_author_keys:
        entries = _fetch_author_work_entries(author_key, author_work_cache)
        if not entries:
            continue

        author_work_titles = [entry["title"] for entry in entries if entry.get("title")]
        inferred_series = detect_series_from_titles(author_work_titles)
        for entry in entries:
            title = entry.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            if book.series:
                same_series = (
                    inferred_series.get(title) is not None
                    and _normalize_series(inferred_series[title]) == _normalize_series(book.series)
                ) or _title_matches_local_series(title, book.series)
                if not same_series:
                    continue
            candidate_entries.append(
                {
                    "key": entry.get("key"),
                    "title": title,
                    "author_name": [book.author],
                    "author_key": [author_key],
                }
            )

    best_doc = None
    best_score = 0.0
    for variant in _title_search_variants(book):
        variant_book = models.Book(title=variant, author=book.author)
        candidate, score = _select_best_doc(
            variant_book,
            candidate_entries,
            preferred_author_keys=preferred_author_keys,
        )
        if score > best_score:
            best_doc = candidate
            best_score = score

    return best_doc, best_score


def _fetch_search_doc(
    book: models.Book,
    *,
    local_books_by_author: dict[str, list[models.Book]],
    author_work_cache: dict[str, list[dict[str, Any]]],
) -> tuple[Optional[dict[str, Any]], float, Optional[str]]:
    manual_remote_ids = _get_manual_remote_ids(book)
    preferred_author_keys = _series_peer_author_keys(book, local_books_by_author)
    manual_author_key = manual_remote_ids.get("open_library_author_key")
    if manual_author_key:
        preferred_author_keys.add(manual_author_key)

    search_variants: list[dict[str, Any]] = []
    if manual_remote_ids.get("isbn_13"):
        search_variants.append({"isbn": manual_remote_ids["isbn_13"], "limit": 5})
    if manual_remote_ids.get("isbn_10"):
        search_variants.append({"isbn": manual_remote_ids["isbn_10"], "limit": 5})
    for title_variant in _title_search_variants(book):
        search_variants.append({"title": title_variant, "author": book.author, "limit": 5})

    seen_searches: set[tuple[tuple[str, Any], ...]] = set()
    best_doc = None
    best_score = 0.0

    for params in search_variants:
        key = tuple(sorted(params.items()))
        if key in seen_searches:
            continue
        seen_searches.add(key)
        docs = _fetch_search_docs(params)
        if not docs:
            continue
        candidate, score = _select_best_doc(book, docs, preferred_author_keys=preferred_author_keys)
        if score > best_score:
            best_doc = candidate
            best_score = score

    if best_doc is None and manual_remote_ids.get("open_library_work_key"):
        work_key = manual_remote_ids["open_library_work_key"]
        try:
            work_data = _request_json(f"{work_key}.json")
            best_doc = {
                "key": work_key,
                "title": work_data.get("title", book.title),
                "author_name": [book.author],
                "author_key": [manual_author_key] if manual_author_key else [],
            }
            best_score = max(_title_similarity(book.title, best_doc.get("title", "")), 0.9)
        except requests.RequestException:
            pass

    series_doc, series_score = _fetch_series_context_doc(
        book,
        preferred_author_keys=preferred_author_keys,
        author_work_cache=author_work_cache,
    )
    if series_score > best_score:
        best_doc = series_doc
        best_score = series_score

    if best_doc is None:
        return None, 0.0, "No Open Library match found."

    threshold = 0.68 if preferred_author_keys or manual_remote_ids else 0.72
    if best_score < threshold:
        return None, best_score, "No confident Open Library match found."

    return best_doc, best_score, None


def _fetch_google_books_match(book: models.Book) -> tuple[Optional[GoogleBooksMatch], float, Optional[str]]:
    if not _google_books_enabled():
        return None, 0.0, None

    manual_remote_ids = _get_manual_remote_ids(book)
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    manual_volume_id = manual_remote_ids.get("google_books_volume_id")
    if manual_volume_id:
        try:
            volume = _fetch_google_books_volume_by_id(manual_volume_id)
        except requests.RequestException:
            logger.warning("Failed to fetch Google Books volume metadata for %s.", manual_volume_id)
            volume = None
        if volume and isinstance(volume.get("id"), str):
            seen_ids.add(volume["id"])
            candidates.append(volume)

    for isbn_key in ("isbn_13", "isbn_10"):
        isbn_value = manual_remote_ids.get(isbn_key)
        if not isbn_value:
            continue
        try:
            isbn_candidates = _fetch_google_books_volumes(f"isbn:{isbn_value}")
        except requests.RequestException:
            logger.warning("Failed to search Google Books for ISBN %s.", isbn_value)
            continue
        for candidate in isbn_candidates:
            candidate_id = candidate.get("id")
            if isinstance(candidate_id, str) and candidate_id not in seen_ids:
                seen_ids.add(candidate_id)
                candidates.append(candidate)

    for title_variant in _title_search_variants(book):
        query = f'intitle:"{title_variant}" inauthor:"{book.author}"'
        try:
            search_candidates = _fetch_google_books_volumes(query)
        except requests.RequestException:
            logger.warning("Failed to search Google Books for %s by %s.", title_variant, book.author)
            continue
        for candidate in search_candidates:
            candidate_id = candidate.get("id")
            if isinstance(candidate_id, str) and candidate_id not in seen_ids:
                seen_ids.add(candidate_id)
                candidates.append(candidate)

    if not candidates:
        return None, 0.0, "No Google Books match found."

    best_candidate = None
    best_score = 0.0
    for candidate in candidates:
        score = _score_google_books_volume(book, candidate)
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is None:
        return None, 0.0, "No Google Books match found."

    threshold = 0.78 if manual_remote_ids else 0.84
    if best_score < threshold:
        return None, best_score, "No confident Google Books match found."

    volume_info = _extract_google_volume_info(best_candidate)
    authors = volume_info.get("authors") or []
    if isinstance(authors, str):
        authors = [authors]

    return (
        GoogleBooksMatch(
            volume_id=str(best_candidate.get("id")),
            title=str(volume_info.get("title") or book.title),
            authors=[author for author in authors if isinstance(author, str)],
            categories=_google_books_categories(best_candidate),
            info_link=volume_info.get("infoLink"),
            remote_ids=_extract_google_remote_ids(best_candidate),
            match_confidence=best_score,
        ),
        best_score,
        None,
    )


def _fetch_work_data(doc: dict[str, Any]) -> dict[str, Any]:
    key = doc.get("key")
    if not key:
        return {}
    try:
        return _request_json(f"{key}.json")
    except requests.RequestException:
        logger.warning("Failed to fetch Open Library work metadata for %s.", key, exc_info=True)
        return {}


def _fetch_author_work_entries(
    author_key: Optional[str],
    author_work_cache: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not author_key:
        return []
    if author_key in author_work_cache:
        return author_work_cache[author_key]

    try:
        payload = _request_json(f"/authors/{author_key}/works.json", params={"limit": 200})
    except requests.RequestException:
        logger.warning("Failed to fetch Open Library author works for %s.", author_key, exc_info=True)
        author_work_cache[author_key] = []
        return []

    entries = payload.get("entries") or []
    normalized_entries = [
        {
            "key": entry.get("key"),
            "title": entry.get("title", "").strip(),
        }
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("title"), str) and entry.get("title").strip()
    ]
    author_work_cache[author_key] = normalized_entries
    return normalized_entries


def _build_suggestion_for_book(
    book: models.Book,
    local_books_by_author: dict[str, list[models.Book]],
    author_work_cache: dict[str, list[dict[str, Any]]],
) -> MetadataSuggestion:
    if not book.title or not book.author or book.author.strip().lower() == "pending":
        return MetadataSuggestion(book=book, matched=False, note="Book is missing stable title/author metadata.")

    google_match: Optional[GoogleBooksMatch] = None
    try:
        doc, score, note = _fetch_search_doc(
            book,
            local_books_by_author=local_books_by_author,
            author_work_cache=author_work_cache,
        )
    except requests.RequestException:
        logger.warning("Metadata sync request failed for %s by %s; continuing.", book.title, book.author)
        doc, score, note = None, 0.0, "Open Library request failed."

    if doc is None:
        try:
            google_match, google_score, google_note = _fetch_google_books_match(book)
        except requests.RequestException:
            logger.warning("Google Books metadata request failed for %s by %s; continuing.", book.title, book.author)
            google_match, google_score, google_note = None, 0.0, "Google Books request failed."

        if google_match is None:
            return MetadataSuggestion(
                book=book,
                matched=False,
                match_confidence=max(score, google_score),
                note=google_note or note,
            )

        google_genre_tags = _derive_genre_tags(google_match.categories)
        existing_tags = {tag.casefold() for tag in (book.genre_tags or [])}
        new_tags = [tag for tag in google_genre_tags if tag.casefold() not in existing_tags]
        return MetadataSuggestion(
            book=book,
            matched=True,
            source="google_books",
            match_confidence=google_match.match_confidence,
            remote_title=google_match.title,
            remote_author=google_match.authors[0] if google_match.authors else None,
            remote_url=google_match.info_link,
            genre_tags=google_genre_tags,
            new_genre_tags=new_tags,
            possible_missing_series_books=[],
            remote_ids=google_match.remote_ids,
            note=None if google_genre_tags else "Matched in Google Books, but no genre tags were found.",
        )

    work_data = _fetch_work_data(doc)
    subjects = _extract_subjects(doc, work_data)
    genre_tags = _derive_genre_tags(subjects)
    existing_tags = {tag.casefold() for tag in (book.genre_tags or [])}
    new_tags = [tag for tag in genre_tags if tag.casefold() not in existing_tags]

    author_names = doc.get("author_name") or []
    if isinstance(author_names, str):
        author_names = [author_names]
    author_keys = doc.get("author_key") or []
    if isinstance(author_keys, str):
        author_keys = [author_keys]
    author_key = author_keys[0] if author_keys else None

    author_work_entries = _fetch_author_work_entries(author_key, author_work_cache)
    author_work_titles = [entry["title"] for entry in author_work_entries if entry.get("title")]
    possible_missing = _infer_possible_missing_books(book, local_books_by_author, author_work_titles)

    remote_ids = _extract_remote_ids(doc, author_key)
    open_library_remote_ids = dict(remote_ids)
    source = "open_library"
    try:
        google_match, _, _ = _fetch_google_books_match(book)
    except requests.RequestException:
        logger.warning("Google Books metadata request failed for %s by %s; continuing.", book.title, book.author)
        google_match = None

    if google_match is not None:
        google_genre_tags = _derive_genre_tags(google_match.categories)
        genre_tags = _merge_genre_tags(genre_tags, google_genre_tags)
        new_tags = [tag for tag in genre_tags if tag.casefold() not in existing_tags]
        remote_ids = _merge_remote_ids(google_match.remote_ids, remote_ids)
        if google_genre_tags or any(
            remote_ids.get(key) != open_library_remote_ids.get(key)
            for key in google_match.remote_ids
        ):
            source = "open_library+google_books"

    return MetadataSuggestion(
        book=book,
        matched=True,
        source=source,
        match_confidence=score,
        remote_title=doc.get("title"),
        remote_author=author_names[0] if author_names else None,
        remote_url=_build_remote_url(doc),
        genre_tags=genre_tags,
        new_genre_tags=new_tags,
        possible_missing_series_books=possible_missing,
        remote_ids=remote_ids,
        note=None if genre_tags or possible_missing else "Matched, but no genre tags or series candidates were found.",
    )


async def _generate_suggestions(
    target_books: list[models.Book],
    all_books: list[models.Book],
) -> list[MetadataSuggestion]:
    local_books_by_author: dict[str, list[models.Book]] = {}
    for book in all_books:
        local_books_by_author.setdefault(_normalize_text(book.author or ""), []).append(book)

    author_work_cache: dict[str, list[dict[str, Any]]] = {}

    return await asyncio.to_thread(
        lambda: [
            _build_suggestion_for_book(book, local_books_by_author, author_work_cache)
            for book in target_books
        ]
    )


async def generate_suggestions(
    target_books: list[models.Book],
    all_books: list[models.Book],
) -> list[MetadataSuggestion]:
    return await _generate_suggestions(target_books, all_books)


def apply_suggestion_to_book(
    book: models.Book,
    suggestion: MetadataSuggestion,
    *,
    source: Optional[str] = None,
    synced_at: Optional[datetime] = None,
) -> bool:
    if not suggestion.matched:
        return False

    resolved_source = source or suggestion.source or "open_library"
    synced_timestamp = synced_at or datetime.now(timezone.utc)
    merged_genres = sorted(
        {
            *(tag for tag in (book.genre_tags or [])),
            *(tag for tag in (suggestion.genre_tags or [])),
        },
        key=str.casefold,
    )
    next_remote_ids = {
        **_get_manual_remote_ids(book),
        **(suggestion.remote_ids or {}),
    }

    changed = (
        merged_genres != (book.genre_tags or [])
        or next_remote_ids != (book.metadata_remote_ids or {})
        or book.metadata_sync_source != resolved_source
    )

    book.genre_tags = merged_genres
    book.metadata_remote_ids = next_remote_ids
    book.metadata_sync_source = resolved_source
    book.metadata_synced_at = synced_timestamp
    return changed


async def _get_target_books(db: AsyncSession, book_ids: Optional[list[int]] = None) -> list[models.Book]:
    if book_ids:
        return await crud.get_books_by_ids(db, book_ids)
    return await crud.get_books(db, limit=100000)


async def preview_metadata_sync(
    db: AsyncSession,
    book_ids: Optional[list[int]] = None,
) -> schemas.MetadataSyncPreviewResponse:
    target_books = await _get_target_books(db, book_ids=book_ids)
    all_books = await crud.get_books(db, limit=100000)
    suggestions = await _generate_suggestions(target_books, all_books)

    results = [suggestion.to_schema() for suggestion in suggestions]
    return schemas.MetadataSyncPreviewResponse(
        scanned_books=len(target_books),
        matched_books=sum(1 for suggestion in suggestions if suggestion.matched),
        books_with_new_genres=sum(1 for suggestion in suggestions if suggestion.new_genre_tags),
        books_with_missing_series_candidates=sum(
            1 for suggestion in suggestions if suggestion.possible_missing_series_books
        ),
        results=results,
    )


async def apply_metadata_sync(
    db: AsyncSession,
    book_ids: Optional[list[int]] = None,
) -> schemas.MetadataSyncApplyResponse:
    target_books = await _get_target_books(db, book_ids=book_ids)
    all_books = await crud.get_books(db, limit=100000)
    suggestions = await _generate_suggestions(target_books, all_books)

    updated_books = 0
    synced_at = datetime.now(timezone.utc)

    for suggestion in suggestions:
        if not suggestion.matched:
            continue

        if apply_suggestion_to_book(suggestion.book, suggestion, source=suggestion.source, synced_at=synced_at):
            updated_books += 1

    await db.commit()

    return schemas.MetadataSyncApplyResponse(
        scanned_books=len(target_books),
        matched_books=sum(1 for suggestion in suggestions if suggestion.matched),
        updated_books=updated_books,
        books_with_new_genres=sum(1 for suggestion in suggestions if suggestion.new_genre_tags),
        books_with_missing_series_candidates=sum(
            1 for suggestion in suggestions if suggestion.possible_missing_series_books
        ),
        results=[suggestion.to_schema() for suggestion in suggestions],
    )
