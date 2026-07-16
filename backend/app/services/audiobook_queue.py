"""Single-worker queue for the audiobook pipeline."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from .. import crud
from ..database import SessionLocal
from .audiobook_ingestion import ingest_epub
from .audiobook_llm import generate_character_roster, diarize_sentences
from .audiobook_tts import generate_audio_for_book
from .audiobook_assembly import assemble_book

logger = logging.getLogger(__name__)

# Ordered pipeline phases; the worker resumes from wherever the book's status is.
_PHASE_ORDER = [
    "ingesting",
    "roster_gen",
    "diarizing",
    "audio_gen",
    "assembling",
]


class AudiobookQueue:
    """App-scoped queue that processes one audiobook pipeline job at a time."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Optional[int]] = asyncio.Queue()
        self._queued_book_ids: set[int] = set()
        # A pipeline mutation may arrive while a book is already running. Keep
        # one follow-up job so the mutation is not lost when the current worker
        # finishes.
        self._rerun_book_ids: set[int] = set()
        self._worker_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._run(), name="audiobook-worker")

    async def stop(self) -> None:
        if not self._worker_task:
            return
        await self._queue.put(None)
        await self._worker_task
        self._worker_task = None
        self._queued_book_ids.clear()
        self._rerun_book_ids.clear()

    async def enqueue(self, book_id: int) -> bool:
        if book_id in self._queued_book_ids:
            self._rerun_book_ids.add(book_id)
            return False
        self._queued_book_ids.add(book_id)
        await self._queue.put(book_id)
        return True

    def has_book_job(self, book_id: int) -> bool:
        """Return whether a book is queued or currently being processed."""
        return book_id in self._queued_book_ids

    async def requeue_in_progress(self) -> int:
        async with SessionLocal() as db:
            books = await crud.audiobook.get_in_progress_audiobook_books(db)
        queued = 0
        for book in books:
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
                    await self._process(book_id)
                except Exception:
                    logger.exception("Unhandled exception in audiobook pipeline for book %s.", book_id)
                    async with SessionLocal() as db:
                        await crud.audiobook.set_book_pipeline_status(db, book_id, "error")
                finally:
                    self._queued_book_ids.discard(book_id)
                    if book_id in self._rerun_book_ids:
                        self._rerun_book_ids.discard(book_id)
                        await self.enqueue(book_id)
            finally:
                self._queue.task_done()

    async def _process(self, book_id: int) -> None:
        """Run the pipeline from the book's current status to completion."""
        async with SessionLocal() as db:
            from ..models import Book

            book = await db.get(Book, book_id)
            if book is None:
                logger.warning("Book %s not found; skipping pipeline.", book_id)
                return
            current_status = book.audiobook_pipeline_status

        if current_status == "paused":
            logger.info("Book %s is paused; skipping pipeline.", book_id)
            return

        if current_status not in _PHASE_ORDER and current_status != "ingesting":
            # Default: start from the beginning
            current_status = "ingesting"
            async with SessionLocal() as db:
                await crud.audiobook.set_book_pipeline_status(db, book_id, "ingesting")

        start_idx = _PHASE_ORDER.index(current_status) if current_status in _PHASE_ORDER else 0

        for phase in _PHASE_ORDER[start_idx:]:
            logger.info("Book %s: running phase '%s'.", book_id, phase)
            async with SessionLocal() as db:
                if phase == "ingesting":
                    await ingest_epub(book_id, db)
                elif phase == "roster_gen":
                    await generate_character_roster(book_id, db)
                elif phase == "diarizing":
                    await diarize_sentences(book_id, db)
                elif phase == "audio_gen":
                    await generate_audio_for_book(book_id, db)
                elif phase == "assembling":
                    await assemble_book(book_id, db)

            # Check if the book was paused mid-pipeline
            async with SessionLocal() as db:
                from ..models import Book

                book = await db.get(Book, book_id)
                if book and book.audiobook_pipeline_status == "paused":
                    logger.info("Book %s paused after phase '%s'.", book_id, phase)
                    return

        logger.info("Audiobook pipeline complete for book %s.", book_id)


_audiobook_queue = AudiobookQueue()


def get_audiobook_queue() -> AudiobookQueue:
    return _audiobook_queue
