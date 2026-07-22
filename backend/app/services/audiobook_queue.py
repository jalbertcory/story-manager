"""Single-worker queue for the audiobook pipeline."""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
from typing import Optional

from .. import crud
from ..database import SessionLocal
from .audiobook_ingestion import ingest_epub
from .audiobook_llm import generate_character_roster, diarize_sentences
from .audiobook_tts import (
    TTS_BATCH_SIZE,
    generate_audio_for_book,
    generate_audio_for_chapter_preview,
    generate_audio_for_sentence,
    generate_audio_for_sentences,
)
from .audiobook_assembly import assemble_book, assemble_chapter_preview

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
        self._queue: asyncio.Queue[Optional[int | tuple[str, int, int]]] = asyncio.Queue()
        self._background_audio_queue: asyncio.PriorityQueue[tuple[int, int, tuple[int, list[int], bool]]] = (
            asyncio.PriorityQueue()
        )
        self._background_audio_sequence = itertools.count()
        self._queued_book_ids: set[int] = set()
        # A pipeline mutation may arrive while a book is already running. Keep
        # one follow-up job so the mutation is not lost when the current worker
        # finishes.
        self._rerun_book_ids: set[int] = set()
        self._queued_preview_ids: set[int] = set()
        self._queued_sentence_ids: set[int] = set()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._background_audio_tasks: list[asyncio.Task[None]] = []
        self._background_audio_ids: dict[int, set[int]] = {}
        self._background_audio_condition = asyncio.Condition()

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._run(), name="audiobook-worker")
        worker_count = max(1, int(os.getenv("AUDIOBOOK_TTS_WORKERS", "1")))
        self._background_audio_tasks = [
            asyncio.create_task(
                self._run_background_audio(),
                name=f"audiobook-tts-worker-{index + 1}",
            )
            for index in range(worker_count)
        ]

    async def stop(self) -> None:
        if not self._worker_task:
            return
        tasks = [self._worker_task, *self._background_audio_tasks]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._worker_task = None
        self._background_audio_tasks.clear()
        self._queue = asyncio.Queue()
        self._background_audio_queue = asyncio.PriorityQueue()
        self._background_audio_sequence = itertools.count()
        self._queued_book_ids.clear()
        self._rerun_book_ids.clear()
        self._queued_preview_ids.clear()
        self._queued_sentence_ids.clear()
        self._background_audio_ids.clear()

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

    async def enqueue_preview(self, book_id: int, chapter_id: int) -> bool:
        if chapter_id in self._queued_preview_ids:
            return False
        self._queued_preview_ids.add(chapter_id)
        await self._queue.put(("preview", book_id, chapter_id))
        return True

    async def enqueue_sentence_audio(self, book_id: int, sentence_id: int) -> bool:
        if sentence_id in self._queued_sentence_ids:
            return False
        self._queued_sentence_ids.add(sentence_id)
        await self._background_audio_queue.put((0, next(self._background_audio_sequence), (book_id, [sentence_id], True)))
        return True

    async def enqueue_background_audio(self, book_id: int, sentence_ids: list[int]) -> None:
        """Queue durable, analyzed sentences for the pipelined TTS lane."""
        async with self._background_audio_condition:
            queued_ids = self._background_audio_ids.setdefault(book_id, set())
            new_ids = []
            for sentence_id in sentence_ids:
                if sentence_id in queued_ids:
                    continue
                queued_ids.add(sentence_id)
                new_ids.append(sentence_id)
            for start in range(0, len(new_ids), TTS_BATCH_SIZE):
                batch_ids = new_ids[slice(start, start + TTS_BATCH_SIZE)]
                await self._background_audio_queue.put(
                    (
                        1,
                        next(self._background_audio_sequence),
                        (book_id, batch_ids, False),
                    )
                )

    async def _wait_for_background_audio(self, book_id: int) -> None:
        """Wait for pipelined TTS while publishing phase-accurate progress."""
        while True:
            async with self._background_audio_condition:
                queued_count = len(self._background_audio_ids.get(book_id, ()))
                if not queued_count:
                    return

            async with SessionLocal() as db:
                counts = await crud.audiobook.count_sentences_by_status(db, book_id)
                generated_count = counts.get("audio_generated", 0)
                total_count = sum(counts.values())
                await crud.audiobook.update_book_pipeline_progress(
                    db,
                    book_id,
                    current=generated_count,
                    total=total_count,
                    detail=(f"Generating speech: {generated_count:,} of {total_count:,} clips " f"({queued_count:,} queued)"),
                )

            async with self._background_audio_condition:
                await self._background_audio_condition.wait_for(
                    lambda: len(self._background_audio_ids.get(book_id, ())) < queued_count
                )

    async def _run_background_audio(self) -> None:
        while True:
            _priority, _sequence, item = await self._background_audio_queue.get()
            try:
                book_id, sentence_ids, manual_request = item
                eligible_ids = []
                try:
                    async with SessionLocal() as db:
                        from ..models import AudiobookSentence, Book

                        book = await db.get(Book, book_id)
                        if book is None:
                            continue
                        if not manual_request and (
                            book.audiobook_pause_requested or book.audiobook_pipeline_status not in ("diarizing", "audio_gen")
                        ):
                            continue
                        for sentence_id in sentence_ids:
                            sentence = await db.get(AudiobookSentence, sentence_id)
                            if sentence is None:
                                continue
                            allowed_statuses = (
                                ("ready_for_audio", "audio_queued", "audio_generating")
                                if manual_request
                                else ("ready_for_audio",)
                            )
                            if sentence.status not in allowed_statuses:
                                continue
                            await crud.audiobook.set_sentence_status(
                                db,
                                sentence_id,
                                "audio_generating",
                            )
                            eligible_ids.append(sentence_id)
                        if not eligible_ids:
                            continue
                        if manual_request:
                            await generate_audio_for_sentence(book_id, eligible_ids[0], db)
                            failures = {}
                        else:
                            failures = await generate_audio_for_sentences(
                                book_id,
                                eligible_ids,
                                db,
                            )
                        for sentence_id, error in failures.items():
                            logger.error(
                                "Pipelined TTS failed for sentence %s in book %s: %s",
                                sentence_id,
                                book_id,
                                error,
                            )
                            await crud.audiobook.mark_sentence_error(db, sentence_id)
                except Exception:
                    logger.exception(
                        "Pipelined TTS batch failed for sentences %s in book %s.",
                        eligible_ids or sentence_ids,
                        book_id,
                    )
                    async with SessionLocal() as db:
                        for sentence_id in eligible_ids:
                            await crud.audiobook.mark_sentence_error(db, sentence_id)
            finally:
                book_id, sentence_ids, manual_request = item
                if manual_request:
                    self._queued_sentence_ids.difference_update(sentence_ids)
                async with self._background_audio_condition:
                    queued_ids = self._background_audio_ids.get(book_id)
                    if queued_ids is not None:
                        queued_ids.difference_update(sentence_ids)
                        if not queued_ids:
                            self._background_audio_ids.pop(book_id, None)
                    self._background_audio_condition.notify_all()
                self._background_audio_queue.task_done()

    async def requeue_in_progress(self) -> int:
        async with SessionLocal() as db:
            books = await crud.audiobook.get_in_progress_audiobook_books(db)
        queued = 0
        for book in books:
            if await self.enqueue(book.id):
                queued += 1
        async with SessionLocal() as db:
            preview_chapters = await crud.audiobook.get_chapters_with_pending_previews(db)
            for chapter in preview_chapters:
                await crud.audiobook.set_chapter_preview_status(db, chapter.id, "queued")
        for chapter in preview_chapters:
            if await self.enqueue_preview(chapter.book_id, chapter.id):
                queued += 1
        async with SessionLocal() as db:
            sentence_jobs = await crud.audiobook.get_pending_sentence_audio_jobs(db)
            for _book_id, sentence_id in sentence_jobs:
                await crud.audiobook.set_sentence_status(db, sentence_id, "audio_queued")
        for book_id, sentence_id in sentence_jobs:
            if await self.enqueue_sentence_audio(book_id, sentence_id):
                queued += 1
        return queued

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if item is None:
                    return
                if isinstance(item, tuple):
                    job_type, book_id, record_id = item
                    if job_type == "preview":
                        try:
                            await self._process_preview(book_id, record_id)
                        except Exception as exc:
                            logger.exception("Chapter preview failed for chapter %s.", record_id)
                            async with SessionLocal() as db:
                                await crud.audiobook.set_chapter_preview_status(db, record_id, "error", str(exc))
                        finally:
                            self._queued_preview_ids.discard(record_id)
                    elif job_type == "sentence":
                        try:
                            await self._process_sentence_audio(book_id, record_id)
                        except Exception:
                            logger.exception("Sentence audio failed for sentence %s.", record_id)
                            async with SessionLocal() as db:
                                await crud.audiobook.mark_sentence_error(db, record_id)
                        finally:
                            self._queued_sentence_ids.discard(record_id)
                    continue
                book_id = item
                try:
                    await self._process(book_id)
                except Exception as exc:
                    logger.exception("Unhandled exception in audiobook pipeline for book %s.", book_id)
                    async with SessionLocal() as db:
                        await crud.audiobook.set_book_pipeline_error(db, book_id, str(exc))
                finally:
                    self._queued_book_ids.discard(book_id)
                    if book_id in self._rerun_book_ids:
                        self._rerun_book_ids.discard(book_id)
                        await self.enqueue(book_id)
            finally:
                self._queue.task_done()

    async def _process_preview(self, book_id: int, chapter_id: int) -> None:
        async with SessionLocal() as db:
            await crud.audiobook.set_chapter_preview_status(db, chapter_id, "generating")
            await generate_audio_for_chapter_preview(book_id, chapter_id, db)
            await assemble_chapter_preview(book_id, chapter_id, db)
            await crud.audiobook.set_chapter_preview_status(db, chapter_id, "ready")

    async def _process_sentence_audio(self, book_id: int, sentence_id: int) -> None:
        async with SessionLocal() as db:
            await crud.audiobook.set_sentence_status(db, sentence_id, "audio_generating")
            await generate_audio_for_sentence(book_id, sentence_id, db)

    async def _restart_for_pending_content(self, book_id: int) -> bool:
        """Move a refresh received mid-build to the next durable boundary."""
        async with SessionLocal() as db:
            from ..models import Book

            book = await db.get(Book, book_id)
            if book is None or book.audiobook_pending_content_version is None:
                return False
            if (
                book.audiobook_source_content_version is not None
                and book.audiobook_pending_content_version <= book.audiobook_source_content_version
            ):
                return False
            book.audiobook_pipeline_status = "ingesting"
            await db.commit()
            return True

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
                    recovered = await crud.audiobook.reset_error_sentences_for_book(
                        db,
                        book_id,
                    )
                    if recovered:
                        logger.warning(
                            "Book %s: automatically retrying %d failed speech clips.",
                            book_id,
                            recovered,
                        )
                    ready_sentences = await crud.audiobook.get_sentences_ready_for_audio(
                        db,
                        book_id,
                        limit=100_000,
                    )
                    await self.enqueue_background_audio(
                        book_id,
                        [
                            sentence.id
                            for sentence in sorted(
                                ready_sentences,
                                key=lambda sentence: len(sentence.tagged_text or sentence.original_text),
                            )
                        ],
                    )
                    await diarize_sentences(
                        book_id,
                        db,
                        on_sentences_ready=lambda sentence_ids: self.enqueue_background_audio(
                            book_id,
                            sentence_ids,
                        ),
                    )
                elif phase == "audio_gen":
                    # A process restart can resume directly in this phase, after
                    # the in-memory TTS queue has been lost. Rebuild it from
                    # durable sentence state and preserve length bucketing.
                    ready_sentences = await crud.audiobook.get_sentences_ready_for_audio(
                        db,
                        book_id,
                        limit=100_000,
                    )
                    await self.enqueue_background_audio(
                        book_id,
                        [
                            sentence.id
                            for sentence in sorted(
                                ready_sentences,
                                key=lambda sentence: len(sentence.tagged_text or sentence.original_text),
                            )
                        ],
                    )
                    await self._wait_for_background_audio(book_id)
                    recovered = await crud.audiobook.reset_error_sentences_for_book(
                        db,
                        book_id,
                    )
                    if recovered:
                        logger.warning(
                            "Book %s: retrying %d failed speech clips before assembly.",
                            book_id,
                            recovered,
                        )
                    await generate_audio_for_book(book_id, db)
                elif phase == "assembling":
                    await assemble_book(book_id, db)

            # Stop only at durable boundaries. Mid-phase services also check
            # cooperative pause requests between batches/items.
            async with SessionLocal() as db:
                from ..models import Book

                book = await db.get(Book, book_id)
                if book and book.audiobook_pipeline_status == "paused":
                    logger.info("Book %s paused after phase '%s'.", book_id, phase)
                    return
                if await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
                    logger.info("Book %s acknowledged pause after phase '%s'.", book_id, phase)
                    return
                if await crud.audiobook.pause_book_pipeline_after_phase(db, book_id, phase):
                    logger.info("Book %s stopped for review after phase '%s'.", book_id, phase)
                    return

            if await self._restart_for_pending_content(book_id):
                logger.info("Book %s: restarting ingestion for pending refreshed content.", book_id)
                return await self._process(book_id)

        logger.info("Audiobook pipeline complete for book %s.", book_id)


_audiobook_queue = AudiobookQueue()


def get_audiobook_queue() -> AudiobookQueue:
    return _audiobook_queue
