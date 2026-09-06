"""Durable serial worker for imported-audiobook timestamp alignment."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, cast

from sqlalchemy import Table, select

from ..database import SessionLocal
from ..models import ImportedAudiobook
from .audiobook_alignment import process_alignment

logger = logging.getLogger(__name__)


class AudiobookAlignmentQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Optional[int]] = asyncio.Queue()
        self._queued_ids: set[int] = set()
        self._worker_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._run(), name="audiobook-alignment-worker")

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
        self._worker_task = None
        self._queue = asyncio.Queue()
        self._queued_ids.clear()

    async def enqueue(self, edition_id: int) -> bool:
        if edition_id in self._queued_ids:
            return False
        self._queued_ids.add(edition_id)
        await self._queue.put(edition_id)
        return True

    async def requeue_pending(self) -> int:
        async with SessionLocal() as db:
            result = await db.execute(select(ImportedAudiobook.id).where(ImportedAudiobook.status == "aligning"))
            ids = list(result.scalars().all())
            if ids:
                await db.execute(
                    cast(Table, ImportedAudiobook.__table__)
                    .update()
                    .where(ImportedAudiobook.id.in_(ids))
                    .values(progress_detail="Timestamp alignment queued after restart")
                )
                await db.commit()
        return sum([await self.enqueue(edition_id) for edition_id in ids])

    async def _run(self) -> None:
        while True:
            edition_id = await self._queue.get()
            try:
                if edition_id is None:
                    return
                async with SessionLocal() as db:
                    await process_alignment(edition_id, db)
            except Exception:
                logger.exception("Unhandled audiobook alignment failure for edition %s.", edition_id)
            finally:
                if edition_id is not None:
                    self._queued_ids.discard(edition_id)
                self._queue.task_done()


_queue: AudiobookAlignmentQueue | None = None


def get_audiobook_alignment_queue() -> AudiobookAlignmentQueue:
    global _queue
    if _queue is None:
        _queue = AudiobookAlignmentQueue()
    return _queue
