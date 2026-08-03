"""Durable, user-visible orchestration for background processing jobs."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..database import SessionLocal
from ..models import Book, ImportedAudiobook, ProcessingJob
from .audiobook_alignment import process_alignment
from .audiobook_import import process_import, rematch_imported_audiobook
from .audiobook_queue import get_audiobook_queue
from .audiobook_tts import generate_audio_for_sentence
from .audiobook_assembly import assemble_chapter_preview
from .audiobook_tts import generate_audio_for_chapter_preview
from .cover_processing import reextract_book_cover
from .metadata_jobs import process_metadata_sync_job
from .update_scheduler import run_web_novel_update
from .web_novel import run_book_refresh

logger = logging.getLogger(__name__)

_Result = TypeVar("_Result")


class ProcessingQueue:
    """A durable ledger backed by a small set of resource-aware workers."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[int | None] = asyncio.Queue()
        self._queued_ids: set[int] = set()
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._lanes = {
            "audiobook": asyncio.Semaphore(1),
            "maintenance": asyncio.Semaphore(1),
        }

    async def start(self) -> None:
        if self._worker_tasks:
            return
        worker_count = max(1, int(os.getenv("PROCESSING_WORKERS", "3")))
        self._worker_tasks = [
            asyncio.create_task(self._run(), name=f"processing-worker-{index + 1}") for index in range(worker_count)
        ]

    @property
    def is_running(self) -> bool:
        return bool(self._worker_tasks)

    async def stop(self) -> None:
        if not self._worker_tasks:
            return
        for task in self._worker_tasks:
            task.cancel()
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()
        self._queued_ids.clear()
        self._queue = asyncio.Queue()

    async def enqueue(self, job_id: int) -> bool:
        if job_id in self._queued_ids:
            return False
        self._queued_ids.add(job_id)
        await self._queue.put(job_id)
        return True

    async def requeue_pending(self) -> int:
        async with SessionLocal() as db:
            jobs = await crud.get_pending_processing_jobs(db)
        return sum([await self.enqueue(job.id) for job in jobs])

    @asynccontextmanager
    async def _lane(self, job_type: str) -> AsyncIterator[None]:
        if job_type in {
            "audiobook_pipeline",
            "import_audiobook",
            "rematch_imported_audiobook",
            "align_imported_audiobook",
            "generate_sentence_audio",
            "generate_chapter_preview",
        }:
            semaphore = self._lanes["audiobook"]
        elif job_type in {"clean_all", "refresh_all"}:
            semaphore = self._lanes["maintenance"]
        else:
            semaphore = None
        if semaphore is None:
            yield
        else:
            async with semaphore:
                yield

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if job_id is None:
                    return
                async with SessionLocal() as db:
                    job = await crud.mark_processing_job_running(db, job_id)
                if job is None:
                    continue
                try:
                    async with self._lane(job.job_type):
                        async with SessionLocal() as db:
                            if await crud.is_processing_job_cancel_requested(db, job.id):
                                await crud.mark_processing_job_canceled(db, job.id)
                                continue
                        detail = await self._execute(job)
                    async with SessionLocal() as db:
                        if await crud.is_processing_job_cancel_requested(db, job.id):
                            await crud.mark_processing_job_canceled(db, job.id)
                        else:
                            await crud.complete_processing_job(db, job.id, detail)
                except Exception as exc:
                    logger.exception("Processing job %s (%s) failed.", job.id, job.job_type)
                    async with SessionLocal() as db:
                        await crud.fail_processing_job(db, job.id, str(exc))
            finally:
                if job_id is not None:
                    self._queued_ids.discard(job_id)
                self._queue.task_done()

    async def _execute(self, job: ProcessingJob) -> str:
        payload = job.payload or {}
        if job.job_type == "clean_book":
            return await self._clean_book(job.id, job.book_id)
        if job.job_type == "clean_all":
            return await self._clean_all(job.id)
        if job.job_type == "refresh_book":
            if job.book_id is None:
                raise ValueError("Refresh job has no book.")
            await self._update_progress(job.id, 0, 1, "Downloading and rebuilding the web book")
            await run_book_refresh(job.book_id)
            async with SessionLocal() as db:
                book = await db.get(Book, job.book_id)
                if book is not None and book.refresh_status == "error":
                    raise RuntimeError("Book refresh failed; check the application logs.")
                await crud.update_processing_job_progress(db, job.id, current=1, total=1, detail="Web book refreshed")
            return "Book refresh completed"
        if job.job_type == "refresh_all":

            async def refresh_all() -> bool:
                return await run_web_novel_update(payload.get("trigger", "manual"))

            await self._run_with_progress_mirror(
                job.id,
                refresh_all,
                self._library_refresh_progress,
            )
            async with SessionLocal() as db:
                refresh_task = await crud.get_latest_update_task(db)
                if refresh_task is not None and refresh_task.status == "failed":
                    raise RuntimeError("One or more web books failed to refresh; check the job history.")
            return "Library refresh completed"
        if job.job_type == "audiobook_pipeline":
            return await self._run_audiobook_pipeline(job)
        if job.job_type == "import_audiobook":
            target_id = _required_target(job)

            async def import_audio() -> None:
                async with SessionLocal() as db:
                    await process_import(target_id, db)

            await self._run_with_progress_mirror(
                job.id,
                import_audio,
                lambda: self._imported_audio_progress(target_id),
            )
            async with SessionLocal() as db:
                edition = await db.get(ImportedAudiobook, target_id)
                if edition is not None and edition.status == "error":
                    raise RuntimeError(edition.error or "Human audiobook import failed.")
            return "Human audiobook import completed"
        if job.job_type == "rematch_imported_audiobook":
            target_id = _required_target(job)

            async def rematch_audio() -> int:
                async with SessionLocal() as db:
                    return await rematch_imported_audiobook(target_id, db)

            matched = await self._run_with_progress_mirror(
                job.id,
                rematch_audio,
                lambda: self._imported_audio_progress(target_id),
            )
            if payload.get("realign"):
                child = await queue_processing_job(
                    job_type="align_imported_audiobook",
                    book_id=job.book_id,
                    target_type="imported_audiobook",
                    target_id=job.target_id,
                    parent_job_id=job.id,
                    dedupe_key=f"align_imported_audiobook:imported_audiobook:{job.target_id}",
                    progress_detail="Queued after human-audio rematch",
                )
                await self.enqueue(child.id)
            return f"Human audiobook rematched ({matched} tracks)"
        if job.job_type == "align_imported_audiobook":
            target_id = _required_target(job)

            async def align_audio() -> None:
                async with SessionLocal() as db:
                    await process_alignment(target_id, db)

            await self._run_with_progress_mirror(
                job.id,
                align_audio,
                lambda: self._imported_audio_progress(target_id),
            )
            async with SessionLocal() as db:
                edition = await db.get(ImportedAudiobook, target_id)
                if edition is not None and edition.alignment_error:
                    raise RuntimeError(edition.alignment_error)
            return "Human audiobook timing alignment completed"
        if job.job_type == "metadata_sync":
            metadata_job_id = payload.get("metadata_job_id") or job.target_id
            if metadata_job_id is None:
                raise ValueError("Metadata processing job has no metadata job.")
            metadata_job_id = int(metadata_job_id)

            async def sync_metadata() -> None:
                async with SessionLocal() as db:
                    await process_metadata_sync_job(db, metadata_job_id)

            await self._run_with_progress_mirror(
                job.id,
                sync_metadata,
                lambda: self._metadata_progress(metadata_job_id),
            )
            async with SessionLocal() as db:
                metadata_job = await crud.get_metadata_sync_job(db, int(metadata_job_id))
                if metadata_job is not None and metadata_job.status == "failed":
                    raise RuntimeError(metadata_job.error or "Metadata sync failed.")
            return "Metadata sync completed"
        if job.job_type == "generate_sentence_audio":
            sentence_id = _required_target(job)
            async with SessionLocal() as db:
                await crud.update_processing_job_progress(db, job.id, current=0, total=1, detail="Generating sentence audio")
                await crud.audiobook.set_sentence_status(db, sentence_id, "audio_generating")
                await generate_audio_for_sentence(job.book_id, sentence_id, db)
                await crud.update_processing_job_progress(db, job.id, current=1, total=1, detail="Sentence audio generated")
            return "Sentence audio generated"
        if job.job_type == "generate_chapter_preview":
            chapter_id = _required_target(job)
            async with SessionLocal() as db:
                await crud.update_processing_job_progress(db, job.id, current=0, total=2, detail="Generating preview audio")
                await crud.audiobook.set_chapter_preview_status(db, chapter_id, "generating")
                await generate_audio_for_chapter_preview(job.book_id, chapter_id, db)
                await crud.update_processing_job_progress(db, job.id, current=1, total=2, detail="Assembling chapter preview")
                await assemble_chapter_preview(job.book_id, chapter_id, db)
                await crud.audiobook.set_chapter_preview_status(db, chapter_id, "ready")
                await crud.update_processing_job_progress(db, job.id, current=2, total=2, detail="Chapter preview ready")
            return "Chapter preview generated"
        if job.job_type == "retry_cover":
            async with SessionLocal() as db:
                book = await db.get(Book, job.book_id)
                if book is None:
                    raise ValueError("Book no longer exists.")
                await crud.update_processing_job_progress(
                    db, job.id, current=0, total=1, detail="Extracting or finding a book cover"
                )
                await reextract_book_cover(book, db)
                await crud.update_processing_job_progress(db, job.id, current=1, total=1, detail="Book cover updated")
            return "Book cover re-extracted"
        raise ValueError(f"Unsupported processing job type: {job.job_type}")

    async def _clean_book(self, job_id: int, book_id: int | None) -> str:
        if book_id is None:
            raise ValueError("Cleaning job has no book.")
        from .. import epub_editor

        async with SessionLocal() as db:
            book = await db.get(Book, book_id)
            if book is None:
                raise ValueError("Book no longer exists.")
            await crud.update_processing_job_progress(db, job_id, current=0, total=1, detail="Applying cleaning rules")
            changed = await epub_editor.apply_book_cleaning(book, db, force=True)
            if changed:
                await queue_audio_reconciliation(book, db, parent_job_id=job_id)
            await crud.update_processing_job_progress(
                db,
                job_id,
                current=1,
                total=1,
                detail="Cleaning changed the book" if changed else "Cleaning made no content changes",
            )
        return "Cleaned book and queued derived audio" if changed else "Cleaning made no content changes"

    async def _clean_all(self, job_id: int) -> str:
        from .. import epub_editor

        async with SessionLocal() as db:
            books = await crud.get_books(db, limit=100000)
            configs = await crud.get_cleaning_configs(db)
            total = len(books)
            await crud.update_processing_job_progress(db, job_id, current=0, total=total, detail="Starting library cleaning")
            updated = 0
            for index, book in enumerate(books, start=1):
                if await crud.is_processing_job_cancel_requested(db, job_id):
                    return f"Stopped after {index - 1} of {total} books"
                changed = await epub_editor.apply_book_cleaning(book, db, force=True, cleaning_configs=configs)
                if changed:
                    updated += 1
                    await queue_audio_reconciliation(book, db, parent_job_id=job_id)
                await crud.update_processing_job_progress(
                    db,
                    job_id,
                    current=index,
                    total=total,
                    detail=f"Cleaned {index} of {total} books; {updated} changed",
                )
        return f"Cleaned {total} books; {updated} changed"

    async def _run_audiobook_pipeline(self, job: ProcessingJob) -> str:
        mode = (job.payload or {}).get("mode", "resume")
        async with SessionLocal() as db:
            book = await db.get(Book, job.book_id)
            if book is None:
                raise ValueError("Book no longer exists.")
            if not book.audiobook_enabled:
                raise ValueError("AI audiobook generation is not enabled for this book.")

            if mode == "rebuild":
                chapters = await crud.audiobook.get_chapters_for_book(db, book.id)
                if chapters:
                    await crud.audiobook.reset_roster_and_diarization_for_book(db, book.id)
                await crud.audiobook.set_book_audiobook_summary(db, book.id, None)
                next_phase = "roster_gen" if chapters else "ingesting"
                stop_after = None
                batch_limit = None
            elif mode == "audio":
                chapters = await crud.audiobook.get_chapters_for_book(db, book.id)
                characters = await crud.audiobook.get_characters_for_book(db, book.id)
                review = await crud.audiobook.count_sentence_review_flags(db, book.id)
                if not chapters or not characters:
                    raise ValueError("Run AI speaker analysis before regenerating TTS audio.")
                if review.get("unassigned", 0):
                    raise ValueError("Assign every sentence before regenerating TTS audio.")
                await crud.audiobook.reset_audio_generation_for_book(db, book.id)
                next_phase = "audio_gen"
                stop_after = None
                batch_limit = None
            elif mode == "roster":
                chapters = await crud.audiobook.get_chapters_for_book(db, book.id)
                if not chapters:
                    raise ValueError("Run ingestion before regenerating the roster.")
                await crud.audiobook.reset_roster_and_diarization_for_book(db, book.id)
                await crud.audiobook.set_book_audiobook_summary(db, book.id, None)
                next_phase = "roster_gen"
                stop_after = "roster_gen"
                batch_limit = None
            elif mode == "reconcile":
                next_phase = "ingesting"
                stop_after = None
                batch_limit = None
            elif mode == "resume" and book.audiobook_pipeline_status in {
                "ingesting",
                "roster_gen",
                "diarizing",
                "audio_gen",
                "assembling",
            }:
                next_phase = book.audiobook_pipeline_status
                stop_after = book.audiobook_stop_after_phase
                batch_limit = book.audiobook_batch_limit
            else:
                if book.audiobook_pipeline_status == "error" and await crud.audiobook.has_sentence_status(
                    db, book.id, "error"
                ):
                    await crud.audiobook.reset_error_sentences_for_book(db, book.id)
                next_phase = await crud.audiobook.infer_audiobook_resume_status(db, book.id)
                if next_phase == "complete":
                    return "Audiobook was already complete"
                stop_after = next_phase if mode == "step" else None
                batch_limit = 1 if mode == "batch" else None

            await crud.audiobook.configure_book_pipeline_run(
                db,
                book.id,
                status=next_phase,
                stop_after_phase=stop_after,
                batch_limit=batch_limit,
            )
        pipeline_task = asyncio.create_task(
            get_audiobook_queue().process_book(job.book_id),
            name=f"audiobook-processing-job-{job.id}",
        )
        try:
            while not pipeline_task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(pipeline_task), timeout=1)
                except asyncio.TimeoutError:
                    async with SessionLocal() as db:
                        book = await db.get(Book, job.book_id)
                        if book is not None:
                            await crud.update_processing_job_progress(
                                db,
                                job.id,
                                current=book.audiobook_progress_current or 0,
                                total=book.audiobook_progress_total or 0,
                                detail=book.audiobook_progress_detail or f"Audiobook phase: {book.audiobook_pipeline_status}",
                            )
                        if await crud.is_processing_job_cancel_requested(db, job.id):
                            await crud.audiobook.request_book_pipeline_pause(db, job.book_id)
            await pipeline_task
        except asyncio.CancelledError:
            pipeline_task.cancel()
            await asyncio.gather(pipeline_task, return_exceptions=True)
            raise
        async with SessionLocal() as db:
            book = await db.get(Book, job.book_id)
            if book is not None and book.audiobook_pipeline_status == "error":
                raise RuntimeError(book.audiobook_last_error or "Audiobook processing failed.")
        return "Audiobook processing reached its requested checkpoint"

    async def _run_with_progress_mirror(
        self,
        job_id: int,
        operation: Callable[[], Awaitable[_Result]],
        snapshot: Callable[[], Awaitable[tuple[int, int, str | None]]],
    ) -> _Result:
        task = asyncio.create_task(operation(), name=f"processing-operation-{job_id}")
        try:
            while not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
                except asyncio.TimeoutError:
                    current, total, detail = await snapshot()
                    await self._update_progress(job_id, current, total, detail)
            result = await task
            current, total, detail = await snapshot()
            await self._update_progress(job_id, current, total, detail)
            return result
        except asyncio.CancelledError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def _update_progress(
        self,
        job_id: int,
        current: int,
        total: int,
        detail: str | None,
    ) -> None:
        async with SessionLocal() as db:
            await crud.update_processing_job_progress(
                db,
                job_id,
                current=current,
                total=total,
                detail=detail,
            )

    async def _imported_audio_progress(self, edition_id: int) -> tuple[int, int, str | None]:
        async with SessionLocal() as db:
            edition = await db.get(ImportedAudiobook, edition_id)
            if edition is None:
                return 0, 0, "Audiobook edition no longer exists"
            return (
                edition.progress_current or 0,
                edition.progress_total or 0,
                edition.progress_detail,
            )

    async def _metadata_progress(self, metadata_job_id: int) -> tuple[int, int, str | None]:
        async with SessionLocal() as db:
            metadata_job = await crud.get_metadata_sync_job(db, metadata_job_id)
            if metadata_job is None:
                return 0, 0, "Metadata job no longer exists"
            return (
                metadata_job.processed_books or 0,
                metadata_job.total_books or 0,
                (
                    f"Checked {metadata_job.processed_books or 0} of {metadata_job.total_books or 0} books"
                    f" · {metadata_job.matched_books or 0} matched"
                    f" · {metadata_job.proposed_books or 0} proposed"
                ),
            )

    async def _library_refresh_progress(self) -> tuple[int, int, str | None]:
        async with SessionLocal() as db:
            task = await crud.get_latest_update_task(db)
            if task is None:
                return 0, 0, "Preparing the web library refresh"
            return (
                task.completed_books or 0,
                task.total_books or 0,
                f"Refreshed {task.completed_books or 0} of {task.total_books or 0} web books",
            )


