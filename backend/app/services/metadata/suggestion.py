"""Provider-neutral metadata suggestion record and the helpers every provider shares."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from bs4 import BeautifulSoup
from pydantic import JsonValue

from ... import models, schemas
from ...metadata_types import MetadataDetails
from ...metadata_types import metadata_details as validate_metadata_details
from ...metadata_types import metadata_json, remote_identifiers, searchable_identifiers
from .scoring import bibliographic_title_variants as _bibliographic_title_variants
from .scoring import infer_series_metadata as _infer_series_metadata
from .scoring import normalize_text as _normalize_text
from .scoring import series_match_issues as _series_match_issues

DEFAULT_MATCH_CANDIDATE_LIMIT = 5

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
    remote_ids: dict[str, JsonValue] | None = None
    metadata_details: MetadataDetails | None = None
    match_issues: list[str] | None = None

    def __post_init__(self) -> None:
        if self.remote_ids is not None:
            self.remote_ids = remote_identifiers(self.remote_ids)
        if self.metadata_details is not None:
            self.metadata_details = validate_metadata_details(self.metadata_details)

    def to_schema(self) -> schemas.MetadataSyncBookResult:
        return schemas.MetadataSyncBookResult(
            book_id=self.book.id,
            title=self.book.title or "",
            author=self.book.author or "",
            matched=self.matched,
            source=self.source if self.matched else None,
            match_confidence=round(self.match_confidence, 3),
            remote_title=self.remote_title,
            remote_author=self.remote_author,
            remote_url=self.remote_url,
            remote_ids=self.remote_ids,
            metadata_details=metadata_json(self.metadata_details) if self.metadata_details is not None else None,
            match_issues=self.match_issues or [],
            genre_tags=self.genre_tags or [],
            new_genre_tags=self.new_genre_tags or [],
            possible_missing_series_books=self.possible_missing_series_books or [],
            note=self.note,
        )


def _strip_trailing_metadata(value: str) -> str:
    cleaned = _TRAILING_SERIES_BOOK_RE.sub("", value).strip()
    if cleaned != value.strip():
        return _TRAILING_PUNCTUATION_RE.sub("", cleaned).strip()
    cleaned = _TRAILING_PARENS_RE.sub("", value).strip()
    return _TRAILING_PUNCTUATION_RE.sub("", cleaned).strip()


def title_search_variants(book: models.Book) -> list[str]:
    variants = _bibliographic_title_variants(book.title or "", book.series or "") or [(book.title or "").strip()]
    stripped = _strip_trailing_metadata(book.title or "")
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


def book_manual_remote_ids(book: models.Book) -> dict[str, str]:
    return searchable_identifiers(book.metadata_remote_ids)


def compact_metadata_details(**values: object) -> MetadataDetails:
    return validate_metadata_details(
        {
            key: value.strip() if isinstance(value, str) else value
            for key, value in values.items()
            if value is not None and (not isinstance(value, str) or value.strip())
        }
    )


def safe_series_index(value: object) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


def first_list_value(value: object) -> object:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def series_metadata_details(
    title: str,
    *,
    series: object = None,
    series_index: object = None,
) -> MetadataDetails:
    raw_series = first_list_value(series)
    series_name = str(raw_series).strip() if raw_series is not None else ""
    resolved_index = safe_series_index(first_list_value(series_index))
    inferred_series, inferred_index = _infer_series_metadata(title, series_name)
    return compact_metadata_details(
        series=series_name or inferred_series,
        series_index=resolved_index or inferred_index,
    )


def suggestion_match_issues(
    book: models.Book,
    *,
    remote_title: str,
    metadata_details: MetadataDetails,
) -> list[str]:
    return _series_match_issues(
        local_title=book.title or "",
        local_series=book.series or "",
        local_series_index=book.series_index,
        remote_title=remote_title,
        remote_series=str(metadata_details.get("series") or ""),
        remote_series_index=metadata_details.get("series_index"),
    )


def description_value(value: object) -> Optional[str]:
    if isinstance(value, str):
        return " ".join(BeautifulSoup(value, "html.parser").get_text(" ", strip=True).split()) or None
    if isinstance(value, dict) and isinstance(value.get("value"), str):
        return " ".join(BeautifulSoup(value["value"], "html.parser").get_text(" ", strip=True).split()) or None
    return None
