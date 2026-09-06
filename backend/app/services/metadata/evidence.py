"""Build a reliable metadata search identity from an EPUB and its opening pages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import re
from typing import Any, Optional

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from ...config import LIBRARY_PATH
from ...models import AudiobookSettings, Book
from ..audiobook_llm import _call_llm
from ..endpoint_pool import configured_endpoints
from .scoring import author_similarity, clean_isbn, normalize_text, title_similarity

logger = logging.getLogger(__name__)

MAX_OPENING_DOCUMENTS = 4
MAX_OPENING_CONTENT_CHARS = 12_000
_BYLINE_RE = re.compile(r"^(?:written\s+)?by\s+(.{2,120})$", re.IGNORECASE)
_ISBN_CANDIDATE_RE = re.compile(r"(?<!\d)(?:97[89][\d\- ]{10,20}|[\d][\d\- ]{7,15}[\dXx])(?!\d)")
_SERIES_PATTERNS = (
    re.compile(
        r"(?:book|volume|vol\.?|#)\s*(\d+(?:\.\d+)?)\s*(?:of|in)\s+(?:the\s+)?(.{2,100}?)(?:\s+series)?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(.{2,100}?)(?:\s+series)?\s*[-,:—]?\s*(?:book|volume|vol\.?|#)\s*(\d+(?:\.\d+)?)$",
        re.IGNORECASE,
    ),
)
_GENERIC_HEADING_RE = re.compile(
    r"^(?:chapter|book|part|volume|prologue|epilogue|contents?|table of contents|copyright|title page)\b",
    re.IGNORECASE,
)

IDENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 300},
        "author": {"type": "string", "maxLength": 200},
        "series": {"type": "string", "maxLength": 200},
        "series_index": {"type": "number"},
        "isbn_10": {"type": "string", "maxLength": 32},
        "isbn_13": {"type": "string", "maxLength": 32},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "maxLength": 500},
    },
    "required": ["title", "author", "series", "series_index", "isbn_10", "isbn_13", "confidence", "reason"],
    "additionalProperties": False,
}


@dataclass
class EpubEvidence:
    package_title: Optional[str] = None
    package_author: Optional[str] = None
    package_series: Optional[str] = None
    package_series_index: Optional[float] = None
    content_series: Optional[str] = None
    content_series_index: Optional[float] = None
    heading_title: Optional[str] = None
    byline_author: Optional[str] = None
    remote_ids: dict[str, str] = field(default_factory=dict)
    opening_content: str = ""


@dataclass
class SearchIdentity:
    title: str
    author: str
    series: Optional[str]
    series_index: Optional[float]
    remote_ids: dict[str, str]
    evidence_note: Optional[str] = None
    used_llm: bool = False
    opening_excerpt: str = ""


def _first_metadata(book: epub.EpubBook, namespace: str, name: str) -> Optional[str]:
    try:
        entries = book.get_metadata(namespace, name)
    except (KeyError, AttributeError):
        return None
    for value, _attributes in entries:
        cleaned = " ".join(str(value or "").split()).strip()
        if cleaned:
            return cleaned
    return None


def _metadata_values(book: epub.EpubBook, namespace: str, name: str) -> list[str]:
    try:
        entries = book.get_metadata(namespace, name)
    except (KeyError, AttributeError):
        return []
    return [cleaned for value, _attributes in entries if (cleaned := " ".join(str(value or "").split()).strip())]


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _book_path(book: Book) -> Optional[Path]:
    relative_path = book.current_path or book.immutable_path
    if not relative_path:
        return None
    library_root = LIBRARY_PATH.parent.resolve()
    path = (library_root / relative_path).resolve()
    if not path.is_relative_to(library_root) or path.suffix.casefold() != ".epub" or not path.is_file():
        return None
    return path


def _usable_heading(value: str) -> bool:
    normalized = " ".join(value.split()).strip()
    return 2 <= len(normalized) <= 300 and not _GENERIC_HEADING_RE.match(normalized)


def _series_from_lines(lines: list[str]) -> tuple[Optional[str], Optional[float]]:
    for line in lines:
        if len(line) > 120:
            continue
        for index, pattern in enumerate(_SERIES_PATTERNS):
            match = pattern.search(line)
            if not match:
                continue
            number_group, name_group = (1, 2) if index == 0 else (2, 1)
            name = re.sub(r"\s+series$", "", match.group(name_group).strip(" -,:—"), flags=re.IGNORECASE)
            number = _safe_float(match.group(number_group))
            if name and number is not None and not _GENERIC_HEADING_RE.match(name):
                return name, number
    return None, None


def extract_epub_evidence(book: Book) -> EpubEvidence:
    path = _book_path(book)
    if path is None:
        return EpubEvidence()

    try:
        ebook = epub.read_epub(str(path))
    except Exception:
        logger.warning("Could not read EPUB evidence for book %s at %s.", book.id, path, exc_info=True)
        return EpubEvidence()

    package_title = _first_metadata(ebook, "DC", "title")
    package_author = _first_metadata(ebook, "DC", "creator")
    package_series = _first_metadata(ebook, "calibre", "series")
    package_series_index = _safe_float(_first_metadata(ebook, "calibre", "series_index"))

    remote_ids: dict[str, str] = {}
    for raw_identifier in _metadata_values(ebook, "DC", "identifier"):
        isbn = clean_isbn(raw_identifier)
        if len(isbn) == 10:
            remote_ids.setdefault("isbn_10", isbn)
        elif len(isbn) == 13:
            remote_ids.setdefault("isbn_13", isbn)

    text_parts: list[str] = []
    heading_title: Optional[str] = None
    byline_author: Optional[str] = None
    content_series: Optional[str] = None
    content_series_index: Optional[float] = None
    document_count = 0
    for item_id, _linear in ebook.spine:
        item = ebook.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT or isinstance(item, epub.EpubNav):
            continue
        document_count += 1
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for removable in soup(["script", "style", "nav", "svg"]):
            removable.decompose()

        if heading_title is None:
            heading = next(
                (
                    " ".join(element.get_text(" ", strip=True).split())
                    for element in soup.select("h1, h2, [epub\\:type='titlepage'] .title, .book-title, .title")
                    if _usable_heading(element.get_text(" ", strip=True))
                ),
                None,
            )
            heading_title = heading

        cleaned_lines = [" ".join(raw_line.split()).strip() for raw_line in soup.get_text("\n").splitlines()]
        text = "\n".join(line for line in cleaned_lines if line)
        if content_series is None:
            content_series, content_series_index = _series_from_lines(cleaned_lines[:60])
        if byline_author is None:
            for line in text.splitlines()[:40]:
                match = _BYLINE_RE.match(line)
                if match and not _GENERIC_HEADING_RE.match(match.group(1)):
                    byline_author = match.group(1).strip(" .")
                    break
        for candidate in _ISBN_CANDIDATE_RE.findall(text):
            isbn = clean_isbn(candidate)
            if len(isbn) == 10:
                remote_ids.setdefault("isbn_10", isbn)
            elif len(isbn) == 13:
                remote_ids.setdefault("isbn_13", isbn)

        text_parts.append(text)
        if document_count >= MAX_OPENING_DOCUMENTS or sum(len(part) for part in text_parts) >= MAX_OPENING_CONTENT_CHARS:
            break

    opening_content = "\n\n".join(text_parts)[:MAX_OPENING_CONTENT_CHARS]
    return EpubEvidence(
        package_title=package_title,
        package_author=package_author,
        package_series=package_series,
        package_series_index=package_series_index,
        content_series=content_series,
        content_series_index=content_series_index,
        heading_title=heading_title,
        byline_author=byline_author,
        remote_ids=remote_ids,
        opening_content=opening_content,
    )


def _unstable(value: Optional[str]) -> bool:
    return not value or normalize_text(value) in {"pending", "unknown", "unknown author", "untitled"}


def _first_stable(*values: Optional[str]) -> str:
    return next((value.strip() for value in values if value and not _unstable(value)), "")


def _llm_configured(settings: AudiobookSettings | None) -> bool:
    if settings is None:
        return False
    for endpoint in configured_endpoints(settings, "llm"):
        provider = str(endpoint.get("provider") or "").casefold()
        if provider == "ollama":
            return True
        if provider not in {"", "none", "stub"} and (endpoint.get("api_key") or endpoint.get("base_url")):
            return True
    return False


def _needs_llm(book: Book, evidence: EpubEvidence) -> bool:
    if not evidence.opening_content:
        return False
    if _unstable(book.title) or _unstable(book.author):
        return True
    if evidence.package_title and title_similarity(book.title or "", evidence.package_title) < 0.72:
        return True
    if evidence.package_author and author_similarity(book.author or "", evidence.package_author) < 0.65:
        return True
    if evidence.heading_title and title_similarity(book.title or "", evidence.heading_title) < 0.72:
        return True
    return False


async def infer_identity_with_llm(
    book: Book,
    evidence: EpubEvidence,
    settings: AudiobookSettings,
) -> dict[str, Any]:
    prompt = f"""Determine this ebook's bibliographic identity from package metadata and the opening pages. The opening may
