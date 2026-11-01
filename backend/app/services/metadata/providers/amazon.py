"""Amazon search, scoring and suggestion building."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from .... import models
from ....metadata_types import MetadataDetails
from ....metadata_types import metadata_details as validate_metadata_details
from ....metadata_types import remote_identifiers
from ..amazon import AmazonCandidate, enrich_amazon_candidate, search_amazon
from ..clients import amazon_metadata_enabled as _amazon_metadata_enabled
from ..genres import derive_genre_tags as _derive_genre_tags
from ..scoring import score_metadata_candidate as _score_metadata_candidate
from ..suggestion import MetadataSuggestion, book_manual_remote_ids, suggestion_match_issues, title_search_variants

logger = logging.getLogger(__name__)


@dataclass
class AmazonMatch:
    asin: str
    title: str
    authors: list[str]
    categories: list[str]
    remote_url: str
    remote_ids: dict[str, str]
    metadata_details: MetadataDetails
    match_confidence: float


def collect_amazon_matches(
    book: models.Book,
    *,
    limit: int = 3,
) -> list[AmazonMatch]:
    if not _amazon_metadata_enabled():
        return []

    manual_remote_ids = book_manual_remote_ids(book)
    queries = [manual_remote_ids[key] for key in ("asin", "isbn_13", "isbn_10") if manual_remote_ids.get(key)]
    queries.extend(f"{title_variant} {book.author}".strip() for title_variant in title_search_variants(book))

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
            local_title=book.title or "",
            local_author=book.author or "",
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
                metadata_details=validate_metadata_details(detailed.metadata_details),
                match_confidence=score,
            )
        )

    ranked.sort(key=lambda match: match.match_confidence, reverse=True)
    return ranked[:limit]


def build_amazon_suggestion(book: models.Book, match: AmazonMatch) -> MetadataSuggestion:
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
        remote_ids=remote_identifiers(match.remote_ids),
        metadata_details=match.metadata_details,
        match_issues=suggestion_match_issues(
            book,
            remote_title=match.title,
            metadata_details=match.metadata_details,
        ),
        note=None if genre_tags else "Matched on Amazon, but no genre tags were found.",
    )
