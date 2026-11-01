"""Helpers for storing and cleaning library files."""

import os
import re
import tempfile
from pathlib import Path

from ..config import LIBRARY_PATH


def _safe_segment(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^\w\s.-]", "", value or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or fallback


LIBRARY_STAGING_DIRNAME = ".staging"


def library_staging_dir() -> Path:
    """Directory for in-progress uploads and downloads.

    It lives inside the library so finished files can be renamed into place on the
    same filesystem, and is kept apart so nothing scans in-progress files as books.
    """
    staging = LIBRARY_PATH / LIBRARY_STAGING_DIRNAME
    staging.mkdir(parents=True, exist_ok=True)
    return staging


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


def reserve_book_paths(filename: str, author: str, max_attempts: int = 1000) -> tuple[Path, Path]:
    """Return ``build_book_paths`` targets that no other file is using.

    Both paths are created empty with an exclusive create so a concurrent caller
    cannot claim the same names. Callers must replace them with real content and
    may unlink them on failure. A numeric suffix is added when the plain name is taken.
    """
    stem = filename[:-5] if filename.lower().endswith(".epub") else filename
    for attempt in range(1, max_attempts + 1):
        candidate = filename if attempt == 1 else f"{stem} - {attempt}.epub"
        immutable_path, current_path = build_book_paths(candidate, author)
        try:
            immutable_path.open("xb").close()
        except FileExistsError:
            continue
        try:
            current_path.open("xb").close()
        except FileExistsError:
            immutable_path.unlink(missing_ok=True)
            continue
        return immutable_path, current_path
    raise FileExistsError(f"No free library path for {filename!r} after {max_attempts} attempts")


def remove_empty_parent_dirs(path: Path) -> None:
    current = path.parent
    library_root = LIBRARY_PATH.resolve()
    while current != library_root and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def write_file_atomically(path: Path, data: bytes) -> None:
    """Replace ``path`` in one step so readers never see a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_library_file(relative_path: str | None) -> Path | None:
    """Resolve a stored ``library/...`` path, refusing anything outside the library."""
    if not relative_path:
        return None
    path = (LIBRARY_PATH.parent / relative_path).resolve()
    return path if path.is_relative_to(LIBRARY_PATH.resolve()) else None


def audiobooks_root() -> Path:
    """Directory holding every book's generated, imported and reader audiobook files."""
    return LIBRARY_PATH / "audiobooks"


def book_audiobook_dir(book_id: int) -> Path:
    return audiobooks_root() / str(book_id)
