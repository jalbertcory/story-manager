"""Helpers for storing and cleaning library files."""

import re
from pathlib import Path

from ..config import LIBRARY_PATH


def _safe_segment(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^\w\s.-]", "", value or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or fallback


def get_author_library_dir(author: str) -> Path:
    safe_name = _safe_segment(author, "Unknown Author")
    author_dir = LIBRARY_PATH / safe_name
    author_dir.mkdir(parents=True, exist_ok=True)
    # On case-insensitive filesystems (macOS), the directory may already exist
    # with different casing. Resolve to the actual filesystem casing so DB
    # paths match the real directory name.
    try:
        for entry in LIBRARY_PATH.iterdir():
            if entry.is_dir() and entry.name.lower() == safe_name.lower():
                return entry
    except OSError:
        pass
    return author_dir


def build_book_paths(filename: str, author: str) -> tuple[Path, Path]:
    safe_filename = _safe_segment(filename, "book.epub")
    if not safe_filename.lower().endswith(".epub"):
        safe_filename = f"{safe_filename}.epub"

    author_dir = get_author_library_dir(author)
    current_path = author_dir / safe_filename
    immutable_path = author_dir / f"immutable_{safe_filename}"
    return immutable_path, current_path


def remove_empty_parent_dirs(path: Path) -> None:
    current = path.parent
    library_root = LIBRARY_PATH.resolve()
    while current != library_root and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
