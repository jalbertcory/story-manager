"""Shared library file-health inspection used by dashboards and maintenance tools."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, TypedDict, NotRequired

from ..models import Book, SourceType


class LibraryFileIssue(TypedDict):
    book_id: int
    title: str | None
    author: str | None
    issue: str
    source_url: NotRequired[str]
    path: NotRequired[str]


def _file_issue(book: Book, issue: str, *, source_url: str | None = None, path: str | None = None) -> LibraryFileIssue:
    result: LibraryFileIssue = {"book_id": book.id, "title": book.title, "author": book.author, "issue": issue}
    if source_url is not None:
        result["source_url"] = source_url
    if path is not None:
        result["path"] = path
    return result


def is_failed_web_import_placeholder(book: Book) -> bool:
    return bool(book.source_url and book.download_status == "error" and not book.immutable_path and not book.current_path)


def inspect_library_files(books: Iterable[Book], *, library_path: Path) -> list[LibraryFileIssue]:
    """Return missing or broken EPUB and cover paths for the supplied books."""
    issues: list[LibraryFileIssue] = []
    for book in books:
        if book.source_url and not book.immutable_path and not book.current_path:
            if book.download_status == "pending":
                issues.append(_file_issue(book, "pending_web_import", source_url=str(book.source_url)))
                continue
            if is_failed_web_import_placeholder(book):
                issues.append(_file_issue(book, "failed_web_import", source_url=str(book.source_url)))
                continue

        if not book.immutable_path and book.source_type != SourceType.audiobook:
            issues.append(_file_issue(book, "missing_immutable_path"))
        elif book.immutable_path:
            full_path = library_path.parent / book.immutable_path
            if not full_path.exists():
                issues.append(_file_issue(book, "immutable_file_not_found", path=book.immutable_path))

        if not book.current_path and book.source_type != SourceType.audiobook:
            issues.append(_file_issue(book, "missing_current_path"))
        elif book.current_path:
            full_path = library_path.parent / book.current_path
            if not full_path.exists():
                issues.append(_file_issue(book, "current_file_not_found", path=book.current_path))

        if book.cover_path:
            full_path = library_path.parent / book.cover_path
            if not full_path.exists():
                issues.append(_file_issue(book, "cover_file_not_found", path=book.cover_path))

    return issues


def find_missing_covers(books: Iterable[Book], *, library_path: Path) -> list[LibraryFileIssue]:
    """Return completed books with no usable local cover image."""
    issues: list[LibraryFileIssue] = []
    for book in books:
        if book.download_status == "pending" or is_failed_web_import_placeholder(book):
            continue
        if not book.cover_path:
            issues.append(_file_issue(book, "missing_cover"))
            continue
        if not (library_path.parent / book.cover_path).exists():
            issues.append(_file_issue(book, "cover_file_not_found", path=book.cover_path))
    return issues
