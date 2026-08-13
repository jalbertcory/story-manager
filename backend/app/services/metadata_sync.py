"""Online metadata enrichment and preview/apply flows for books."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from .metadata.arbitration import arbitrate_candidate_suggestions, refine_unmatched_search_identity
from .metadata.amazon import AmazonCandidate, enrich_amazon_candidate, search_amazon
from .metadata.clients import amazon_metadata_enabled as _amazon_metadata_enabled
from .metadata.clients import OPEN_LIBRARY_BASE_URL
from .metadata.clients import google_books_enabled as _google_books_enabled
from .metadata.clients import request_google_books_json as _request_google_books_json
from .metadata.clients import request_open_library_json as _request_json
from .metadata.genres import derive_genre_tags as _derive_genre_tags
from .metadata.genres import merge_genre_tags as _merge_genre_tags
from .metadata.evidence import SearchIdentity, resolve_search_identity
from .metadata.scoring import normalize_series as _normalize_series
from .metadata.scoring import normalize_text as _normalize_text
from .metadata.scoring import best_author_similarity as _best_author_similarity
from .metadata.scoring import bibliographic_title_variants as _bibliographic_title_variants
from .metadata.scoring import canonical_isbn as _canonical_isbn
from .metadata.scoring import clean_isbn as _clean_isbn
from .metadata.scoring import infer_series_metadata as _infer_series_metadata
from .metadata.scoring import score_metadata_candidate as _score_metadata_candidate
from .metadata.scoring import series_match_issues as _series_match_issues
from .metadata.scoring import title_similarity as _title_similarity
from .series import detect_series_from_titles

logger = logging.getLogger(__name__)

AUTO_APPROVE_THRESHOLD = 0.92
PROPOSAL_THRESHOLD = 0.75
DEFAULT_MATCH_CANDIDATE_LIMIT = 5
KNOWN_REMOTE_ID_KEYS = {
    "asin",
    "google_books_volume_id",
    "isbn_10",
    "isbn_13",
    "open_library_author_key",
    "open_library_edition_key",
    "open_library_work_key",
}

_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")
_TRAILING_SERIES_BOOK_RE = re.compile(r"\s*\([^)]*book\s+\d+[^)]*\)\s*$", re.IGNORECASE)
_TRAILING_PUNCTUATION_RE = re.compile(r"[\s:;,\-]+$")


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
    metadata_details: dict[str, Any] | None = None
    match_issues: list[str] | None = None

    def to_schema(self) -> schemas.MetadataSyncBookResult:
        return schemas.MetadataSyncBookResult(
            book_id=self.book.id,
            title=self.book.title,
            author=self.book.author,
            matched=self.matched,
            source=self.source if self.matched else None,
            match_confidence=round(self.match_confidence, 3),
            remote_title=self.remote_title,
            remote_author=self.remote_author,
            remote_url=self.remote_url,
            remote_ids=self.remote_ids,
            metadata_details=self.metadata_details,
            match_issues=self.match_issues or [],
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
    metadata_details: dict[str, Any]
    match_confidence: float


@dataclass
class AmazonMatch:
    asin: str
    title: str
    authors: list[str]
    categories: list[str]
    remote_url: str
    remote_ids: dict[str, str]
    metadata_details: dict[str, Any]
    match_confidence: float


def _strip_trailing_metadata(value: str) -> str:
    cleaned = _TRAILING_SERIES_BOOK_RE.sub("", value).strip()
    if cleaned != value.strip():
        return _TRAILING_PUNCTUATION_RE.sub("", cleaned).strip()
    cleaned = _TRAILING_PARENS_RE.sub("", value).strip()
    return _TRAILING_PUNCTUATION_RE.sub("", cleaned).strip()


def _title_search_variants(book: models.Book) -> list[str]:
    variants = _bibliographic_title_variants(book.title, book.series or "") or [book.title.strip()]
    stripped = _strip_trailing_metadata(book.title)
    if stripped and _normalize_text(stripped) not in {_normalize_text(variant) for variant in variants}:
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


def _score_search_doc(book: models.Book, doc: dict[str, Any]) -> float:
    author_names = doc.get("author_name") or []
    if isinstance(author_names, str):
        author_names = [author_names]
    author_keys = doc.get("author_key") or []
    if isinstance(author_keys, str):
        author_keys = [author_keys]
    remote_title = str(doc.get("title") or "")
    series_details = _series_metadata_details(
        remote_title,
        series=doc.get("series"),
        series_index=doc.get("series_index"),
    )
    return _score_metadata_candidate(
        local_title=book.title,
        local_author=book.author,
        remote_title=remote_title,
        remote_authors=[str(author) for author in author_names if author],
        local_ids=_get_manual_remote_ids(book),
        remote_ids=_extract_remote_ids(doc, str(author_keys[0]) if author_keys else None),
        local_series=book.series or "",
        local_series_index=book.series_index,
        remote_series=str(series_details.get("series") or ""),
        remote_series_index=series_details.get("series_index"),
    )


def _extract_subjects(doc: dict[str, Any], work_data: dict[str, Any]) -> list[str]:
    subjects: list[str] = []
    for raw_subject in work_data.get("subjects") or doc.get("subject") or []:
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


def _merge_remote_ids(*groups: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for group in groups:
        merged.update(group)
    return merged


def _stable_remote_identifiers(remote_ids: dict[str, Any] | None) -> set[tuple[str, str]]:
    remote_ids = remote_ids or {}
    identifiers = {
        (key, str(remote_ids[key]).strip())
        for key in ("google_books_volume_id", "open_library_work_key", "asin")
        if remote_ids.get(key) and str(remote_ids[key]).strip()
    }
    identifiers.update(
        ("isbn", normalized) for key in ("isbn_10", "isbn_13") if (normalized := _canonical_isbn(remote_ids.get(key)))
    )
    return identifiers


def _annotate_duplicate_assignments(
    book: models.Book,
    suggestions: list[MetadataSuggestion],
    all_books: list[models.Book],
    *,
    ignored_book_ids: set[int] | None = None,
) -> None:
    ignored_book_ids = ignored_book_ids or set()
    peers = [
        peer
        for peer in all_books
        if peer.id != book.id and peer.id not in ignored_book_ids and getattr(peer, "deleted_at", None) is None
    ]
    for suggestion in suggestions:
        identifiers = _stable_remote_identifiers(suggestion.remote_ids)
        if not suggestion.matched or not identifiers:
            continue
        duplicate_peer = next(
            (peer for peer in peers if identifiers & _stable_remote_identifiers(peer.metadata_remote_ids)),
            None,
        )
        if duplicate_peer is None:
            continue
        issue = (
            f'Remote record is already assigned to "{duplicate_peer.title}" '
            f"(local book #{duplicate_peer.id}); verify this is not the wrong series volume."
        )
        suggestion.match_issues = list(dict.fromkeys([*(suggestion.match_issues or []), issue]))
        suggestion.match_confidence = min(suggestion.match_confidence, 0.89)


def allocate_unique_candidate_suggestions(
    books: list[models.Book],
    candidate_groups: list[list[MetadataSuggestion]],
) -> list[list[MetadataSuggestion]]:
    """Choose a collection-wide one-to-one remote assignment before applying matches."""

    priorities: list[tuple[float, float, int]] = []
    for index, candidates in enumerate(candidate_groups):
        ranked = sorted(
            (candidate for candidate in candidates if candidate.matched),
            key=lambda candidate: (not bool(candidate.match_issues), candidate.match_confidence),
            reverse=True,
        )
        top_score = ranked[0].match_confidence if ranked else 0.0
        runner_up = ranked[1].match_confidence if len(ranked) > 1 else 0.0
        priorities.append((top_score - runner_up, top_score, index))

    used_identifiers: dict[tuple[str, str], models.Book] = {}
    allocated: list[list[MetadataSuggestion]] = [list(group) for group in candidate_groups]
    for _margin, _score, group_index in sorted(priorities, reverse=True):
        book = books[group_index]
        ranked = sorted(
            allocated[group_index],
            key=lambda candidate: (not bool(candidate.match_issues), candidate.match_confidence),
            reverse=True,
        )
        selected: MetadataSuggestion | None = None
        for candidate in ranked:
            if not candidate.matched:
                continue
            identifiers = _stable_remote_identifiers(candidate.remote_ids)
            if identifiers and any(identifier in used_identifiers for identifier in identifiers):
                owner_titles = ", ".join(
                    sorted(
                        {
                            f'"{used_identifiers[identifier].title}"'
                            for identifier in identifiers
                            if identifier in used_identifiers
                        }
                    )
                )
                issue = f"Collection-wide assignment reserved this remote record for {owner_titles}."
                candidate.match_issues = list(dict.fromkeys([*(candidate.match_issues or []), issue]))
                candidate.match_confidence = min(candidate.match_confidence, 0.89)
                continue
            selected = candidate
            for identifier in identifiers:
                used_identifiers[identifier] = book
            break
        if selected is not None:
            for alternative in ranked:
                if alternative is selected or not alternative.matched:
                    continue
                alternative_identifiers = _stable_remote_identifiers(alternative.remote_ids)
                conflicting_owners = {
                    used_identifiers[identifier].id: used_identifiers[identifier]
                    for identifier in alternative_identifiers
                    if identifier in used_identifiers and used_identifiers[identifier].id != book.id
                }
                if not conflicting_owners:
                    continue
                owner_titles = ", ".join(sorted({f'"{owner.title}"' for owner in conflicting_owners.values()}))
                issue = f"Collection-wide assignment reserved this remote record for {owner_titles}."
                alternative.match_issues = list(dict.fromkeys([*(alternative.match_issues or []), issue]))
                alternative.match_confidence = min(alternative.match_confidence, 0.89)
            allocated[group_index] = [selected, *(candidate for candidate in ranked if candidate is not selected)]
        else:
            allocated[group_index] = ranked
    return allocated


def _compact_metadata_details(**values: Any) -> dict[str, Any]:
    return {
        key: value.strip() if isinstance(value, str) else value
        for key, value in values.items()
        if value is not None and (not isinstance(value, str) or value.strip())
    }


def _safe_series_index(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _series_metadata_details(
    title: str,
    *,
    series: Any = None,
    series_index: Any = None,
) -> dict[str, Any]:
    raw_series = _first_list_value(series)
    series_name = str(raw_series).strip() if raw_series is not None else ""
    resolved_index = _safe_series_index(_first_list_value(series_index))
    inferred_series, inferred_index = _infer_series_metadata(title, series_name)
    return _compact_metadata_details(
        series=series_name or inferred_series,
        series_index=resolved_index or inferred_index,
    )


def _suggestion_match_issues(
    book: models.Book,
    *,
    remote_title: str,
    metadata_details: dict[str, Any],
) -> list[str]:
    return _series_match_issues(
        local_title=book.title,
        local_series=book.series or "",
        local_series_index=book.series_index,
        remote_title=remote_title,
        remote_series=str(metadata_details.get("series") or ""),
        remote_series_index=metadata_details.get("series_index"),
    )


def _description_value(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split()) or None
    if isinstance(value, dict) and isinstance(value.get("value"), str):
        return " ".join(BeautifulSoup(value["value"], "html.parser").get_text(" ", strip=True).split()) or None
    return None


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


def _google_books_metadata_details(volume: dict[str, Any]) -> dict[str, Any]:
    volume_info = _extract_google_volume_info(volume)
    image_links = volume_info.get("imageLinks")
    if not isinstance(image_links, dict):
        image_links = {}
    cover_url = next(
        (
            image_links.get(key)
            for key in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail")
            if image_links.get(key)
        ),
        None,
    )
    page_count = volume_info.get("printedPageCount") or volume_info.get("pageCount")
    series_info = volume_info.get("seriesInfo")
    if not isinstance(series_info, dict):
        series_info = {}
    volume_series = series_info.get("volumeSeries") or []
    if not isinstance(volume_series, list):
        volume_series = []
    order_number = None
    if volume_series and isinstance(volume_series[0], dict):
        order_number = volume_series[0].get("orderNumber")
        if isinstance(order_number, dict):
            order_number = order_number.get("number") or order_number.get("value")
    series_index = _safe_series_index(order_number) or _safe_series_index(series_info.get("bookDisplayNumber"))
    series_details = _series_metadata_details(
        str(volume_info.get("title") or ""),
        series=series_info.get("shortSeriesBookTitle"),
        series_index=series_index,
    )
    return _compact_metadata_details(
        subtitle=volume_info.get("subtitle"),
        description=_description_value(volume_info.get("description")),
        publisher=volume_info.get("publisher"),
        published_date=volume_info.get("publishedDate"),
        language=volume_info.get("language"),
        page_count=page_count if isinstance(page_count, int) and page_count > 0 else None,
        cover_url=cover_url,
        **series_details,
    )


def _google_books_doc(volume: dict[str, Any]) -> dict[str, Any]:
    volume_info = _extract_google_volume_info(volume)
    return {
        "title": volume_info.get("title", ""),
        "author_name": volume_info.get("authors") or [],
    }


def _score_google_books_volume(book: models.Book, volume: dict[str, Any]) -> float:
    volume_doc = _google_books_doc(volume)
    authors = volume_doc.get("author_name") or []
    if isinstance(authors, str):
        authors = [authors]
    metadata_details = _google_books_metadata_details(volume)
    return _score_metadata_candidate(
        local_title=book.title,
        local_author=book.author,
        remote_title=str(volume_doc.get("title") or ""),
        remote_authors=[str(author) for author in authors if author],
        local_ids=_get_manual_remote_ids(book),
        remote_ids=_extract_google_remote_ids(volume),
        local_series=book.series or "",
        local_series_index=book.series_index,
        remote_series=str(metadata_details.get("series") or ""),
        remote_series_index=metadata_details.get("series_index"),
    )


def _get_manual_remote_ids(book: models.Book) -> dict[str, str]:
    raw_ids = book.metadata_remote_ids or {}
    if not isinstance(raw_ids, dict):
        return {}
    return {key: str(value).strip() for key, value in raw_ids.items() if value is not None and str(value).strip()}


def _fetch_search_docs(params: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _request_json("/search.json", params=params)
    docs = payload.get("docs") or []
    return [doc for doc in docs if isinstance(doc, dict)]


def _fetch_google_books_volumes(query: str) -> list[dict[str, Any]]:
    if not _google_books_enabled():
        return []

    payload = _request_google_books_json("/volumes", params={"q": query, "maxResults": 10})
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


def _collect_search_doc_candidates(
    book: models.Book,
    *,
    local_books_by_author: dict[str, list[models.Book]],
    author_work_cache: dict[str, list[dict[str, Any]]],
    limit: int = DEFAULT_MATCH_CANDIDATE_LIMIT,
) -> list[tuple[dict[str, Any], float]]:
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
        search_variants.append({"title": title_variant, "limit": 10})

    ranked: list[tuple[dict[str, Any], float, float]] = []
    seen_searches: set[tuple[tuple[str, Any], ...]] = set()
    seen_docs: set[str] = set()

    for params in search_variants:
        key = tuple(sorted(params.items()))
        if key in seen_searches:
            continue
        seen_searches.add(key)

        for doc in _fetch_search_docs(params):
            doc_key = str(doc.get("key") or doc.get("cover_edition_key") or doc.get("title") or "")
            if not doc_key or doc_key in seen_docs:
                continue
            score = _score_search_doc(book, doc)
            threshold = 0.68 if preferred_author_keys or manual_remote_ids else 0.72
            if score < threshold:
                continue

            ranking_score = score
            doc_author_keys = doc.get("author_key") or []
            if isinstance(doc_author_keys, str):
                doc_author_keys = [doc_author_keys]
            if preferred_author_keys and any(author_key in preferred_author_keys for author_key in doc_author_keys):
                ranking_score += 0.08
            seen_docs.add(doc_key)
            ranked.append((doc, score, ranking_score))

    manual_work_key = manual_remote_ids.get("open_library_work_key")
    if manual_work_key and manual_work_key not in seen_docs:
        try:
            work_data = _request_json(f"{manual_work_key}.json")
        except requests.RequestException:
            logger.warning("Failed to fetch manually configured Open Library work %s.", manual_work_key)
        else:
            manual_doc = {
                "key": manual_work_key,
                "title": work_data.get("title") or book.title,
                "author_name": [book.author],
                "author_key": [manual_author_key] if manual_author_key else [],
            }
            manual_score = _score_search_doc(book, manual_doc)
            ranked.append((manual_doc, manual_score, manual_score + 0.1))
            seen_docs.add(manual_work_key)

    series_doc, series_score = _fetch_series_context_doc(
        book,
        preferred_author_keys=preferred_author_keys,
        author_work_cache=author_work_cache,
    )
    if series_doc is not None:
        doc_key = str(series_doc.get("key") or series_doc.get("title") or "")
        if doc_key and doc_key not in seen_docs:
            ranked.append((series_doc, series_score, series_score + 0.08))

    ranked.sort(key=lambda item: item[2], reverse=True)
    return [(doc, score) for doc, score, _ranking_score in ranked[:limit]]


def _collect_google_books_matches(
    book: models.Book,
    *,
    limit: int = DEFAULT_MATCH_CANDIDATE_LIMIT,
) -> list[GoogleBooksMatch]:
    if not _google_books_enabled():
        return []

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
        for query in (f'intitle:"{title_variant}" inauthor:"{book.author}"', f'intitle:"{title_variant}"'):
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
        return []

    ranked: list[GoogleBooksMatch] = []
    threshold = 0.70 if manual_remote_ids else 0.72
    for candidate in candidates:
        score = _score_google_books_volume(book, candidate)
        if score < threshold:
            continue
        volume_info = _extract_google_volume_info(candidate)
        authors = volume_info.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        ranked.append(
            GoogleBooksMatch(
                volume_id=str(candidate.get("id")),
                title=str(volume_info.get("title") or book.title),
                authors=[author for author in authors if isinstance(author, str)],
                categories=_google_books_categories(candidate),
                info_link=volume_info.get("infoLink"),
                remote_ids=_extract_google_remote_ids(candidate),
                metadata_details=_google_books_metadata_details(candidate),
                match_confidence=score,
            )
        )

    ranked.sort(key=lambda match: match.match_confidence, reverse=True)
    return ranked[:limit]


def _collect_amazon_matches(
    book: models.Book,
    *,
    limit: int = 3,
) -> list[AmazonMatch]:
    if not _amazon_metadata_enabled():
        return []

    manual_remote_ids = _get_manual_remote_ids(book)
    queries = [manual_remote_ids[key] for key in ("asin", "isbn_13", "isbn_10") if manual_remote_ids.get(key)]
    queries.extend(f"{title_variant} {book.author}".strip() for title_variant in _title_search_variants(book))

    candidates: list[AmazonCandidate] = []
    seen_asins: set[str] = set()
    for query in queries:
        try:
            results = search_amazon(query, limit=5)
        except requests.RequestException:
            logger.warning("Amazon metadata search failed for %s; continuing with other providers.", query)
            continue
        for candidate in results:
            if candidate.asin in seen_asins:
                continue
            seen_asins.add(candidate.asin)
            candidates.append(candidate)

    ranked: list[AmazonMatch] = []
    # Fetch only a few detail pages. Amazon is the slowest and least reliable
    # provider, and the other sources should remain useful if it blocks us.
    for candidate in candidates[: max(limit * 2, 3)]:
        try:
            detailed = enrich_amazon_candidate(candidate)
        except requests.RequestException:
            detailed = candidate
        score = _score_metadata_candidate(
            local_title=book.title,
            local_author=book.author,
            remote_title=detailed.title,
            remote_authors=detailed.authors,
            local_ids=manual_remote_ids,
            remote_ids=detailed.remote_ids,
            local_series=book.series or "",
            local_series_index=book.series_index,
            remote_series=str(detailed.metadata_details.get("series") or ""),
            remote_series_index=detailed.metadata_details.get("series_index"),
        )
        if score < (0.70 if manual_remote_ids else 0.72):
            continue
        ranked.append(
            AmazonMatch(
                asin=detailed.asin,
                title=detailed.title,
                authors=detailed.authors,
                categories=detailed.categories,
                remote_url=detailed.url,
                remote_ids=detailed.remote_ids,
                metadata_details=detailed.metadata_details,
                match_confidence=score,
            )
        )

    ranked.sort(key=lambda match: match.match_confidence, reverse=True)
    return ranked[:limit]


def _fetch_work_data(doc: dict[str, Any]) -> dict[str, Any]:
    key = doc.get("key")
    if not key:
        return {}
    try:
        return _request_json(f"{key}.json")
    except requests.RequestException:
        logger.warning("Failed to fetch Open Library work metadata for %s.", key, exc_info=True)
        return {}


def _first_list_value(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _open_library_metadata_details(doc: dict[str, Any], work_data: dict[str, Any]) -> dict[str, Any]:
    cover_id = doc.get("cover_i") or _first_list_value(work_data.get("covers"))
    title = str(doc.get("title") or work_data.get("title") or "")
    series_details = _series_metadata_details(
        title,
        series=doc.get("series") or work_data.get("series"),
        series_index=doc.get("series_index") or work_data.get("series_index"),
    )
    return _compact_metadata_details(
        description=_description_value(work_data.get("description")),
        publisher=_first_list_value(doc.get("publisher")),
        published_date=work_data.get("first_publish_date") or doc.get("first_publish_year"),
        language=_first_list_value(doc.get("language")),
        page_count=doc.get("number_of_pages_median"),
        cover_url=f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None,
        **series_details,
    )


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


def _build_open_library_suggestion(
    book: models.Book,
    doc: dict[str, Any],
    score: float,
    local_books_by_author: dict[str, list[models.Book]],
    author_work_cache: dict[str, list[dict[str, Any]]],
) -> MetadataSuggestion:
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

    remote_title = str(doc.get("title") or "")
    metadata_details = _open_library_metadata_details(doc, work_data)
    return MetadataSuggestion(
        book=book,
        matched=True,
        source="open_library",
        match_confidence=score,
        remote_title=remote_title,
        remote_author=author_names[0] if author_names else None,
        remote_url=_build_remote_url(doc),
        genre_tags=genre_tags,
        new_genre_tags=new_tags,
        possible_missing_series_books=possible_missing,
        remote_ids=remote_ids,
        metadata_details=metadata_details,
        match_issues=_suggestion_match_issues(
            book,
            remote_title=remote_title,
            metadata_details=metadata_details,
        ),
        note=None if genre_tags or possible_missing else "Matched, but no genre tags or series candidates were found.",
    )


def _build_google_books_suggestion(book: models.Book, match: GoogleBooksMatch) -> MetadataSuggestion:
    genre_tags = _derive_genre_tags(match.categories)
    existing_tags = {tag.casefold() for tag in (book.genre_tags or [])}
    return MetadataSuggestion(
        book=book,
        matched=True,
        source="google_books",
        match_confidence=match.match_confidence,
        remote_title=match.title,
        remote_author=match.authors[0] if match.authors else None,
        remote_url=match.info_link,
        genre_tags=genre_tags,
        new_genre_tags=[tag for tag in genre_tags if tag.casefold() not in existing_tags],
        possible_missing_series_books=[],
        remote_ids=match.remote_ids,
        metadata_details=match.metadata_details,
        match_issues=_suggestion_match_issues(
            book,
            remote_title=match.title,
            metadata_details=match.metadata_details,
        ),
        note=None if genre_tags else "Matched in Google Books, but no genre tags were found.",
    )


def _build_amazon_suggestion(book: models.Book, match: AmazonMatch) -> MetadataSuggestion:
    genre_tags = _derive_genre_tags(match.categories)
    existing_tags = {tag.casefold() for tag in (book.genre_tags or [])}
    return MetadataSuggestion(
        book=book,
        matched=True,
        source="amazon",
        match_confidence=match.match_confidence,
        remote_title=match.title,
        remote_author=match.authors[0] if match.authors else None,
        remote_url=match.remote_url,
        genre_tags=genre_tags,
        new_genre_tags=[tag for tag in genre_tags if tag.casefold() not in existing_tags],
        possible_missing_series_books=[],
        remote_ids=match.remote_ids,
        metadata_details=match.metadata_details,
        match_issues=_suggestion_match_issues(
            book,
            remote_title=match.title,
            metadata_details=match.metadata_details,
        ),
        note=None if genre_tags else "Matched on Amazon, but no genre tags were found.",
    )


def _suggestion_isbns(suggestion: MetadataSuggestion) -> set[str]:
    return {isbn for key in ("isbn_13", "isbn_10") if (isbn := _clean_isbn((suggestion.remote_ids or {}).get(key)))}


def _suggestions_same_record(left: MetadataSuggestion, right: MetadataSuggestion) -> bool:
    left_ids = left.remote_ids or {}
    right_ids = right.remote_ids or {}
    for key in ("google_books_volume_id", "open_library_work_key", "asin"):
        if left_ids.get(key) and left_ids.get(key) == right_ids.get(key):
            return True

    left_isbns = _suggestion_isbns(left)
    right_isbns = _suggestion_isbns(right)
    if left_isbns and right_isbns:
        return bool(left_isbns & right_isbns)

    if _title_similarity(left.remote_title or "", right.remote_title or "") < 0.96:
        return False
    if left.remote_author and right.remote_author:
        return _best_author_similarity(left.remote_author, [right.remote_author]) >= 0.9
    return False


def _merge_sources(*sources: str) -> str:
    found = {part for source in sources for part in source.split("+") if part}
    return "+".join(source for source in ("open_library", "google_books", "amazon") if source in found)


def _merge_matching_suggestions(primary: MetadataSuggestion, corroborating: MetadataSuggestion) -> MetadataSuggestion:
    genre_tags = _merge_genre_tags(primary.genre_tags or [], corroborating.genre_tags or [])
    existing_tags = {tag.casefold() for tag in (primary.book.genre_tags or [])}
    remote_ids = _merge_remote_ids(corroborating.remote_ids or {}, primary.remote_ids or {})
    possible_missing = list(
        dict.fromkeys([*(primary.possible_missing_series_books or []), *(corroborating.possible_missing_series_books or [])])
    )
    merged_source = _merge_sources(primary.source, corroborating.source)
    metadata_details = {
        **(corroborating.metadata_details or {}),
        **(primary.metadata_details or {}),
        "corroborating_sources": merged_source.split("+"),
    }
    match_issues = list(dict.fromkeys([*(primary.match_issues or []), *(corroborating.match_issues or [])]))
    confidence = min(1.0, max(primary.match_confidence, corroborating.match_confidence) + 0.03)
    if len(merged_source.split("+")) >= 2 and not match_issues:
        confidence = max(confidence, 0.98)
    return MetadataSuggestion(
        book=primary.book,
        matched=True,
        source=merged_source,
        match_confidence=confidence,
        remote_title=primary.remote_title or corroborating.remote_title,
        remote_author=primary.remote_author or corroborating.remote_author,
        remote_url=primary.remote_url or corroborating.remote_url,
        genre_tags=genre_tags,
        new_genre_tags=[tag for tag in genre_tags if tag.casefold() not in existing_tags],
        possible_missing_series_books=possible_missing,
        remote_ids=remote_ids,
        metadata_details=metadata_details,
        match_issues=match_issues,
        note=None if genre_tags or possible_missing else primary.note or corroborating.note,
    )


def _consolidate_suggestions(suggestions: list[MetadataSuggestion]) -> list[MetadataSuggestion]:
    ranked = sorted(suggestions, key=lambda suggestion: suggestion.match_confidence, reverse=True)
    consolidated: list[MetadataSuggestion] = []
    for suggestion in ranked:
        existing_index = next(
            (index for index, existing in enumerate(consolidated) if _suggestions_same_record(existing, suggestion)),
            None,
        )
        if existing_index is None:
            consolidated.append(suggestion)
        else:
            consolidated[existing_index] = _merge_matching_suggestions(consolidated[existing_index], suggestion)
    consolidated.sort(key=lambda suggestion: suggestion.match_confidence, reverse=True)
    return consolidated


def _build_suggestions_for_book(
    book: models.Book,
    local_books_by_author: dict[str, list[models.Book]],
    author_work_cache: dict[str, list[dict[str, Any]]],
    *,
    max_candidates: int = DEFAULT_MATCH_CANDIDATE_LIMIT,
    search_identity: Optional[SearchIdentity] = None,
) -> list[MetadataSuggestion]:
    search_book = book
    evidence_note = None
    if search_identity is not None:
        search_book = models.Book(
            id=book.id,
            title=search_identity.title,
            author=search_identity.author,
            series=search_identity.series,
            series_index=search_identity.series_index,
            metadata_remote_ids=search_identity.remote_ids,
        )
        evidence_note = search_identity.evidence_note

    if not search_book.title or not search_book.author or search_book.author.strip().lower() == "pending":
        return [MetadataSuggestion(book=book, matched=False, note="Book is missing stable title/author metadata.")]

    suggestions: list[MetadataSuggestion] = []
    try:
        open_library_candidates = _collect_search_doc_candidates(
            search_book,
            local_books_by_author=local_books_by_author,
            author_work_cache=author_work_cache,
            limit=max_candidates,
        )
    except requests.RequestException:
        logger.warning("Metadata sync request failed for %s by %s; continuing.", book.title, book.author)
        open_library_candidates = []
    suggestions.extend(
        _build_open_library_suggestion(book, doc, score, local_books_by_author, author_work_cache)
        for doc, score in open_library_candidates
    )

    try:
        suggestions.extend(
            _build_google_books_suggestion(book, match)
            for match in _collect_google_books_matches(search_book, limit=max_candidates)
        )
    except requests.RequestException:
        logger.warning("Google Books metadata request failed for %s by %s; continuing.", book.title, book.author)

    try:
        suggestions.extend(_build_amazon_suggestion(book, match) for match in _collect_amazon_matches(search_book))
    except requests.RequestException:
        logger.warning("Amazon metadata request failed for %s by %s; continuing.", book.title, book.author)

    if suggestions:
        consolidated = _consolidate_suggestions(suggestions)[:max_candidates]
        for suggestion in consolidated:
            suggestion.match_issues = list(
                dict.fromkeys(
                    [
                        *(suggestion.match_issues or []),
                        *_suggestion_match_issues(
                            search_book,
                            remote_title=suggestion.remote_title or "",
                            metadata_details=suggestion.metadata_details or {},
                        ),
                    ]
                )
            )
            if suggestion.match_issues:
                suggestion.match_confidence = min(suggestion.match_confidence, 0.89)
        consolidated.sort(key=lambda suggestion: suggestion.match_confidence, reverse=True)
        if evidence_note:
            for suggestion in consolidated:
                suggestion.note = f"Matched using {evidence_note}." + (f" {suggestion.note}" if suggestion.note else "")
        return consolidated

    return [MetadataSuggestion(book=book, matched=False, note="No confident metadata match found across enabled providers.")]


async def _generate_suggestions(
    target_books: list[models.Book],
    all_books: list[models.Book],
    *,
    settings: Optional[models.AudiobookSettings] = None,
) -> list[MetadataSuggestion]:
    local_books_by_author: dict[str, list[models.Book]] = {}
    for book in all_books:
        local_books_by_author.setdefault(_normalize_text(book.author or ""), []).append(book)

    author_work_cache: dict[str, list[dict[str, Any]]] = {}
    identities = [await resolve_search_identity(book, settings) for book in target_books]

    suggestions = await asyncio.to_thread(
        lambda: [
            _build_suggestions_for_book(
                book,
                local_books_by_author,
                author_work_cache,
                max_candidates=1,
                search_identity=identity,
            )[0]
            for book, identity in zip(target_books, identities)
        ]
    )
    for index, (book, identity, suggestion) in enumerate(zip(target_books, identities, suggestions)):
        if suggestion.matched:
            continue
        refined = await refine_unmatched_search_identity(identity, settings)
        if refined is None:
            continue
        refined_identity = SearchIdentity(
            title=refined["title"],
            author=refined["author"],
            series=identity.series,
            series_index=identity.series_index,
            remote_ids=identity.remote_ids,
            evidence_note=f"LLM retry query: {refined['reason']}" if refined["reason"] else "LLM retry query",
            used_llm=True,
            opening_excerpt=identity.opening_excerpt,
        )
        suggestions[index] = (
            await asyncio.to_thread(
                _build_suggestions_for_book,
                book,
                local_books_by_author,
                author_work_cache,
                max_candidates=1,
                search_identity=refined_identity,
            )
        )[0]
    for book, suggestion in zip(target_books, suggestions):
        _annotate_duplicate_assignments(book, [suggestion], all_books)
    suggestions = [
        (await arbitrate_candidate_suggestions(book, identity, [suggestion], settings))[0]
        for book, identity, suggestion in zip(target_books, identities, suggestions)
    ]
    return suggestions


async def _generate_candidate_suggestions(
    target_books: list[models.Book],
    all_books: list[models.Book],
    *,
    max_candidates: int = DEFAULT_MATCH_CANDIDATE_LIMIT,
    settings: Optional[models.AudiobookSettings] = None,
) -> list[list[MetadataSuggestion]]:
    local_books_by_author: dict[str, list[models.Book]] = {}
    for book in all_books:
        local_books_by_author.setdefault(_normalize_text(book.author or ""), []).append(book)

    author_work_cache: dict[str, list[dict[str, Any]]] = {}
    identities = [await resolve_search_identity(book, settings) for book in target_books]

    candidate_groups = await asyncio.to_thread(
        lambda: [
            _build_suggestions_for_book(
                book,
                local_books_by_author,
                author_work_cache,
                max_candidates=max_candidates,
                search_identity=identity,
            )
            for book, identity in zip(target_books, identities)
        ]
    )
    for index, (book, identity, suggestions) in enumerate(zip(target_books, identities, candidate_groups)):
        if any(suggestion.matched for suggestion in suggestions):
            continue
        refined = await refine_unmatched_search_identity(identity, settings)
        if refined is None:
            continue
        refined_identity = SearchIdentity(
            title=refined["title"],
            author=refined["author"],
            series=identity.series,
            series_index=identity.series_index,
            remote_ids=identity.remote_ids,
            evidence_note=f"LLM retry query: {refined['reason']}" if refined["reason"] else "LLM retry query",
            used_llm=True,
            opening_excerpt=identity.opening_excerpt,
        )
        candidate_groups[index] = await asyncio.to_thread(
            _build_suggestions_for_book,
            book,
            local_books_by_author,
            author_work_cache,
            max_candidates=max_candidates,
            search_identity=refined_identity,
        )
    target_ids = {book.id for book in target_books}
    for book, suggestions in zip(target_books, candidate_groups):
        _annotate_duplicate_assignments(
            book,
            suggestions,
            all_books,
            ignored_book_ids=target_ids,
        )
        suggestions.sort(key=lambda suggestion: suggestion.match_confidence, reverse=True)
    candidate_groups = [
        await arbitrate_candidate_suggestions(book, identity, suggestions, settings)
        for book, identity, suggestions in zip(target_books, identities, candidate_groups)
    ]
    return allocate_unique_candidate_suggestions(target_books, candidate_groups)


async def generate_suggestions(
    target_books: list[models.Book],
    all_books: list[models.Book],
    *,
    settings: Optional[models.AudiobookSettings] = None,
) -> list[MetadataSuggestion]:
    return await _generate_suggestions(target_books, all_books, settings=settings)


async def generate_candidate_suggestions(
    target_books: list[models.Book],
    all_books: list[models.Book],
    *,
    max_candidates: int = DEFAULT_MATCH_CANDIDATE_LIMIT,
    settings: Optional[models.AudiobookSettings] = None,
) -> list[list[MetadataSuggestion]]:
    return await _generate_candidate_suggestions(
        target_books,
        all_books,
        max_candidates=max_candidates,
        settings=settings,
    )


def apply_suggestion_to_book(
    book: models.Book,
    suggestion: MetadataSuggestion,
    *,
    source: Optional[str] = None,
    synced_at: Optional[datetime] = None,
    allow_match_issues: bool = False,
) -> bool:
    if not suggestion.matched or (suggestion.match_issues and not allow_match_issues):
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
        **{key: value for key, value in _get_manual_remote_ids(book).items() if key not in KNOWN_REMOTE_ID_KEYS},
        **(suggestion.remote_ids or {}),
    }
    next_metadata_details = {
        **(book.metadata_details or {}),
        **(suggestion.metadata_details or {}),
    } or None

    changed = (
        merged_genres != (book.genre_tags or [])
        or next_remote_ids != (book.metadata_remote_ids or {})
        or next_metadata_details != book.metadata_details
        or book.metadata_sync_source != resolved_source
    )

    book.genre_tags = merged_genres
    book.metadata_remote_ids = next_remote_ids
    book.metadata_details = next_metadata_details
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
    settings = await crud.audiobook.get_audiobook_settings(db)
    suggestions = await _generate_suggestions(target_books, all_books, settings=settings)

    results = [suggestion.to_schema() for suggestion in suggestions]
    return schemas.MetadataSyncPreviewResponse(
        scanned_books=len(target_books),
        matched_books=sum(1 for suggestion in suggestions if suggestion.matched),
        books_with_new_genres=sum(1 for suggestion in suggestions if suggestion.new_genre_tags),
        books_with_missing_series_candidates=sum(1 for suggestion in suggestions if suggestion.possible_missing_series_books),
        results=results,
    )


async def apply_metadata_sync(
    db: AsyncSession,
    book_ids: Optional[list[int]] = None,
) -> schemas.MetadataSyncApplyResponse:
    target_books = await _get_target_books(db, book_ids=book_ids)
    all_books = await crud.get_books(db, limit=100000)
    settings = await crud.audiobook.get_audiobook_settings(db)
    suggestions = await _generate_suggestions(target_books, all_books, settings=settings)

    updated_books = 0
    synced_at = datetime.now(timezone.utc)

    from .book_recovery import add_book_revision, snapshot_book

    for suggestion in suggestions:
        if not suggestion.matched:
            continue

        previous_snapshot = snapshot_book(suggestion.book)
        if apply_suggestion_to_book(suggestion.book, suggestion, source=suggestion.source, synced_at=synced_at):
            add_book_revision(
                db,
                suggestion.book,
                action="metadata_changed",
                summary=f"Applied metadata from {suggestion.source or 'Open Library'}",
                snapshot=previous_snapshot,
            )
            updated_books += 1

    await db.commit()

    return schemas.MetadataSyncApplyResponse(
        scanned_books=len(target_books),
        matched_books=sum(1 for suggestion in suggestions if suggestion.matched),
        updated_books=updated_books,
        books_with_new_genres=sum(1 for suggestion in suggestions if suggestion.new_genre_tags),
        books_with_missing_series_candidates=sum(1 for suggestion in suggestions if suggestion.possible_missing_series_books),
        results=[suggestion.to_schema() for suggestion in suggestions],
    )