contain fiction prose, advertisements, navigation, or another book's title, so do not guess. Prefer explicit title-page,
copyright, ISBN, and author evidence. Return empty strings and series_index 0 when unknown.

Stored library record:
title: {book.title}
author: {book.author}
series: {book.series or ""}
series_index: {book.series_index or ""}

EPUB package metadata:
title: {evidence.package_title or ""}
author: {evidence.package_author or ""}
series: {evidence.package_series or ""}
series_index: {evidence.package_series_index or ""}

Opening EPUB content (bounded sample):
{evidence.opening_content}
"""
    raw = await _call_llm(
        settings,
        [
            {"role": "system", "content": "You extract book metadata. Return only the requested JSON object."},
            {"role": "user", "content": prompt},
        ],
        response_schema=IDENTITY_SCHEMA,
    )
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


async def resolve_search_identity(
    book: Book,
    settings: AudiobookSettings | None,
) -> SearchIdentity:
    evidence = await asyncio.to_thread(extract_epub_evidence, book)
    title = book.title or ""
    author = book.author or ""
    series = book.series
    series_index = float(book.series_index) if book.series_index is not None else None
    reasons: list[str] = []

    if _unstable(title):
        title = _first_stable(evidence.package_title, evidence.heading_title, title)
        if title and not _unstable(title):
            reasons.append("title from EPUB")
    if _unstable(author):
        author = _first_stable(evidence.package_author, evidence.byline_author, author)
        if author and not _unstable(author):
            reasons.append("author from EPUB")
    if not series and (evidence.package_series or evidence.content_series):
        series = evidence.package_series or evidence.content_series
        series_index = evidence.package_series_index or evidence.content_series_index
        reasons.append("series from EPUB")

    used_llm = False
    if settings is not None and _needs_llm(book, evidence) and _llm_configured(settings):
        try:
            inferred = await infer_identity_with_llm(book, evidence, settings)
            confidence = float(inferred.get("confidence") or 0)
            if confidence >= 0.7:
                title = str(inferred.get("title") or title).strip()
                author = str(inferred.get("author") or author).strip()
                series = str(inferred.get("series") or series or "").strip() or None
                inferred_index = _safe_float(inferred.get("series_index"))
                series_index = inferred_index if inferred_index and inferred_index > 0 else series_index
                for key in ("isbn_10", "isbn_13"):
                    isbn = clean_isbn(inferred.get(key))
                    if isbn:
                        evidence.remote_ids[key] = isbn
                reason = str(inferred.get("reason") or "").strip()
                reasons.append(f"LLM-confirmed EPUB identity{f': {reason}' if reason else ''}")
                used_llm = True
        except Exception:
            logger.warning(
                "LLM EPUB identity inference failed for book %s; using deterministic evidence.", book.id, exc_info=True
            )

    stored_remote_ids = book.metadata_remote_ids if isinstance(book.metadata_remote_ids, dict) else {}
    remote_ids = {**stored_remote_ids, **evidence.remote_ids}
    return SearchIdentity(
        title=title,
        author=author,
        series=series,
        series_index=series_index,
        remote_ids={key: str(value) for key, value in remote_ids.items() if value},
        evidence_note="; ".join(reasons) if reasons else None,
        used_llm=used_llm,
        opening_excerpt=evidence.opening_content[:4000],
    )
