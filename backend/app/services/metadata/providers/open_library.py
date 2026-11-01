"""Open Library search, scoring and suggestion building."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from .... import models
from ....metadata_types import (
    MetadataDetails,
    remote_identifiers,
)
from ...series import detect_series_from_titles
from ..clients import OPEN_LIBRARY_BASE_URL
from ..clients import request_open_library_json as _request_json
from ..genres import derive_genre_tags as _derive_genre_tags
from ..responses import (
    OPEN_LIBRARY_DOC,
    OPEN_LIBRARY_WORK,
    OpenLibraryDoc,
    OpenLibraryWork,
    valid_record,
    valid_records,
)
from ..scoring import normalize_series as _normalize_series
from ..scoring import normalize_text as _normalize_text
from ..scoring import score_metadata_candidate as _score_metadata_candidate
from ..suggestion import (
    DEFAULT_MATCH_CANDIDATE_LIMIT,
    MetadataSuggestion,
    book_manual_remote_ids,
    compact_metadata_details,
    description_value,
    first_list_value,
    series_metadata_details,
    suggestion_match_issues,
    title_search_variants,
)

logger = logging.getLogger(__name__)


def _score_search_doc(book: models.Book, doc: OpenLibraryDoc) -> float:
    author_names = doc.get("author_name") or []
    if isinstance(author_names, str):
        author_names = [author_names]
    author_keys = doc.get("author_key") or []
    if isinstance(author_keys, str):
        author_keys = [author_keys]
    remote_title = str(doc.get("title") or "")
    series_details = series_metadata_details(
        remote_title,
        series=doc.get("series"),
        series_index=doc.get("series_index"),
    )
    return _score_metadata_candidate(
        local_title=book.title or "",
        local_author=book.author or "",
        remote_title=remote_title,
        remote_authors=[str(author) for author in author_names if author],
        local_ids=book_manual_remote_ids(book),
        remote_ids=_extract_remote_ids(doc, str(author_keys[0]) if author_keys else None),
        local_series=book.series or "",
        local_series_index=book.series_index,
        remote_series=str(series_details.get("series") or ""),
        remote_series_index=series_details.get("series_index"),
    )


def _extract_subjects(doc: OpenLibraryDoc, work_data: OpenLibraryWork) -> list[str]:
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
        _normalize_text(local_book.title or "")
        for local_book in local_books_by_author.get(_normalize_text(book.author or ""), [])
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
    docs: list[OpenLibraryDoc],
    *,
    preferred_author_keys: Optional[set[str]] = None,
) -> tuple[Optional[OpenLibraryDoc], float]:
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


def _build_remote_url(doc: OpenLibraryDoc) -> Optional[str]:
    key = doc.get("key")
    if not key:
        return None
    return f"{OPEN_LIBRARY_BASE_URL}{key}"


def _extract_remote_ids(doc: OpenLibraryDoc, author_key: Optional[str]) -> dict[str, str]:
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


def _fetch_search_docs(params: dict[str, str | int | None]) -> list[OpenLibraryDoc]:
    payload = _request_json("/search.json", params=params)
    return valid_records(payload, "docs", OPEN_LIBRARY_DOC)


def _series_peer_author_keys(
    book: models.Book,
    local_books_by_author: dict[str, list[models.Book]],
) -> set[str]:
    if not book.series:
        return set()

    author_books = local_books_by_author.get(_normalize_text(book.author or ""), [])
    keys: set[str] = set()
    for local_book in author_books:
        if local_book.id == book.id or not local_book.series:
            continue
        if _normalize_series(local_book.series) != _normalize_series(book.series):
            continue
        remote_ids = book_manual_remote_ids(local_book)
        author_key = remote_ids.get("open_library_author_key")
        if author_key:
            keys.add(author_key)
    return keys


def _fetch_series_context_doc(
    book: models.Book,
    *,
    preferred_author_keys: set[str],
    author_work_cache: dict[str, list[OpenLibraryWork]],
) -> tuple[Optional[OpenLibraryDoc], float]:
    if not preferred_author_keys:
        return None, 0.0

    candidate_entries: list[OpenLibraryDoc] = []
    for author_key in preferred_author_keys:
        entries = _fetch_author_work_entries(author_key, author_work_cache)
        if not entries:
            continue

        author_work_titles = [title for entry in entries if (title := entry.get("title"))]
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
                    "author_name": [book.author] if book.author else [],
                    "author_key": [author_key],
                }
            )

    best_doc = None
    best_score = 0.0
    for variant in title_search_variants(book):
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


def collect_search_doc_candidates(
    book: models.Book,
    *,
    local_books_by_author: dict[str, list[models.Book]],
    author_work_cache: dict[str, list[OpenLibraryWork]],
    limit: int = DEFAULT_MATCH_CANDIDATE_LIMIT,
) -> list[tuple[OpenLibraryDoc, float]]:
    manual_remote_ids = book_manual_remote_ids(book)
    preferred_author_keys = _series_peer_author_keys(book, local_books_by_author)
    manual_author_key = manual_remote_ids.get("open_library_author_key")
    if manual_author_key:
        preferred_author_keys.add(manual_author_key)

    search_variants: list[dict[str, str | int | None]] = []
    if manual_remote_ids.get("isbn_13"):
        search_variants.append({"isbn": manual_remote_ids["isbn_13"], "limit": 5})
    if manual_remote_ids.get("isbn_10"):
        search_variants.append({"isbn": manual_remote_ids["isbn_10"], "limit": 5})
    for title_variant in title_search_variants(book):
        search_variants.append({"title": title_variant, "author": book.author, "limit": 5})
        search_variants.append({"title": title_variant, "limit": 10})

    ranked: list[tuple[OpenLibraryDoc, float, float]] = []
    seen_searches: set[tuple[tuple[str, str | int | None], ...]] = set()
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
            manual_work = valid_record(_request_json(f"{manual_work_key}.json"), OPEN_LIBRARY_WORK)
        except requests.RequestException:
            logger.warning("Failed to fetch manually configured Open Library work %s.", manual_work_key)
        else:
            if manual_work is not None:
                manual_doc: OpenLibraryDoc = {
                    "key": manual_work_key,
                    "title": manual_work.get("title") or book.title,
                    "author_name": [book.author] if book.author else [],
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


def _fetch_work_data(doc: OpenLibraryDoc) -> OpenLibraryWork:
    key = doc.get("key")
    if not key:
        return {}
    try:
        return valid_record(_request_json(f"{key}.json"), OPEN_LIBRARY_WORK) or {}
    except requests.RequestException:
        logger.warning("Failed to fetch Open Library work metadata for %s.", key, exc_info=True)
        return {}


def _open_library_metadata_details(doc: OpenLibraryDoc, work_data: OpenLibraryWork) -> MetadataDetails:
    cover_id = doc.get("cover_i") or first_list_value(work_data.get("covers"))
    title = str(doc.get("title") or work_data.get("title") or "")
    series_details = series_metadata_details(
        title,
        series=doc.get("series") or work_data.get("series"),
        series_index=doc.get("series_index") or work_data.get("series_index"),
    )
    return compact_metadata_details(
        description=description_value(work_data.get("description")),
        publisher=first_list_value(doc.get("publisher")),
        published_date=work_data.get("first_publish_date") or doc.get("first_publish_year"),
        language=first_list_value(doc.get("language")),
        page_count=doc.get("number_of_pages_median"),
        cover_url=f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg" if cover_id else None,
        **series_details,
    )


def _fetch_author_work_entries(
    author_key: Optional[str],
    author_work_cache: dict[str, list[OpenLibraryWork]],
) -> list[OpenLibraryWork]:
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

    entries = valid_records(payload, "entries", OPEN_LIBRARY_WORK)
    normalized_entries: list[OpenLibraryWork] = [
        {"key": entry.get("key"), "title": title.strip()}
        for entry in entries
        if (title := entry.get("title")) and title.strip()
    ]
    author_work_cache[author_key] = normalized_entries
    return normalized_entries


def build_open_library_suggestion(
    book: models.Book,
    doc: OpenLibraryDoc,
    score: float,
    local_books_by_author: dict[str, list[models.Book]],
    author_work_cache: dict[str, list[OpenLibraryWork]],
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
    author_work_titles = [title for entry in author_work_entries if (title := entry.get("title"))]
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
        remote_ids=remote_identifiers(remote_ids),
        metadata_details=metadata_details,
        match_issues=suggestion_match_issues(
            book,
            remote_title=remote_title,
            metadata_details=metadata_details,
        ),
        note=None if genre_tags or possible_missing else "Matched, but no genre tags or series candidates were found.",
    )
