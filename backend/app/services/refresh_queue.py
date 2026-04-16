"""Single-worker queue for manual 'refresh from source' jobs."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .. import crud
from ..database import SessionLocal
from .web_novel import run_book_refresh

logger = logging.getLogger(__name__)


class RefreshQueue:
    """App-scoped queue that processes one book refresh at a time.

    Mirrors :class:`WebImportQueue` — a single asyncio worker drains a queue
    of book IDs, running :func:`run_book_refresh` for each. The book's
    ``refresh_status`` column is the source of truth for UI polling; this
    queue only tracks in-memory set membership to avoid double-enqueueing.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Optional[int]] = asyncio.Queue()
        self._queued_book_ids: set[int] = set()
        self._worker_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._run(), name="refresh-worker")

    async def stop(self) -> None:
        if not self._worker_task:
            return
        await self._queue.put(None)
        await self._worker_task
        self._worker_task = None
        self._queued_book_ids.clear()

    async def enqueue(self, book_id: int) -> bool:
        if book_id in self._queued_book_ids:
            return False
        self._queued_book_ids.add(book_id)
        await self._queue.put(book_id)
        return True

    async def requeue_pending_books(self) -> int:
        """Resume any refreshes that were in-flight when the app was last shut down."""
        async with SessionLocal() as db:
            books = await crud.get_pending_refresh_books(db)

        queued = 0
        for book in books:
            if not book.source_url:
                continue
            if await self.enqueue(book.id):
                queued += 1
        return queued

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return

                book_id = item
                try:
                    await run_book_refresh(book_id)
                except Exception:
                    logger.exception("Unhandled exception while refreshing book %s.", book_id)
                finally:
                    self._queued_book_ids.discard(book_id)
            finally:
                self._queue.task_done()


_refresh_queue = RefreshQueue()


def get_refresh_queue() -> RefreshQueue:
    return _refresh_queue
