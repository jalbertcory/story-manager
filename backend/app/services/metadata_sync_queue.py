"""Single-worker queue for background metadata sync jobs."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .. import crud
from ..database import SessionLocal
from .metadata_jobs import process_metadata_sync_job

logger = logging.getLogger(__name__)


class MetadataSyncQueue:
    """App-scoped queue that processes one metadata sync job at a time."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Optional[int]] = asyncio.Queue()
        self._queued_job_ids: set[int] = set()
        self._worker_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._run(), name="metadata-sync-worker")

    async def stop(self) -> None:
        if not self._worker_task:
            return
        await self._queue.put(None)
        await self._worker_task
        self._worker_task = None
        self._queued_job_ids.clear()

    async def enqueue(self, job_id: int) -> bool:
        if job_id in self._queued_job_ids:
            return False
        self._queued_job_ids.add(job_id)
        await self._queue.put(job_id)
        return True

    async def requeue_pending_jobs(self) -> int:
        async with SessionLocal() as db:
            await crud.reset_running_metadata_sync_jobs(db)
            jobs = await crud.get_pending_metadata_sync_jobs(db)

        queued = 0
        for job in jobs:
            if await self.enqueue(job.id):
                queued += 1
        return queued

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return

                job_id = item
                try:
                    async with SessionLocal() as db:
                        await process_metadata_sync_job(db, job_id)
                except Exception:
                    logger.exception("Unhandled exception while processing metadata sync job %s.", job_id)
                finally:
                    self._queued_job_ids.discard(job_id)
            finally:
                self._queue.task_done()


_metadata_sync_queue = MetadataSyncQueue()


def get_metadata_sync_queue() -> MetadataSyncQueue:
    return _metadata_sync_queue
