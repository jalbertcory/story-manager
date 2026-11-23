"""Apple Books search (iTunes Search API), scoring and suggestion building."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

from .... import models
from ....metadata_types import MetadataDetails, remote_identifiers
from ..clients import apple_books_enabled as _apple_books_enabled
from ..clients import request_apple_books_json as _request_apple_books_json
from ..genres import derive_genre_tags as _derive_genre_tags
from ..responses import APPLE_BOOK, AppleBook, valid_records
from ..scoring import score_metadata_candidate as _score_metadata_candidate
from ..suggestion import (
    DEFAULT_MATCH_CANDIDATE_LIMIT,
    MetadataSuggestion,
    book_manual_remote_ids,
    compact_metadata_details,
    description_value,
    series_metadata_details,
    suggestion_match_issues,
    title_search_variants,
)

logger = logging.getLogger(__name__)

# Apple serves artwork at any requested size; the API only links a thumbnail.
_ARTWORK_SIZE_RE = re.compile(r"/\d+x\d+(bb)?\.(jpg|jpeg|png)$", re.IGNORECASE)
_COVER_SIZE = "1200x1200"
# Storefront categories that say nothing about the story itself.
_GENERIC_GENRES = {"books", "ebooks"}


@dataclass
class AppleBooksMatch:
    apple_books_id: str
    title: str
    authors: list[str]
    categories: list[str]
    remote_url: Optional[str]
    remote_ids: dict[str, str]
    metadata_details: MetadataDetails
    match_confidence: float


def _apple_books_id(record: AppleBook) -> str:
    track_id = record.get("trackId")
    return str(track_id) if isinstance(track_id, int) and not isinstance(track_id, bool) else ""


def _full_size_cover_url(artwork_url: object) -> Optional[str]:
    if not isinstance(artwork_url, str) or not artwork_url.startswith("https://"):
        return None
    return _ARTWORK_SIZE_RE.sub(lambda match: f"/{_COVER_SIZE}bb.{match.group(2)}", artwork_url)


def _apple_books_authors(record: AppleBook) -> list[str]:
    raw = str(record.get("artistName") or "")
    return [author.strip() for author in re.split(r"\s*(?:,|&| and )\s*", raw) if author.strip()]


def _apple_books_categories(record: AppleBook) -> list[str]:
    genres = record.get("genres") or []
    return [genre.strip() for genre in genres if genre.strip() and genre.strip().casefold() not in _GENERIC_GENRES]


def _apple_books_metadata_details(record: AppleBook) -> MetadataDetails:
    released = str(record.get("releaseDate") or "")
    return compact_metadata_details(
        description=description_value(record.get("description")),
        published_date=released[:10] or None,
        cover_url=_full_size_cover_url(record.get("artworkUrl100")),
        **series_metadata_details(str(record.get("trackName") or "")),
    )


def _search_apple_books(term: str) -> list[AppleBook]:
    payload = _request_apple_books_json("/search", params={"term": term, "media": "ebook", "entity": "ebook", "limit": 10})
    return valid_records(payload, "results", APPLE_BOOK)


def _lookup_apple_book(apple_books_id: str) -> list[AppleBook]:
    if not apple_books_id.isdigit():
        return []
    payload = _request_apple_books_json("/lookup", params={"id": apple_books_id})
    return valid_records(payload, "results", APPLE_BOOK)


def collect_apple_books_matches(
    book: models.Book,
    *,
    limit: int = DEFAULT_MATCH_CANDIDATE_LIMIT,
) -> list[AppleBooksMatch]:
    if not _apple_books_enabled():
        return []

    manual_remote_ids = book_manual_remote_ids(book)
    candidates: list[AppleBook] = []
    seen_ids: set[str] = set()

    def add(records: list[AppleBook]) -> None:
        for record in records:
            record_id = _apple_books_id(record)
            if record_id and record_id not in seen_ids and record.get("trackName"):
                seen_ids.add(record_id)
                candidates.append(record)

    manual_id = manual_remote_ids.get("apple_books_id")
    if manual_id:
        try:
            add(_lookup_apple_book(manual_id))
        except requests.RequestException:
            logger.warning("Failed to look up Apple Books ID %s.", manual_id)

    # One search per title variant, stopping at the first that finds anything,
    # keeps a library-wide sync inside Apple's rate limit.
    if not candidates:
        for title_variant in title_search_variants(book):
            try:
                add(_search_apple_books(f"{title_variant} {book.author or ''}".strip()))
            except requests.RequestException:
                logger.warning("Failed to search Apple Books for %s by %s.", title_variant, book.author)
                continue
            if candidates:
                break

    ranked: list[AppleBooksMatch] = []
    threshold = 0.70 if manual_remote_ids else 0.72
    for candidate in candidates:
        record_id = _apple_books_id(candidate)
        title = str(candidate.get("trackName") or "")
        authors = _apple_books_authors(candidate)
        remote_ids = {"apple_books_id": record_id}
        details = _apple_books_metadata_details(candidate)
        score = _score_metadata_candidate(
            local_title=book.title or "",
            local_author=book.author or "",
            remote_title=title,
            remote_authors=authors,
            local_ids=manual_remote_ids,
            remote_ids=remote_ids,
            local_series=book.series or "",
            local_series_index=book.series_index,
            remote_series=str(details.get("series") or ""),
            remote_series_index=details.get("series_index"),
        )
        if score < threshold:
            continue
        ranked.append(
            AppleBooksMatch(
                apple_books_id=record_id,
                title=title,
                authors=authors,
                categories=_apple_books_categories(candidate),
                remote_url=candidate.get("trackViewUrl"),
                remote_ids=remote_ids,
                metadata_details=details,
                match_confidence=score,
            )
        )

    ranked.sort(key=lambda match: match.match_confidence, reverse=True)
    return ranked[:limit]


def build_apple_books_suggestion(book: models.Book, match: AppleBooksMatch) -> MetadataSuggestion:
    genre_tags = _derive_genre_tags(match.categories)
    existing_tags = {tag.casefold() for tag in (book.genre_tags or [])}
    return MetadataSuggestion(
        book=book,
        matched=True,
        source="apple_books",
        match_confidence=match.match_confidence,
        remote_title=match.title,
        remote_author=match.authors[0] if match.authors else None,
        remote_url=match.remote_url,
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
        note=None if genre_tags else "Matched in Apple Books, but no genre tags were found.",
    )
