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
    tracked: set[str] = set()
    for book in books:
        if book.immutable_path:
            tracked.add(str((LIBRARY_PATH.parent / book.immutable_path).resolve()))
        if book.current_path:
            tracked.add(str((LIBRARY_PATH.parent / book.current_path).resolve()))
        if book.cover_path:
            tracked.add(str((LIBRARY_PATH.parent / book.cover_path).resolve()))

    orphans = []
    for file in LIBRARY_PATH.rglob("*"):
        if not file.is_file():
            continue
        path_str = str(file.resolve())
        if path_str not in tracked:
            size = file.stat().st_size
            orphans.append({"path": str(file.relative_to(LIBRARY_PATH.parent)), "size_bytes": size})

    total_bytes = sum(f["size_bytes"] for f in orphans)

    if not dry_run:
        for f in orphans:
            full = LIBRARY_PATH.parent / f["path"]
            full.unlink(missing_ok=True)
        logger.info(f"Storage cleanup: deleted {len(orphans)} orphaned files ({total_bytes} bytes)")

    return {"dry_run": dry_run, "files": orphans, "total_bytes": total_bytes}
