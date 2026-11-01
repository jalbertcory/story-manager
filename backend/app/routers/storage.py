"""Storage cleanup and persistent log endpoints."""

from .. import api_schemas as contracts
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, TypedDict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud, models
from ..config import LIBRARY_PATH
from ..crud.processing import ACTIVE_PROCESSING_STATUSES
from ..database import get_db
from ..logging_config import is_quiet_successful_access_entry, read_persisted_logs
from ..services.library_health import LibraryFileIssue, inspect_library_files, is_failed_web_import_placeholder
from ..services.library_paths import LIBRARY_STAGING_DIRNAME
from ..services.web_novel import is_fanficfare_running

logger = logging.getLogger(__name__)
_ui_logger = logging.getLogger("frontend")

router = APIRouter()


class OrphanedFile(TypedDict):
    path: str
    size_bytes: int


# Files this new may still be in the middle of an upload, download or rewrite
# whose database row is not committed yet.
RECENT_FILE_GRACE_SECONDS = 15 * 60
# Staging leftovers older than this come from interrupted uploads or downloads.
STALE_STAGING_SECONDS = 24 * 60 * 60


class ClientLogEntry(BaseModel):
    level: str = "ERROR"
    message: str
    source: Optional[str] = None


@router.post("/api/logs/client", response_model=contracts.OkResponse)
async def post_client_log(entry: ClientLogEntry) -> contracts.OkResponse:
    """Receive log entries from the frontend UI."""
    msg = entry.message
    if entry.source:
        msg = f"[{entry.source}] {msg}"
    level = getattr(logging, entry.level.upper(), logging.ERROR)
    _ui_logger.log(level, msg)
    return {"ok": True}


@router.get("/api/logs", response_model=list[contracts.LogEntry])
async def get_logs(
    limit: int = Query(default=200, ge=1, le=1000),
    level: Optional[str] = None,
    request_id: Optional[str] = None,
    job_id: Optional[int] = None,
    include_polling: bool = False,
) -> list[contracts.LogEntry]:
    entries = read_persisted_logs(limit=1000, level=level)
    if not include_polling:
        entries = [entry for entry in entries if not is_quiet_successful_access_entry(entry)]
    if request_id:
        entries = [entry for entry in entries if entry.get("request_id") == request_id]
    if job_id is not None:
        entries = [entry for entry in entries if entry.get("job_id") == job_id]
    return entries[-limit:]


@router.get("/api/library/validate", response_model=contracts.LibraryValidation)
async def validate_library(db: AsyncSession = Depends(get_db)) -> contracts.LibraryValidation:
    """
    Check every book record for missing or broken file paths.
    Returns a list of issues found (empty list means everything is healthy).
    """
    books = await crud.get_books_for_file_health(db)
    issues = await asyncio.to_thread(inspect_library_files, books, library_path=LIBRARY_PATH)

    if issues:
        logger.warning("Library validation found %d issue(s)", len(issues))
    return {"total_books": len(books), "issues_count": len(issues), "issues": issues}


@router.post("/api/storage/cleanup", response_model=contracts.StorageCleanup)
async def cleanup_storage(dry_run: bool = True, db: AsyncSession = Depends(get_db)) -> contracts.StorageCleanup:
    """
    Scans the library directory for files not referenced by any book record and
    failed web-import placeholder books that never produced EPUB files.
    dry_run=True (default): returns what would be deleted without deleting.
    dry_run=False: deletes orphaned files and failed placeholder books.
    """
    if not LIBRARY_PATH.exists():
        return {"dry_run": dry_run, "files": [], "books": [], "total_bytes": 0}

    books = await crud.get_all_books_including_deleted(db)
    active_books = [book for book in books if book.deleted_at is None]
    failed_import_books: list[LibraryFileIssue] = [
        {
            "book_id": book.id,
            "title": book.title,
            "author": book.author,
            "source_url": book.source_url or "",
            "issue": "failed_web_import",
        }
        for book in active_books
        if is_failed_web_import_placeholder(book)
    ]

    # Refuse to run while anything may be writing library files that are not
    # recorded in the database yet.
    busy_reason = await _library_busy_reason(db)
    if busy_reason:
        return {
            "dry_run": dry_run,
            "files": [],
            "books": [],
            "total_bytes": 0,
            "skipped_reason": busy_reason,
        }

    # Use case-folded paths for comparison so case-insensitive filesystems
    # (macOS HFS+/APFS) don't cause false orphan detections when the DB
    # stores a different casing than what's on disk.
    tracked: set[str] = set()
    tracked_directories: set[str] = set()
    for book in books:
        if book.immutable_path:
            tracked.add(str((LIBRARY_PATH.parent / book.immutable_path).resolve()).casefold())
        if book.current_path:
            tracked.add(str((LIBRARY_PATH.parent / book.current_path).resolve()).casefold())
        if book.cover_path:
            tracked.add(str((LIBRARY_PATH.parent / book.cover_path).resolve()).casefold())
        tracked_directories.add(str((LIBRARY_PATH / "audiobooks" / str(book.id)).resolve()).casefold())

    orphans = await asyncio.to_thread(_find_orphaned_files, tracked, tracked_directories, time.time())
    total_bytes = sum(f["size_bytes"] for f in orphans)

    if not dry_run:
        deleted = await asyncio.to_thread(_delete_orphaned_files, orphans, time.time())
        if len(deleted) != len(orphans):
            orphans = deleted
            total_bytes = sum(f["size_bytes"] for f in orphans)
        for book in active_books:
            if not is_failed_web_import_placeholder(book):
                continue
            logger.info("Storage cleanup: deleting failed web import placeholder book %s (%s)", book.id, book.source_url)
            await crud.delete_book(db, book=book)
        if failed_import_books:
            await crud.cleanup_orphaned_series_metadata(db)
        logger.info(f"Storage cleanup: deleted {len(orphans)} orphaned files ({total_bytes} bytes)")

    return {"dry_run": dry_run, "files": orphans, "books": failed_import_books, "total_bytes": total_bytes}


