"""Shared library file-health inspection used by dashboards and maintenance tools."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..models import Book


def is_failed_web_import_placeholder(book: Book) -> bool:
    return bool(book.source_url and book.download_status == "error" and not book.immutable_path and not book.current_path)


def inspect_library_files(books: Iterable[Book], *, library_path: Path) -> list[dict]:
    """Return missing or broken EPUB and cover paths for the supplied books."""
    issues: list[dict] = []
    for book in books:
        book_info = {"book_id": book.id, "title": book.title, "author": book.author}
        if book.source_url and not book.immutable_path and not book.current_path:
            if book.download_status == "pending":
                issues.append({**book_info, "issue": "pending_web_import", "source_url": str(book.source_url)})
                continue
            if is_failed_web_import_placeholder(book):
                issues.append({**book_info, "issue": "failed_web_import", "source_url": str(book.source_url)})
                continue

        if not book.immutable_path:
            issues.append({**book_info, "issue": "missing_immutable_path"})
        else:
            full_path = library_path.parent / book.immutable_path
            if not full_path.exists():
                issues.append({**book_info, "issue": "immutable_file_not_found", "path": book.immutable_path})

        if not book.current_path:
            issues.append({**book_info, "issue": "missing_current_path"})
        else:
            full_path = library_path.parent / book.current_path
            if not full_path.exists():
                issues.append({**book_info, "issue": "current_file_not_found", "path": book.current_path})

        if book.cover_path:
            full_path = library_path.parent / book.cover_path
            if not full_path.exists():
                issues.append({**book_info, "issue": "cover_file_not_found", "path": book.cover_path})

    return issues


def find_missing_covers(books: Iterable[Book], *, library_path: Path) -> list[dict]:
    """Return completed books with no usable local cover image."""
    issues: list[dict] = []
    for book in books:
        if book.download_status == "pending" or is_failed_web_import_placeholder(book):
            continue
        if not book.cover_path:
            issues.append(
                {
                    "book_id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "issue": "missing_cover",
                }
            )
            continue
        if not (library_path.parent / book.cover_path).exists():
            issues.append(
                {
                    "book_id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "issue": "cover_file_not_found",
                    "path": book.cover_path,
                }
            )
    return issues
