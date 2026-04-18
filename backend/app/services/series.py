"""Series detection: infers series groupings from book title patterns."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

_ROMAN = re.compile(
    r"^M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$",
    re.IGNORECASE,
)
_NUMBER_TOKEN = r"#?(?:\d+(?:\.\d+)?|[IVXLCDMivxlcdm]+)"
_SEPARATOR_RE = re.compile(r"[\s\-:,_]+")
_AUTHOR_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_TRAILING_METADATA_RE = re.compile(r"\s*\([^)]*\)\s*$")
_SERIES_PATTERNS = (
    re.compile(rf"^.+?\((?P<series>.+?)\s+Book\s+(?P<num>{_NUMBER_TOKEN})\)\s*$", re.IGNORECASE),
    re.compile(rf"^.+?[:,-]\s*(?P<series>.+?),?\s+Book\s+(?P<num>{_NUMBER_TOKEN})\b.*$", re.IGNORECASE),
    re.compile(rf"^(?P<series>.+?)\s*:\s*.+?\bBook\s+(?P<num>{_NUMBER_TOKEN})\b.*$", re.IGNORECASE),
    re.compile(rf"^.+?:\s*(?P<num>{_NUMBER_TOKEN})\s*\((?P<series>.+?)\)\s*$", re.IGNORECASE),
    re.compile(rf"^(?P<series>.+?)\s*:\s*Book\s+(?P<num>{_NUMBER_TOKEN})(?:\b.*)?$", re.IGNORECASE),
    re.compile(rf"^(?P<series>.+?)\s+(?P<num>{_NUMBER_TOKEN})(?:\s*[-:(].*)?$", re.IGNORECASE),
)
_PARENTHETICAL_SERIES_RE = re.compile(r"^.+?\((?P<series>[^)]+)\)\s*$")


@dataclass(frozen=True)
class SeriesBook:
    title: str
    author: str


def _is_valid_sequence_token(token: str) -> bool:
    token = token.lstrip("#")
    return token.replace(".", "", 1).isdigit() or bool(_ROMAN.fullmatch(token))


def _normalize_series_name(value: str) -> str:
    return _SEPARATOR_RE.sub(" ", value.casefold()).strip()


def _normalize_author_name(value: str) -> str:
    tokens = [token for token in _AUTHOR_TOKEN_RE.findall(value.casefold()) if len(token) > 1 or token.isdigit()]
    return " ".join(tokens)


def _extract_series_hints(title: str) -> list[str]:
    stripped = title.strip()
    hints: list[str] = []

    primary_parenthetical_match = _SERIES_PATTERNS[0].match(stripped)
    if primary_parenthetical_match:
        token = primary_parenthetical_match.group("num")
        if _is_valid_sequence_token(token):
            hints.append(primary_parenthetical_match.group("series").strip(" :-,()"))

    if not primary_parenthetical_match:
        for pattern in _SERIES_PATTERNS[1:]:
            match = pattern.match(stripped)
            if not match:
                continue
            token = match.group("num")
            if not _is_valid_sequence_token(token):
                continue
            hints.append(match.group("series").strip(" :-,()"))

    paren_match = _PARENTHETICAL_SERIES_RE.match(stripped)
    if paren_match:
        paren_value = paren_match.group("series").strip(" :-,()")
        if paren_value and not re.search(rf"\bBook\s+{_NUMBER_TOKEN}\b", paren_value, re.IGNORECASE):
            hints.append(paren_value)

    deduped: list[str] = []
    seen: set[str] = set()
    for hint in hints:
        normalized_hint = _normalize_series_name(hint)
        if not normalized_hint or normalized_hint in seen:
            continue
        seen.add(normalized_hint)
        deduped.append(hint)

    return deduped


def _labels_overlap(left: str, right: str) -> bool:
    if left == right:
        return True
    return left.endswith(" " + right) or right.endswith(" " + left)


def _choose_canonical_label(labels: Iterable[str]) -> str:
    return min(labels, key=lambda label: (len(_normalize_series_name(label)), len(label), label.casefold()))


def _title_matches_series(title: str, label: str) -> bool:
    raw_title = title.strip()
    raw_label = label.strip()
    normalized_title = _normalize_series_name(raw_title)
    normalized_label = _normalize_series_name(raw_label)
    if normalized_title == normalized_label:
        return True

    title_without_trailing_metadata = _TRAILING_METADATA_RE.sub("", raw_title).strip()
    normalized_without_metadata = _normalize_series_name(title_without_trailing_metadata)
    if normalized_without_metadata == normalized_label:
        return True

    prefixes = (f"{raw_label}: ", f"{raw_label} - ", f"{raw_label}, ")
    return any(raw_title.startswith(prefix) for prefix in prefixes)


def detect_series_from_books(books: list[SeriesBook]) -> dict[tuple[str, str], str]:
    """
    Detect series assignments from title patterns, grouped by normalized author.

    Books are only compared against titles from the same author bucket, which lets us
    safely relax the title matching rules for common real-world formats such as:
      - "<title> (Series Book 3)"
      - "<title>: Series, Book II"
      - "<series>: Book 2 (...)"
      - "<series> 3"
    """

    result: dict[tuple[str, str], str] = {}
    books_by_author: dict[str, list[SeriesBook]] = defaultdict(list)
    for book in books:
        books_by_author[_normalize_author_name(book.author)].append(book)

    for author_books in books_by_author.values():
        clusters: list[dict[str, list[str] | set[tuple[str, str]]]] = []

        for book in author_books:
            for hint in _extract_series_hints(book.title):
                normalized_hint = _normalize_series_name(hint)
                cluster = next(
                    (
                        existing
                        for existing in clusters
                        if any(_labels_overlap(normalized_hint, existing_label) for existing_label in existing["normalized"])
                    ),
                    None,
                )
                if cluster is None:
                    cluster = {"labels": [], "normalized": [], "books": set()}
                    clusters.append(cluster)
                cluster["labels"].append(hint)
                cluster["normalized"].append(normalized_hint)
                cluster["books"].add((book.author, book.title))

        confirmed = []
        for cluster in clusters:
            if len(cluster["books"]) < 2:
                continue
            canonical = _choose_canonical_label(cluster["labels"])
            confirmed.append((canonical, list(cluster["labels"]), set(cluster["books"])))
            for key in cluster["books"]:
                result[key] = canonical

        if not confirmed:
            continue

        for book in author_books:
            key = (book.author, book.title)
            if key in result:
                continue
            for canonical, labels, _cluster_books in confirmed:
                if _title_matches_series(book.title, canonical) or any(
                    _title_matches_series(book.title, label) for label in labels
                ):
                    result[key] = canonical
                    break

    return result


def detect_series_from_titles(titles: list[str]) -> dict[str, str]:
    """Backward-compatible title-only wrapper used by existing tests."""

    books = [SeriesBook(title=title, author="") for title in titles]
    assignments = detect_series_from_books(books)
    return {title: assignments[("", title)] for title in titles if ("", title) in assignments}
