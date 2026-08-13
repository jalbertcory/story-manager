"""Normalization and confidence scoring shared by metadata providers."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any, Iterable, Optional

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_SEPARATOR_RE = re.compile(r"[\s\-:,_]+")
_TRAILING_CONTRIBUTOR_RE = re.compile(
    r"\s*\((?:author|editor|translator|illustrator|narrator)\)\s*$",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_SERIES_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_SERIES_NUMBER_TOKEN = r"(?:\d+(?:\.\d+)?|[IVXLCDMivxlcdm]+|" + "|".join(_SERIES_NUMBER_WORDS) + r")"
_EXPLICIT_SERIES_INDEX_RE = re.compile(
    rf"(?:\b(?:book|part|band|vol(?:ume)?\.?)\s*|#)\s*(?P<index>{_SERIES_NUMBER_TOKEN})\b",
    re.IGNORECASE,
)
_NAMED_SERIES_INDEX_RE = re.compile(
    rf"^(.+?)(?:,\s*)?(?:band|vol(?:ume)?\.?|#)\s*(?P<index>{_SERIES_NUMBER_TOKEN})\s*$",
    re.IGNORECASE,
)
_TRAILING_SERIES_INDEX_RE = re.compile(rf"^(.+?)\s+(?P<index>{_SERIES_NUMBER_TOKEN})\s*$", re.IGNORECASE)
_BOOK_OF_SERIES_RE = re.compile(
    rf"^(?P<title>.+?)\s*:\s*Book\s+(?P<index>{_SERIES_NUMBER_TOKEN})\s+of\s+(?:the\s+)?(?P<series>.+?)\)?\s*$",
    re.IGNORECASE,
)
_ISBN_RE = re.compile(r"[^0-9Xx]")
_MISLEADING_EDITION_TOKENS = {
    "analysis",
    "boxed",
    "collection",
    "companion",
    "guide",
    "omnibus",
    "set",
    "study",
    "summary",
    "workbook",
}


def normalize_text(value: str) -> str:
    """Return a search-safe representation that is stable across providers."""

    decomposed = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(character for character in decomposed if not unicodedata.combining(character))
    ascii_text = ascii_text.casefold().replace("&", " and ")
    return _NON_ALNUM_RE.sub(" ", ascii_text).strip()


def normalize_series(value: str) -> str:
    return _SEPARATOR_RE.sub(" ", normalize_text(value)).strip()


def clean_isbn(value: Any) -> str:
    if value is None:
        return ""
    cleaned = _ISBN_RE.sub("", str(value)).upper()
    if len(cleaned) == 10 and re.fullmatch(r"\d{9}[\dX]", cleaned):
        return cleaned
    if len(cleaned) == 13 and cleaned.isdigit():
        return cleaned
    return ""


def canonical_isbn(value: Any) -> str:
    isbn = clean_isbn(value)
    if len(isbn) != 10:
        return isbn
    body = "978" + isbn[:9]
    checksum = (10 - (sum((1 if index % 2 == 0 else 3) * int(digit) for index, digit in enumerate(body)) % 10)) % 10
    return body + str(checksum)


def _isbn_set(remote_ids: dict[str, Any]) -> set[str]:
    return {canonical for key in ("isbn_13", "isbn_10") if (canonical := canonical_isbn(remote_ids.get(key)))}


def _safe_series_index(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _roman_to_int(value: str) -> Optional[int]:
    roman = value.upper()
    if not roman or not re.fullmatch(r"M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})", roman):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for character in reversed(roman):
        current = values[character]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total or None


def _parse_series_index(value: Any) -> Optional[float]:
    parsed = _safe_series_index(value)
    if parsed is not None:
        return parsed
    text = str(value or "").strip().casefold()
    if text in _SERIES_NUMBER_WORDS:
        return float(_SERIES_NUMBER_WORDS[text])
    roman = _roman_to_int(text)
    return float(roman) if roman is not None else None


def _format_series_index(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:g}"


def infer_series_metadata(title: str, series_name: str = "") -> tuple[Optional[str], Optional[float]]:
    """Infer a series name/index from conservative, common title patterns."""

    cleaned_title = " ".join((title or "").split()).strip()
    if not cleaned_title:
        return None, None

    book_of_series = _BOOK_OF_SERIES_RE.match(cleaned_title)
    if book_of_series:
        inferred_series = series_name.strip() or book_of_series.group("series").strip(" \t:;,–—-()")
        return inferred_series, _parse_series_index(book_of_series.group("index"))

    if series_name:
        series_prefix = re.compile(
            rf"^\s*{re.escape(series_name.strip())}\s*(?:book\s*|vol(?:ume)?\.?\s*|#\s*)?"
            rf"(?P<index>{_SERIES_NUMBER_TOKEN})\s*(?:[:\-–—.]|$)",
            re.IGNORECASE,
        ).match(cleaned_title)
        if series_prefix:
            return series_name.strip(), _parse_series_index(series_prefix.group("index"))

        before_parenthetical = re.search(
            rf"[:\-–—]\s*(?P<index>{_SERIES_NUMBER_TOKEN})\s*\(\s*{re.escape(series_name.strip())}\s*\)\s*$",
            cleaned_title,
            re.IGNORECASE,
        )
        if before_parenthetical:
            return series_name.strip(), _parse_series_index(before_parenthetical.group("index"))

    explicit_match = _EXPLICIT_SERIES_INDEX_RE.search(cleaned_title)
    if explicit_match:
        named_match = _NAMED_SERIES_INDEX_RE.match(cleaned_title)
        inferred_name = series_name.strip() or (named_match.group(1).strip(" \t:;,–—-(") if named_match else None)
        return inferred_name, _parse_series_index(explicit_match.group("index"))

    trailing_match = _TRAILING_SERIES_INDEX_RE.match(cleaned_title)
    if not trailing_match:
        return None, None
    inferred_name = trailing_match.group(1).strip(" \t:;,–—-(")
    inferred_index = _parse_series_index(trailing_match.group("index"))
    # Avoid treating publication years and other large trailing numbers as a
    # volume unless a known series name anchors the title.
    if inferred_index is None or (inferred_index > 999 and not series_name):
        return None, None
    if series_name:
        normalized_title = normalize_series(cleaned_title)
        normalized_series_name = normalize_series(series_name)
        if not normalized_title.startswith(normalized_series_name + " "):
            return None, None
        inferred_name = series_name.strip()
    return inferred_name or None, inferred_index


def bibliographic_title_variants(title: str, series_name: str = "") -> list[str]:
    """Return plausible provider-facing titles without destructive normalization."""

    original = " ".join((title or "").split()).strip()
    if not original:
        return []
    variants = [original]

    def add(value: str) -> None:
        cleaned = value.strip(" \t:;,–—-")
        if cleaned and normalize_text(cleaned) not in {normalize_text(candidate) for candidate in variants}:
            variants.append(cleaned)

    trailing_parenthetical = re.match(r"^(?P<title>.+?)\s*\((?P<meta>[^()]*)\)\s*$", original)
    if trailing_parenthetical:
        metadata = trailing_parenthetical.group("meta")
        series_related = bool(series_name and normalize_series(series_name) in normalize_series(metadata))
        if series_related or _EXPLICIT_SERIES_INDEX_RE.search(metadata):
            add(trailing_parenthetical.group("title"))

    book_of_series = _BOOK_OF_SERIES_RE.match(original)
    if book_of_series:
        add(book_of_series.group("title"))

    if series_name:
        prefix = re.compile(
            rf"^\s*{re.escape(series_name.strip())}\s*(?:book\s*|vol(?:ume)?\.?\s*|#\s*)?"
            rf"{_SERIES_NUMBER_TOKEN}\s*[:\-–—.]\s*(?P<title>.+)$",
            re.IGNORECASE,
        ).match(original)
        if prefix:
            add(prefix.group("title"))

        series_suffix = re.compile(
            rf"^(?P<title>.+?)\s*[:\-–—]\s*{re.escape(series_name.strip())}"
            rf"(?:\s+(?:series))?(?:\s+(?:book|part|vol(?:ume)?\.?)\s*{_SERIES_NUMBER_TOKEN})?\s*$",
            re.IGNORECASE,
        ).match(original)
        if series_suffix:
            add(series_suffix.group("title"))

        numbered_parenthetical = re.match(
            rf"^(?P<title>.+?)\s*[:\-–—]\s*{_SERIES_NUMBER_TOKEN}\s*" rf"\(\s*{re.escape(series_name.strip())}\s*\)\s*$",
            original,
            re.IGNORECASE,
        )
        if numbered_parenthetical:
            add(numbered_parenthetical.group("title"))

    generic_series_suffix = re.match(
        rf"^(?P<title>.+?)\s*[:\-–—]\s*.+?\b(?:book|part|vol(?:ume)?\.?)\s*" rf"{_SERIES_NUMBER_TOKEN}\s*$",
        original,
        re.IGNORECASE,
    )
    if generic_series_suffix:
        add(generic_series_suffix.group("title"))

    volume_suffix = _NAMED_SERIES_INDEX_RE.match(original)
    if volume_suffix:
        add(volume_suffix.group(1))

    return variants


def best_title_similarity(
    local_title: str,
    remote_title: str,
    *,
    local_series: str = "",
    remote_series: str = "",
) -> float:
    return max(
        (
            title_similarity(local_variant, remote_variant)
            for local_variant in bibliographic_title_variants(local_title, local_series)
            for remote_variant in bibliographic_title_variants(remote_title, remote_series)
        ),
        default=0.0,
    )


def series_match_issues(
    *,
    local_title: str,
    local_series: str = "",
    local_series_index: Any = None,
    remote_title: str,
    remote_series: str = "",
    remote_series_index: Any = None,
) -> list[str]:
    """Explain series contradictions that should require human review."""

    inferred_local_series, inferred_local_index = infer_series_metadata(local_title, local_series)
    inferred_remote_series, inferred_remote_index = infer_series_metadata(
        remote_title,
        remote_series or local_series,
    )
    resolved_local_series = (local_series or inferred_local_series or "").strip()
    resolved_remote_series = (remote_series or inferred_remote_series or "").strip()
    resolved_local_index = _parse_series_index(local_series_index) or inferred_local_index
    resolved_remote_index = _parse_series_index(remote_series_index) or inferred_remote_index

    issues: list[str] = []
    if resolved_local_index is not None and resolved_remote_index is not None:
        if abs(resolved_local_index - resolved_remote_index) > 0.001:
            issues.append(
                "Series position conflict: "
                f"local book is #{_format_series_index(resolved_local_index)}, "
                f"candidate is #{_format_series_index(resolved_remote_index)}."
            )

    local_normalized = normalize_series(resolved_local_series)
    remote_normalized = normalize_series(resolved_remote_series)
    if local_normalized and remote_normalized:
        related = (
            local_normalized == remote_normalized
            or local_normalized in remote_normalized
            or remote_normalized in local_normalized
            or _sequence_similarity(local_normalized, remote_normalized) >= 0.82
        )
        if not related:
            issues.append(
                f'Series conflict: local series is "{resolved_local_series}", '
                f'candidate series is "{resolved_remote_series}".'
            )
    return issues


def _tokens(value: str) -> list[str]:
    return [token for token in normalize_text(value).split() if token]


def _numeric_tokens(value: str) -> set[str]:
    return set(_NUMBER_RE.findall(normalize_text(value)))


def _sequence_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left, b=right).ratio()


def title_similarity(left: str, right: str) -> float:
    """Blend character and token similarity while respecting volume numbers."""

    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0

    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    left_set = set(left_tokens)
    right_set = set(right_tokens)
    token_union = left_set | right_set
    token_overlap = len(left_set & right_set) / len(token_union) if token_union else 0.0
    token_sort = _sequence_similarity(" ".join(sorted(left_tokens)), " ".join(sorted(right_tokens)))
    sequence = _sequence_similarity(left_norm, right_norm)

    score = max(sequence, token_sort * 0.97, token_overlap)
    shorter, longer = sorted((left_norm, right_norm), key=len)
    if len(shorter) >= 5 and (longer.startswith(shorter + " ") or longer.endswith(" " + shorter)):
        # Subtitle and edition suffixes should not drown out an exact base title.
        score = max(score, 0.94)

    left_numbers = _numeric_tokens(left)
    right_numbers = _numeric_tokens(right)
    if left_numbers and right_numbers and left_numbers != right_numbers:
        # A near-identical title with a different volume number is a different book.
        score = min(score, 0.68)

    return score


def _author_forms(value: str) -> set[str]:
    cleaned = _TRAILING_CONTRIBUTOR_RE.sub("", value or "").strip()
    forms = {normalize_text(cleaned)}
    if "," in cleaned:
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
        if len(parts) == 2:
            forms.add(normalize_text(f"{parts[1]} {parts[0]}"))

    tokens = _tokens(cleaned)
    if len(tokens) >= 2:
        forms.add(" ".join(tokens))
        forms.add(" ".join(reversed(tokens)))
        forms.add(f"{tokens[0][0]} {tokens[-1]}")
        forms.add(f"{tokens[-1]} {tokens[0][0]}")
    return {form for form in forms if form}


def author_similarity(left: str, right: str) -> float:
    left_forms = _author_forms(left)
    right_forms = _author_forms(right)
    if not left_forms or not right_forms:
        return 0.0
    if left_forms & right_forms:
        return 1.0
    return max(_sequence_similarity(left_form, right_form) for left_form in left_forms for right_form in right_forms)


def best_author_similarity(local_author: str, remote_authors: Iterable[str]) -> float:
    return max(
        (author_similarity(local_author, remote_author) for remote_author in remote_authors if remote_author),
        default=0.0,
    )


def score_metadata_candidate(
    *,
    local_title: str,
    local_author: str,
    remote_title: str,
    remote_authors: Iterable[str],
    local_ids: dict[str, Any] | None = None,
    remote_ids: dict[str, Any] | None = None,
    local_series: str = "",
    local_series_index: Any = None,
    remote_series: str = "",
    remote_series_index: Any = None,
) -> float:
    """Score a candidate consistently regardless of which provider returned it."""

    title_score = best_title_similarity(
        local_title,
        remote_title,
        local_series=local_series,
        remote_series=remote_series,
    )
    author_score = best_author_similarity(local_author, remote_authors)
    score = (title_score * 0.68) + (author_score * 0.32)

    exact_title_variant = bool(
        {normalize_text(variant) for variant in bibliographic_title_variants(local_title, local_series)}
        & {normalize_text(variant) for variant in bibliographic_title_variants(remote_title, remote_series)}
    )
    if exact_title_variant:
        score += 0.08
    if author_score >= 0.97:
        score += 0.04

    local_ids = local_ids or {}
    remote_ids = remote_ids or {}
    local_isbns = _isbn_set(local_ids)
    remote_isbns = _isbn_set(remote_ids)
    exact_identifier = bool(local_isbns & remote_isbns)
    conflicting_identifier = bool(local_isbns and remote_isbns and not exact_identifier)
    for key in ("google_books_volume_id", "open_library_work_key", "asin"):
        local_value = str(local_ids.get(key) or "").strip()
        remote_value = str(remote_ids.get(key) or "").strip()
        if local_value and remote_value:
            if local_value == remote_value:
                exact_identifier = True

    if exact_identifier:
        score = max(score + 0.12, 0.97)
    elif conflicting_identifier:
        score = min(score, 0.79)

    if local_author and author_score < 0.35 and not exact_identifier:
        score = min(score, 0.69)

    local_title_tokens = set(_tokens(local_title))
    remote_title_tokens = set(_tokens(remote_title))
    if (remote_title_tokens - local_title_tokens) & _MISLEADING_EDITION_TOKENS and not exact_identifier:
        score = min(score, 0.72)

    local_numbers = _numeric_tokens(local_title)
    remote_numbers = _numeric_tokens(remote_title)
    if local_numbers and remote_numbers and local_numbers != remote_numbers and not exact_identifier:
        score = min(score, 0.82)

    if series_match_issues(
        local_title=local_title,
        local_series=local_series,
        local_series_index=local_series_index,
        remote_title=remote_title,
        remote_series=remote_series,
        remote_series_index=remote_series_index,
    ):
        # Identifier matches can themselves be stale assignments. A series
        # contradiction always needs review, even when an old ISBN/ASIN agrees.
        score = min(score, 0.89)

    return max(0.0, min(score, 1.0))
