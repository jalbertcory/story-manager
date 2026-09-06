"""Conservative work matching when adding an EPUB to recorded narration."""

import re
from collections.abc import Mapping
from ebooklib import epub
from decimal import Decimal, InvalidOperation

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Book, ImportedAudiobook, SourceType
from .metadata.scoring import canonical_isbn, normalize_text

_TRAILING_TITLE_QUALIFIER_RE = re.compile(r"\s*[\[(].*[\])]\s*$")
_TRAILING_EDITION_RE = re.compile(
    r"(?:\s*,?\s+)(?:movie\s+tie[ -]in|revised|unabridged|abridged|dramatized)" r"(?:\s+(?:edition|adaptation))$",
    re.IGNORECASE,
)


def title_match_keys(value: str) -> set[str]:
    """Return conservative aliases for store and EPUB title decorations."""
    pending = [(value or "").strip()]
    aliases: set[str] = set()
    while pending:
        candidate = pending.pop()
        normalized = normalize_text(candidate)
        if not normalized or normalized in aliases:
            continue
        aliases.add(normalized)

        without_qualifier = _TRAILING_TITLE_QUALIFIER_RE.sub("", candidate).strip()
        if without_qualifier and without_qualifier != candidate:
            pending.append(without_qualifier)

        without_edition = _TRAILING_EDITION_RE.sub("", candidate).strip()
        if without_edition and without_edition != candidate:
            pending.append(without_edition)

        # EPUB metadata commonly appends a series, volume, or edition label
        # after a colon while Libation uses only the work title.
        if ":" in candidate:
            pending.append(candidate.split(":", 1)[0].strip())

    for alias in tuple(aliases):
        words = alias.split()
        if len(words) > 2 and words[0] in {"a", "an", "the"}:
            aliases.add(" ".join(words[1:]))
    return aliases


_NUMBER = re.compile(r"\b(?:book|volume|vol\.?)\s*(\d+(?:\.\d+)?)\b", re.I)
_DIFFERENT_WORK = {"omnibus", "collection", "boxed", "summary", "study", "workbook", "companion"}


def _metadata(ebook: epub.EpubBook, namespace: str, name: str) -> list[str]:
    try:
        values = ebook.get_metadata(namespace, name)
    except KeyError:
        return []
    return [str(value).strip() for value, _attributes in values if value]


def _number(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except InvalidOperation:
        return None


def _title_number(title: str | None) -> Decimal | None:
    match = _NUMBER.search(title or "")
    return _number(match.group(1)) if match else None


def epub_identifiers(ebook: epub.EpubBook) -> dict[str, str]:
    identifiers = {}
    for raw in _metadata(ebook, "DC", "identifier"):
        value = re.sub(r"^(?:urn:)?(?:isbn|asin):?\s*", "", raw, flags=re.I)
        value = re.sub(r"[\s-]", "", value).upper()
        if re.fullmatch(r"(?:[0-9]{9}[0-9X]|[0-9]{13})", value):
            identifiers["isbn_10" if len(value) == 10 else "isbn_13"] = value
        elif re.fullmatch(r"B[0-9A-Z]{9}", value):
            identifiers["asin"] = value
    return identifiers


def _identifier_keys(identifiers: Mapping[str, object]) -> set[str]:
    keys = set()
    for key in ("isbn_10", "isbn_13", "asin"):
        values = identifiers.get(key, [])
        for value in values if isinstance(values, list) else [values]:
            if not value:
                continue
            normalized = re.sub(r"[\s-]", "", str(value)).upper()
            if re.fullmatch(r"(?:[0-9]{9}[0-9X]|[0-9]{13})", normalized):
                keys.add(canonical_isbn(normalized))
            elif key == "asin":
                keys.add(normalized)
    return keys


def _work_title_keys(value: str, series: str | None) -> set[str]:
    keys = title_match_keys(value)
    if ":" in value and series:
        prefix, subtitle = value.split(":", 1)
        # "Series: A Different Story" must not match the first book solely
        # because stripping the subtitle leaves the series name.
        series_key = normalize_text(series)
        if series_key in title_match_keys(prefix) and _title_number(subtitle) is None:
            subtitle_key = normalize_text(subtitle)
            if subtitle_key not in {series_key, "a novel", "audiobook", "unabridged"}:
                keys -= title_match_keys(prefix)
                keys.update(title_match_keys(subtitle))
    return keys


async def match_epub_to_audio_book(db: AsyncSession, ebook: epub.EpubBook, title: str, author: str) -> Book | None:
    # Include previously attached books so uploading another copy is idempotent,
    # even if store metadata decorates their title differently from the EPUB.
    candidates = (
        (
            await db.execute(
                select(Book).where(
                    Book.deleted_at.is_(None),
                    or_(
                        Book.source_type == SourceType.audiobook,
                        exists(select(ImportedAudiobook.id).where(ImportedAudiobook.book_id == Book.id)),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    author_key = normalize_text(author)
    identifiers = _identifier_keys(epub_identifiers(ebook))
    series_values = _metadata(ebook, "calibre", "series")
    number_values = _metadata(ebook, "calibre", "series_index")
    number = _number(number_values[0]) if number_values else _title_number(title)
    exact = []
    matching = []
    for book in candidates:
        book_author = normalize_text(book.author or "")
        if book_author not in {"", "unknown author", author_key}:
            continue
        book_number = _number(book.series_index)
        if book_number is None:
            book_number = _title_number(book.title or "")
        if number is not None and book_number is not None and number != book_number:
            continue
        if (_DIFFERENT_WORK & set(normalize_text(title).split())) != (
            _DIFFERENT_WORK & set(normalize_text(book.title or "").split())
        ):
            continue
        if identifiers & _identifier_keys(book.metadata_remote_ids or {}):
            exact.append(book)
        elif book_author == author_key and _work_title_keys(
            title, series_values[0] if series_values else book.series
        ) & _work_title_keys(book.title or "", book.series):
            matching.append(book)
    matches = exact or matching
    if len(matches) > 1:
        names = "; ".join(f"{book.title} (book {book.id})" for book in matches)
        raise ValueError(
            f"More than one audiobook matches this EPUB: {names}. "
            "Correct their title/author or series position before retrying."
        )
    return matches[0] if matches else None