async def _library_busy_reason(db: AsyncSession) -> str | None:
    # Web imports and refreshes run as processing jobs, so active jobs cover them.
    # Book status columns are not checked: a cancelled or failed job can leave
    # them set forever.
    if is_fanficfare_running():
        return "A web novel download or update is running. Run cleanup after it completes."
    active_jobs = await db.scalar(
        select(func.count(models.ProcessingJob.id)).where(models.ProcessingJob.status.in_(ACTIVE_PROCESSING_STATUSES))
    )
    if active_jobs:
        return f"{active_jobs} processing job(s) are queued or running. Run cleanup after they finish."
    return None


def _is_temporary_write(name: str) -> bool:
    """Whether ``name`` looks like the app's own ``.<file name>.<suffix>`` temp file."""
    return name.startswith(".") and "." in name[1:]


def _is_cleanup_candidate(relative: Path, mtime: float, now: float) -> bool:
    """Whether an untracked file is old enough and outside protected areas to delete."""
    age = now - mtime
    if relative.parts[0] == LIBRARY_STAGING_DIRNAME:
        return age >= STALE_STAGING_SECONDS
    if any(part.startswith(".") for part in relative.parts[:-1]):
        # Hidden directories hold restore safety copies or belong to other tools.
        return False
    if relative.name.startswith("."):
        # Temp files left by interrupted atomic writes; other dotfiles such as
        # .DS_Store or sync-tool markers are left alone.
        return _is_temporary_write(relative.name) and age >= STALE_STAGING_SECONDS
    return age >= RECENT_FILE_GRACE_SECONDS


def _find_orphaned_files(tracked: set[str], tracked_directories: set[str], now: float) -> list[OrphanedFile]:
    orphans: list[OrphanedFile] = []
    for file in LIBRARY_PATH.rglob("*"):
        try:
            if file.is_symlink() or not file.is_file():
                continue
            stat = file.stat()
        except OSError:
            continue
        resolved = file.resolve()
        if str(resolved).casefold() in tracked:
            continue
        if any(str(parent).casefold() in tracked_directories for parent in resolved.parents):
            continue
        if not _is_cleanup_candidate(file.relative_to(LIBRARY_PATH), stat.st_mtime, now):
            continue
        orphans.append({"path": str(file.relative_to(LIBRARY_PATH.parent)), "size_bytes": stat.st_size})
    return orphans


def _delete_orphaned_files(orphans: list[OrphanedFile], now: float) -> list[OrphanedFile]:
    """Delete the listed files, skipping any that changed since the scan."""
    library_root = LIBRARY_PATH.resolve()
    deleted: list[OrphanedFile] = []
    for orphan in orphans:
        full = LIBRARY_PATH.parent / orphan["path"]
        try:
            if not full.resolve().is_relative_to(library_root):
                continue
            if not _is_cleanup_candidate(full.relative_to(LIBRARY_PATH), full.stat().st_mtime, now):
                continue
            logger.info("Storage cleanup: deleting %s", orphan["path"])
            full.unlink()
        except FileNotFoundError:
            continue
        deleted.append(orphan)
    _prune_empty_staging_dirs()
    return deleted


def _prune_empty_staging_dirs() -> None:
    """Remove empty per-download directories left in the staging area."""
    staging = LIBRARY_PATH / LIBRARY_STAGING_DIRNAME
    if not staging.is_dir():
        return
    for directory in sorted((d for d in staging.rglob("*") if d.is_dir() and not d.is_symlink()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue
