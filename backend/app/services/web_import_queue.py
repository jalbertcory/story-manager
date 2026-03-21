"""Single-worker queue for web novel imports."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .. import crud
from ..database import SessionLocal
from .web_novel import finish_web_novel_download

logger = logging.getLogger(__name__)


class WebImportQueue:
    """App-scoped queue that processes one web import at a time."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Optional[tuple[int, str]]] = asyncio.Queue()
        self._queued_book_ids: set[int] = set()
        self._worker_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._run(), name="web-import-worker")

    async def stop(self) -> None:
        if not self._worker_task:
            return
        await self._queue.put(None)
        await self._worker_task
        self._worker_task = None
        self._queued_book_ids.clear()

    async def enqueue(self, book_id: int, source_url: str) -> bool:
        if book_id in self._queued_book_ids:
            return False
        self._queued_book_ids.add(book_id)
        await self._queue.put((book_id, source_url))
        return True

    async def requeue_pending_books(self) -> int:
        async with SessionLocal() as db:
            books = await crud.get_pending_web_books(db)

        queued = 0
        for book in books:
            if not book.source_url:
                continue
            if await self.enqueue(book.id, str(book.source_url)):
                queued += 1
        return queued

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return

                book_id, source_url = item
                try:
                    await finish_web_novel_download(book_id, source_url)
                except Exception:
                    logger.exception("Unhandled exception while importing web book %s.", book_id)
                finally:
                    self._queued_book_ids.discard(book_id)
            finally:
                self._queue.task_done()


_web_import_queue = WebImportQueue()


def get_web_import_queue() -> WebImportQueue:
    return _web_import_queue
