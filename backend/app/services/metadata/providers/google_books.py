"""Google Books search, scoring and suggestion building."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

from .... import models
from ....metadata_types import (
    MetadataDetails,
    remote_identifiers,
)
from ..clients import google_books_enabled as _google_books_enabled
from ..clients import request_google_books_json as _request_google_books_json
from ..genres import derive_genre_tags as _derive_genre_tags
from ..responses import (
    GOOGLE_VOLUME,
    GoogleVolume,
    OpenLibraryDoc,
    SeriesInfo,
    VolumeInfo,
    valid_record,
    valid_records,
)
from ..scoring import normalize_text as _normalize_text
from ..scoring import score_metadata_candidate as _score_metadata_candidate
from ..suggestion import (
    DEFAULT_MATCH_CANDIDATE_LIMIT,
    MetadataSuggestion,
    book_manual_remote_ids,
    compact_metadata_details,
    description_value,
    safe_series_index,
    series_metadata_details,
    suggestion_match_issues,
    title_search_variants,
)

logger = logging.getLogger(__name__)


@dataclass
class GoogleBooksMatch:
    volume_id: str
    title: str
    authors: list[str]
    categories: list[str]
    info_link: Optional[str]
    remote_ids: dict[str, str]
    metadata_details: MetadataDetails
    match_confidence: float


def _extract_google_volume_info(volume: GoogleVolume) -> VolumeInfo:
    volume_info = volume.get("volumeInfo")
    return volume_info if isinstance(volume_info, dict) else {}


def _extract_google_remote_ids(volume: GoogleVolume) -> dict[str, str]:
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


def _google_books_categories(volume: GoogleVolume) -> list[str]:
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


def _google_books_metadata_details(volume: GoogleVolume) -> MetadataDetails:
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
    series_info: SeriesInfo = volume_info.get("seriesInfo") or {}
    volume_series = series_info.get("volumeSeries") or []
    if not isinstance(volume_series, list):
        volume_series = []
    order_number = None
    if volume_series and isinstance(volume_series[0], dict):
        order_number = volume_series[0].get("orderNumber")
        if isinstance(order_number, dict):
            order_number = order_number.get("number") or order_number.get("value")
    series_index = safe_series_index(order_number) or safe_series_index(series_info.get("bookDisplayNumber"))
    series_details = series_metadata_details(
        str(volume_info.get("title") or ""),
        series=series_info.get("shortSeriesBookTitle"),
        series_index=series_index,
    )
    return compact_metadata_details(
        subtitle=volume_info.get("subtitle"),
        description=description_value(volume_info.get("description")),
        publisher=volume_info.get("publisher"),
        published_date=volume_info.get("publishedDate"),
        language=volume_info.get("language"),
        page_count=page_count if isinstance(page_count, int) and page_count > 0 else None,
        cover_url=cover_url,
        **series_details,
    )


def _google_books_doc(volume: GoogleVolume) -> OpenLibraryDoc:
    volume_info = _extract_google_volume_info(volume)
    return {
        "title": volume_info.get("title", ""),
        "author_name": volume_info.get("authors") or [],
    }


def _score_google_books_volume(book: models.Book, volume: GoogleVolume) -> float:
    volume_doc = _google_books_doc(volume)
    authors = volume_doc.get("author_name") or []
    if isinstance(authors, str):
        authors = [authors]
    metadata_details = _google_books_metadata_details(volume)
    return _score_metadata_candidate(
        local_title=book.title or "",
        local_author=book.author or "",
        remote_title=str(volume_doc.get("title") or ""),
        remote_authors=[str(author) for author in authors if author],
        local_ids=book_manual_remote_ids(book),
        remote_ids=_extract_google_remote_ids(volume),
        local_series=book.series or "",
        local_series_index=book.series_index,
        remote_series=str(metadata_details.get("series") or ""),
        remote_series_index=metadata_details.get("series_index"),
    )


def _fetch_google_books_volumes(query: str) -> list[GoogleVolume]:
    if not _google_books_enabled():
        return []

    payload = _request_google_books_json("/volumes", params={"q": query, "maxResults": 10})
    return valid_records(payload, "items", GOOGLE_VOLUME)


def _fetch_google_books_volume_by_id(volume_id: str) -> Optional[GoogleVolume]:
    if not _google_books_enabled() or not volume_id.strip():
        return None

    payload = _request_google_books_json(f"/volumes/{volume_id.strip()}")
    return valid_record(payload, GOOGLE_VOLUME) if payload else None


def collect_google_books_matches(
    book: models.Book,
    *,
    limit: int = DEFAULT_MATCH_CANDIDATE_LIMIT,
) -> list[GoogleBooksMatch]:
    if not _google_books_enabled():
        return []

    manual_remote_ids = book_manual_remote_ids(book)
    candidates: list[GoogleVolume] = []
    seen_ids: set[str] = set()

    manual_volume_id = manual_remote_ids.get("google_books_volume_id")
    if manual_volume_id:
        try:
            volume = _fetch_google_books_volume_by_id(manual_volume_id)
        except requests.RequestException:
            logger.warning("Failed to fetch Google Books volume metadata for %s.", manual_volume_id)
            volume = None
        if volume and (volume_id := volume.get("id")):
            seen_ids.add(volume_id)
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

    for title_variant in title_search_variants(book):
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


def build_google_books_suggestion(book: models.Book, match: GoogleBooksMatch) -> MetadataSuggestion:
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
        remote_ids=remote_identifiers(match.remote_ids),
        metadata_details=match.metadata_details,
        match_issues=suggestion_match_issues(
            book,
            remote_title=match.title,
            metadata_details=match.metadata_details,
        ),
        note=None if genre_tags else "Matched in Google Books, but no genre tags were found.",
    )
