"""Match Libation backup folders to library books before audio is uploaded."""

from __future__ import annotations

import re
from difflib import get_close_matches
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audiobook_schemas import (
    LibationBackupMatchResponse,
    LibationBackupPreviewResponse,
    LibationBookOptionResponse,
    LibationExistingAudioResponse,
)
from ..models import Book, ImportedAudiobook
from .audiobook_import import libation_backup_groups
from .book_matching import title_match_keys as _libation_title_keys
from .metadata.scoring import normalize_text, title_similarity


def _normalized_identifier(value: Any) -> str:
    return re.sub(r"[^0-9a-z]", "", str(value).casefold())


def _identifier_match_keys(value: Any) -> set[str]:
    normalized = _normalized_identifier(value)
    keys = {normalized} if normalized else set()
    if len(normalized) == 10 and re.fullmatch(r"\d{9}[\dx]", normalized):
        digits = [*(int(character) for character in normalized[:9]), 10 if normalized[-1] == "x" else int(normalized[-1])]
        if sum((10 - index) * digit for index, digit in enumerate(digits)) % 11 == 0:
            isbn13_base = f"978{normalized[:9]}"
            check_digit = (
                10 - sum((1 if index % 2 == 0 else 3) * int(digit) for index, digit in enumerate(isbn13_base)) % 10
            ) % 10
            keys.add(f"{isbn13_base}{check_digit}")
    elif len(normalized) == 13 and normalized.startswith("978") and normalized.isdigit():
        if sum((1 if index % 2 == 0 else 3) * int(digit) for index, digit in enumerate(normalized)) % 10 == 0:
            isbn10_base = normalized[3:12]
            check_value = (-sum((10 - index) * int(digit) for index, digit in enumerate(isbn10_base))) % 11
            keys.add(f"{isbn10_base}{'x' if check_value == 10 else check_value}")
    return keys


def _book_identifier_values(book: Book) -> set[str]:
    values: set[str] = set()
    for value in (book.metadata_remote_ids or {}).values():
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, (str, int)):
                values.update(_identifier_match_keys(candidate))
    return values


def _single_book_match(candidates: list[Book]) -> tuple[Book | None, bool]:
    unique = {book.id: book for book in candidates}
    if len(unique) == 1:
        return next(iter(unique.values())), False
    return None, len(unique) > 1


def _existing_audio_options(editions: list[ImportedAudiobook]) -> list[LibationExistingAudioResponse]:
    return [
        LibationExistingAudioResponse(
            edition_id=edition.id,
            name=edition.name,
            status=edition.status,
            source_type=edition.source_type,
            product_id=edition.asin,
        )
        for edition in editions
    ]


def _book_option(
    book: Book,
    *,
    match_score: float | None = None,
    existing_editions: list[ImportedAudiobook] | None = None,
) -> LibationBookOptionResponse:
    return LibationBookOptionResponse(
        book_id=book.id,
        book_title=book.title or "Untitled book",
        book_author=book.author,
        book_series=book.series,
        match_score=round(match_score, 3) if match_score is not None else None,
        existing_audiobooks=_existing_audio_options(existing_editions or []),
    )


def _suggested_libation_books(
    source_title: str,
    books_by_title_variant: dict[str, list[Book]],
    library_title_keys: tuple[str, ...],
    imports_by_book: dict[int, list[ImportedAudiobook]],
) -> list[LibationBookOptionResponse]:
    scores_by_book: dict[int, tuple[float, Book]] = {}
    for source_key in _libation_title_keys(source_title):
        for library_key in get_close_matches(source_key, library_title_keys, n=10, cutoff=0.6):
            score = title_similarity(source_key, library_key)
            for book in books_by_title_variant[library_key]:
                previous = scores_by_book.get(book.id)
                if previous is None or score > previous[0]:
                    scores_by_book[book.id] = (score, book)
    scored = sorted(
        scores_by_book.values(),
        key=lambda item: (-item[0], (item[1].title or "").casefold(), item[1].id),
    )
    if not scored or scored[0][0] < 0.6:
        return []
    minimum = max(0.6, scored[0][0] - 0.12)
    return [
        _book_option(
            book,
            match_score=score,
            existing_editions=imports_by_book.get(book.id, []),
        )
        for score, book in scored[:3]
        if score >= minimum
    ]


