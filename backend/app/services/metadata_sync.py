"""Online metadata enrichment and preview/apply flows for books."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Optional

import requests
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models, schemas
from ..metadata_types import metadata_details as validate_metadata_details
from ..metadata_types import metadata_json, remote_identifiers, searchable_identifiers
from .metadata.arbitration import arbitrate_candidate_suggestions, refine_unmatched_search_identity
from .metadata.evidence import SearchIdentity, resolve_search_identity
from .metadata.genres import merge_genre_tags as _merge_genre_tags
from .metadata.providers.amazon import build_amazon_suggestion as _build_amazon_suggestion
from .metadata.providers.amazon import collect_amazon_matches as _collect_amazon_matches
from .metadata.providers.google_books import build_google_books_suggestion as _build_google_books_suggestion
from .metadata.providers.google_books import collect_google_books_matches as _collect_google_books_matches
from .metadata.providers.open_library import build_open_library_suggestion as _build_open_library_suggestion
from .metadata.providers.open_library import collect_search_doc_candidates as _collect_search_doc_candidates
from .metadata.responses import OpenLibraryWork
from .metadata.scoring import best_author_similarity as _best_author_similarity
from .metadata.scoring import canonical_isbn as _canonical_isbn
from .metadata.scoring import clean_isbn as _clean_isbn
from .metadata.scoring import normalize_text as _normalize_text
from .metadata.scoring import title_similarity as _title_similarity
from .metadata.suggestion import DEFAULT_MATCH_CANDIDATE_LIMIT, MetadataSuggestion
from .metadata.suggestion import suggestion_match_issues as _suggestion_match_issues

logger = logging.getLogger(__name__)

AUTO_APPROVE_THRESHOLD = 0.92
PROPOSAL_THRESHOLD = 0.75
KNOWN_REMOTE_ID_KEYS = {
    "asin",
    "google_books_volume_id",
    "isbn_10",
    "isbn_13",
    "open_library_author_key",
    "open_library_edition_key",
    "open_library_work_key",
}


def _merge_remote_ids(*groups: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    merged: dict[str, JsonValue] = {}
    for group in groups:
        merged.update(group)
    return merged


def _stable_remote_identifiers(remote_ids: dict[str, JsonValue] | None) -> set[tuple[str, str]]:
    identifiers_by_name = searchable_identifiers(remote_ids)
    identifiers = {
        (key, str(identifiers_by_name[key]).strip())
        for key in ("google_books_volume_id", "open_library_work_key", "asin")
        if identifiers_by_name.get(key) and str(identifiers_by_name[key]).strip()
    }
    identifiers.update(
        ("isbn", normalized) for key in ("isbn_10", "isbn_13") if (normalized := _canonical_isbn(identifiers_by_name.get(key)))
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
    metadata_details = validate_metadata_details(
        {
            **(corroborating.metadata_details or {}),
            **(primary.metadata_details or {}),
            "corroborating_sources": merged_source.split("+"),
        }
    )
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
        remote_ids=remote_identifiers(remote_ids),
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
    author_work_cache: dict[str, list[OpenLibraryWork]],
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

    author_work_cache: dict[str, list[OpenLibraryWork]] = {}
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
            title=refined.title,
            author=refined.author,
            series=identity.series,
            series_index=identity.series_index,
            remote_ids=identity.remote_ids,
            evidence_note=f"LLM retry query: {refined.reason}" if refined.reason else "LLM retry query",
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

    author_work_cache: dict[str, list[OpenLibraryWork]] = {}
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
            title=refined.title,
            author=refined.author,
            series=identity.series,
            series_index=identity.series_index,
            remote_ids=identity.remote_ids,
            evidence_note=f"LLM retry query: {refined.reason}" if refined.reason else "LLM retry query",
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

    validated_ids = remote_identifiers(suggestion.remote_ids or {})
    validated_details = (
        validate_metadata_details(suggestion.metadata_details) if suggestion.metadata_details is not None else None
    )
    resolved_source = source or suggestion.source or "open_library"
    synced_timestamp = synced_at or datetime.now(timezone.utc)
    merged_genres = sorted(
        {
            *(tag for tag in (book.genre_tags or [])),
            *(tag for tag in (suggestion.genre_tags or [])),
        },
        key=str.casefold,
    )
    stored_ids = book.metadata_remote_ids if isinstance(book.metadata_remote_ids, dict) else {}
    next_remote_ids = {
        **{key: value for key, value in stored_ids.items() if key not in KNOWN_REMOTE_ID_KEYS},
        **validated_ids,
    }
    next_metadata_details = {
        **(book.metadata_details or {}),
        **(metadata_json(validated_details) if validated_details is not None else {}),
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
