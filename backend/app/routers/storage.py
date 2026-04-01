"""Storage cleanup and in-memory log endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..database import get_db
from ..logging_config import _LOG_BUFFER

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/logs")
async def get_logs(limit: int = 200, level: Optional[str] = None):
    entries = list(_LOG_BUFFER)
    if level:
        upper = level.upper()
        entries = [e for e in entries if e["level"] == upper]
    return entries[-limit:]


@router.get("/api/library/validate")
async def validate_library(db: AsyncSession = Depends(get_db)):
    """
    Check every book record for missing or broken file paths.
    Returns a list of issues found (empty list means everything is healthy).
    """
    books = await crud.get_books(db, limit=100000)
    issues: list[dict] = []
    for book in books:
        book_info = {"book_id": book.id, "title": book.title, "author": book.author}
        if not book.immutable_path:
            issues.append({**book_info, "issue": "missing_immutable_path"})
        else:
            full = LIBRARY_PATH.parent / book.immutable_path
            if not full.exists():
                issues.append({**book_info, "issue": "immutable_file_not_found", "path": book.immutable_path})
        if not book.current_path:
            issues.append({**book_info, "issue": "missing_current_path"})
        else:
            full = LIBRARY_PATH.parent / book.current_path
            if not full.exists():
                issues.append({**book_info, "issue": "current_file_not_found", "path": book.current_path})
        if book.cover_path:
            full = LIBRARY_PATH.parent / book.cover_path
            if not full.exists():
                issues.append({**book_info, "issue": "cover_file_not_found", "path": book.cover_path})

    if issues:
        logger.warning("Library validation found %d issue(s)", len(issues))
    return {"total_books": len(books), "issues_count": len(issues), "issues": issues}


@router.post("/api/storage/cleanup")
async def cleanup_storage(dry_run: bool = True, db: AsyncSession = Depends(get_db)):
    """
    Scans the library directory for files not referenced by any book record.
    dry_run=True (default): returns what would be deleted without deleting.
    dry_run=False: deletes orphaned files and returns what was deleted.
    """
    if not LIBRARY_PATH.exists():
        return {"dry_run": dry_run, "files": [], "total_bytes": 0}

    books = await crud.get_books(db, limit=100000)

    # Refuse to run if any downloads are still in progress — their files
    # are not yet recorded in the DB and would be incorrectly flagged.
    pending = [b for b in books if b.download_status == "pending"]
    if pending:
        return {
            "dry_run": dry_run,
            "files": [],
            "total_bytes": 0,
            "skipped_reason": f"{len(pending)} book(s) are still downloading. " "Run cleanup after all downloads complete.",
        }

    # Use case-folded paths for comparison so case-insensitive filesystems
    # (macOS HFS+/APFS) don't cause false orphan detections when the DB
    # stores a different casing than what's on disk.
    tracked: set[str] = set()
    for book in books:
        if book.immutable_path:
            tracked.add(str((LIBRARY_PATH.parent / book.immutable_path).resolve()).casefold())
        if book.current_path:
            tracked.add(str((LIBRARY_PATH.parent / book.current_path).resolve()).casefold())
        if book.cover_path:
            tracked.add(str((LIBRARY_PATH.parent / book.cover_path).resolve()).casefold())

    orphans = []
    for file in LIBRARY_PATH.rglob("*"):
        if not file.is_file():
            continue
        path_str = str(file.resolve())
        if path_str.casefold() not in tracked:
            size = file.stat().st_size
            orphans.append({"path": str(file.relative_to(LIBRARY_PATH.parent)), "size_bytes": size})

    total_bytes = sum(f["size_bytes"] for f in orphans)

    if not dry_run:
        for f in orphans:
            full = LIBRARY_PATH.parent / f["path"]
            logger.info("Storage cleanup: deleting %s", f["path"])
            full.unlink(missing_ok=True)
        logger.info(f"Storage cleanup: deleted {len(orphans)} orphaned files ({total_bytes} bytes)")

    return {"dry_run": dry_run, "files": orphans, "total_bytes": total_bytes}