def _required_target(job: ProcessingJob) -> int:
    if job.target_id is None:
        raise ValueError(f"{job.job_type} job has no target.")
    return job.target_id


_processing_queue = ProcessingQueue()


def get_processing_queue() -> ProcessingQueue:
    return _processing_queue


async def queue_processing_job(
    *,
    job_type: str,
    db: AsyncSession | None = None,
    book_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    target_content_version: int | None = None,
    parent_job_id: int | None = None,
    payload: dict | None = None,
    dedupe_key: str | None = None,
    progress_detail: str | None = "Queued",
) -> ProcessingJob:
    owns_session = db is None
    session = db or SessionLocal()
    try:
        job, created = await crud.create_processing_job(
            session,
            job_type=job_type,
            book_id=book_id,
            target_type=target_type,
            target_id=target_id,
            target_content_version=target_content_version,
            parent_job_id=parent_job_id,
            payload=payload,
            dedupe_key=dedupe_key,
            progress_detail=progress_detail,
        )
        if created and get_processing_queue().is_running:
            await get_processing_queue().enqueue(job.id)
        return job
    finally:
        if owns_session:
            await session.close()


async def queue_audio_reconciliation(book: Book, db: AsyncSession, parent_job_id: int | None = None) -> list[ProcessingJob]:
    """Invalidate and queue every audio derivative of the current cleaned text."""
    await db.refresh(book)
    content_version = book.content_version or 1
    queued: list[ProcessingJob] = []
    if book.audiobook_enabled:
        book.audiobook_publication_state = "stale"
        await db.commit()

    result = await db.execute(select(ImportedAudiobook).where(ImportedAudiobook.book_id == book.id))
    for edition in result.scalars().all():
        if edition.matched_content_version == content_version and edition.status != "stale":
            continue
        realign = edition.alignment_method in {"transcribed", "hybrid"}
        edition.status = "stale"
        edition.progress_detail = "Book content changed; rematch queued"
        edition.alignment_error = None
        await db.commit()
        queued.append(
            await queue_processing_job(
                db=db,
                job_type="rematch_imported_audiobook",
                book_id=book.id,
                target_type="imported_audiobook",
                target_id=edition.id,
                target_content_version=content_version,
                parent_job_id=parent_job_id,
                payload={"realign": realign},
                dedupe_key=f"rematch_imported_audiobook:imported_audiobook:{edition.id}:v{content_version}",
                progress_detail=f"Queued to rematch against cleaned content v{content_version}",
            )
        )
    if book.audiobook_enabled:
        queued.append(
            await queue_processing_job(
                db=db,
                job_type="audiobook_pipeline",
                book_id=book.id,
                target_type="book",
                target_id=book.id,
                target_content_version=content_version,
                parent_job_id=parent_job_id,
                payload={"mode": "reconcile"},
                dedupe_key=f"audiobook_pipeline:book:{book.id}:v{content_version}",
                progress_detail=f"Queued for cleaned content v{content_version}",
            )
        )
    return queued