async def preview_libation_backup(source_paths: list[str], db: AsyncSession) -> LibationBackupPreviewResponse:
    """Match a path-only Libation backup manifest before any audio is uploaded."""
    groups, ignored_file_count = libation_backup_groups(source_paths)
    books = list(
        (await db.execute(select(Book).where(Book.deleted_at.is_(None)).order_by(Book.title, Book.id))).scalars().all()
    )
    imports = list(
        (
            await db.execute(
                select(ImportedAudiobook).order_by(
                    ImportedAudiobook.created_at.desc(),
                    ImportedAudiobook.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    imports_by_book: dict[int, list[ImportedAudiobook]] = {}
    for edition in imports:
        imports_by_book.setdefault(edition.book_id, []).append(edition)
    imports_by_book_and_id = {
        (edition.book_id, identifier): edition
        for edition in imports
        if edition.asin
        for identifier in _identifier_match_keys(edition.asin)
    }
    books_by_identifier: dict[str, list[Book]] = {}
    books_by_title: dict[str, list[Book]] = {}
    books_by_title_variant: dict[str, list[Book]] = {}
    for book in books:
        for identifier in _book_identifier_values(book):
            books_by_identifier.setdefault(identifier, []).append(book)
        books_by_title.setdefault(normalize_text(book.title or ""), []).append(book)
        for title_key in _libation_title_keys(book.title or ""):
            books_by_title_variant.setdefault(title_key, []).append(book)
    library_title_keys = tuple(books_by_title_variant)

    matches: list[LibationBackupMatchResponse] = []
    for group in groups:
        title_candidates: list[Book] = []
        variant_candidates: list[Book] = []
        identifier_keys = _identifier_match_keys(group.product_id)
        identifier_candidates = [book for identifier in identifier_keys for book in books_by_identifier.get(identifier, [])]
        matched_book, ambiguous = _single_book_match(identifier_candidates)
        match_method = "identifier" if matched_book else None
        if not identifier_candidates:
            title_candidates = books_by_title.get(normalize_text(group.title), [])
            matched_book, ambiguous = _single_book_match(title_candidates)
            match_method = "title" if matched_book else None
            if not title_candidates:
                variant_candidates = [
                    book
                    for title_key in _libation_title_keys(group.title)
                    for book in books_by_title_variant.get(title_key, [])
                ]
                matched_book, ambiguous = _single_book_match(variant_candidates)
                match_method = "title_variant" if matched_book else None

        if ambiguous:
            ambiguous_candidates = identifier_candidates or title_candidates or variant_candidates
            matches.append(
                LibationBackupMatchResponse(
                    source_key=group.source_key,
                    folder_name=group.folder_name,
                    source_title=group.title,
                    product_id=group.product_id,
                    file_count=len(group.source_paths),
                    status="ambiguous",
                    detail="More than one library book has this identifier or title.",
                    candidates=[
                        _book_option(
                            book,
                            match_score=1.0,
                            existing_editions=imports_by_book.get(book.id, []),
                        )
                        for book in {book.id: book for book in ambiguous_candidates}.values()
                    ],
                )
            )
            continue
        if matched_book is None:
            matches.append(
                LibationBackupMatchResponse(
                    source_key=group.source_key,
                    folder_name=group.folder_name,
                    source_title=group.title,
                    product_id=group.product_id,
                    file_count=len(group.source_paths),
                    status="unmatched",
                    detail="No confident automatic match. Review the suggestions or search the library.",
                    candidates=_suggested_libation_books(
                        group.title,
                        books_by_title_variant,
                        library_title_keys,
                        imports_by_book,
                    ),
                )
            )
            continue

        existing = next(
            (
                imports_by_book_and_id[(matched_book.id, identifier)]
                for identifier in identifier_keys
                if (matched_book.id, identifier) in imports_by_book_and_id
            ),
            None,
        )
        existing_editions = imports_by_book.get(matched_book.id, [])
        status = "already_imported" if existing else "matched"
        matches.append(
            LibationBackupMatchResponse(
                source_key=group.source_key,
                folder_name=group.folder_name,
                source_title=group.title,
                product_id=group.product_id,
                file_count=len(group.source_paths),
                status=status,
                match_method=match_method,
                book_id=matched_book.id,
                book_title=matched_book.title,
                book_author=matched_book.author,
                existing_edition_id=existing.id if existing else None,
                detail=(f"Already attached as {existing.name} ({existing.status})." if existing else None),
                existing_audiobooks=_existing_audio_options(existing_editions),
            )
        )

    return LibationBackupPreviewResponse(
        groups=matches,
        matched_count=sum(match.status == "matched" for match in matches),
        unmatched_count=sum(match.status == "unmatched" for match in matches),
        ambiguous_count=sum(match.status == "ambiguous" for match in matches),
        already_imported_count=sum(match.status == "already_imported" for match in matches),
        existing_audio_match_count=sum(bool(match.existing_audiobooks) for match in matches),
        ignored_file_count=ignored_file_count,
        library_books=[_book_option(book, existing_editions=imports_by_book.get(book.id, [])) for book in books],
    )
