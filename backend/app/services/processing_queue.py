"""Durable, user-visible orchestration for background processing jobs."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from typing import Awaitable, Callable, TypeVar, TypedDict
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import BACKUP_PATH, BACKUP_RETENTION_COUNT, LIBRARY_PATH
from ..database import DATABASE_URL, SessionLocal
from ..job_payloads import (
    JobPayload,
    validate_job_payload,
    VerifyBackupPayload,
    ImportWebBookPayload,
    RefreshAllPayload,
    ImportAudiobookPayload,
    RematchImportedAudiobookPayload,
    MetadataSyncPayload,
    AudiobookPipelinePayload,
)
from ..lifecycle import (
    AUDIOBOOK_PUBLICATION,
    IMPORTED_AUDIOBOOK,
    AudiobookPublicationStatus,
    ImportedAudiobookStatus,
    ProcessingJobStatus,
    transition_state,
)
from ..models import Book, ImportedAudiobook, ImportedAudiobookTrack, ProcessingJob
from ..logging_config import redact_text
from ..observability_context import correlation_context
from .audiobook_alignment import process_alignment
from .audiobook_import import (
    HumanAudiobookRebuildResult,
    process_import,
    rebuild_imported_audiobook,
    rematch_imported_audiobook,
    upgrade_imported_audiobook,
)
from .audiobook_queue import get_audiobook_queue
from .audiobook_tts import generate_audio_for_sentence
from .audiobook_assembly import assemble_chapter_preview
from .audiobook_tts import generate_audio_for_chapter_preview
from .backup_barrier import backup_barrier
from .backups import create_backup_archive, resolve_backup, verify_backup_archive
from .cover_processing import reextract_book_cover
from .metadata_jobs import process_metadata_sync_job
from .transcription_providers import transcription_provider_name
from .update_scheduler import run_web_novel_update
from .web_novel import run_book_refresh
from .web_novel import finish_web_novel_download


class WorkerHealth(TypedDict):
    status: str
    running: bool
    configured_workers: int
    active_workers: int
    failed_workers: int
    lanes: dict[str, int]


logger = logging.getLogger(__name__)

_Result = TypeVar("_Result")

RESOURCE_LANES = ("cpu", "maintenance", "llm", "tts", "transcription")
JOB_POLICIES: dict[str, tuple[str, int]] = {
    "clean_book": ("cpu", 3),
    "clean_all": ("cpu", 3),
    "refresh_book": ("maintenance", 3),
    "refresh_all": ("maintenance", 3),
    "import_web_book": ("maintenance", 3),
    "retry_cover": ("maintenance", 3),
    "metadata_sync": ("llm", 3),
    "audiobook_pipeline": ("llm", 3),
    "generate_sentence_audio": ("tts", 3),
    "generate_chapter_preview": ("tts", 3),
    "import_audiobook": ("cpu", 3),
    "upgrade_imported_audiobook": ("cpu", 3),
    "rebuild_imported_audiobook": ("cpu", 3),
    "rematch_imported_audiobook": ("cpu", 3),
    "align_imported_audiobook": ("transcription", 3),
    "create_backup": ("maintenance", 1),
    "verify_backup": ("maintenance", 1),
}


def _positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        logger.warning("Ignoring invalid %s; using %s.", name, default)
        return default


def _positive_float_env(name: str, default: float) -> float:
    try:
        return max(0.1, float(os.getenv(name, str(default))))
    except ValueError:
        logger.warning("Ignoring invalid %s; using %s.", name, default)
        return default


class ProcessingQueue:
    """A durable ledger backed by a small set of resource-aware workers."""

    def __init__(self) -> None:
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._wake = asyncio.Event()
        self._instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        self._lease_seconds = _positive_int_env("PROCESSING_LEASE_SECONDS", 60)
        self._heartbeat_seconds = min(
            _positive_int_env("PROCESSING_HEARTBEAT_SECONDS", 15),
            max(1, self._lease_seconds // 2),
        )
        self._poll_seconds = _positive_float_env("PROCESSING_POLL_SECONDS", 1)
        self._retry_backoff_seconds = _positive_int_env("PROCESSING_RETRY_BACKOFF_SECONDS", 5)

    async def start(self) -> None:
        if self._worker_tasks:
            if all(not task.done() for task in self._worker_tasks):
                return
            await self.stop()
        for lane in RESOURCE_LANES:
            count = _positive_int_env(f"PROCESSING_{lane.upper()}_CONCURRENCY", 1)
            for index in range(count):
                task = asyncio.create_task(
                    self._run(lane, index + 1),
                    name=f"processing-{lane}-worker-{index + 1}",
                )
                task.add_done_callback(self._worker_finished)
                self._worker_tasks.append(task)
        await get_audiobook_queue().start_background_audio()
        self._wake.set()

    @property
    def is_running(self) -> bool:
        return bool(self._worker_tasks) and all(not task.done() for task in self._worker_tasks)

    @staticmethod
    def _worker_finished(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "Background worker %s stopped unexpectedly: %s",
                task.get_name(),
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

    def health_snapshot(self) -> WorkerHealth:
        """Return a public, credential-free view of worker availability."""
        configured = {lane: _positive_int_env(f"PROCESSING_{lane.upper()}_CONCURRENCY", 1) for lane in RESOURCE_LANES}
        alive = [task for task in self._worker_tasks if not task.done()]
        dead = [task for task in self._worker_tasks if task.done()]
        return {
            "status": "available" if self.is_running and not dead else "unavailable",
            "running": self.is_running,
            "configured_workers": sum(configured.values()),
            "active_workers": len(alive),
            "failed_workers": len(dead),
            "lanes": configured,
        }

    async def stop(self) -> None:
        if not self._worker_tasks:
            return
        for task in self._worker_tasks:
            task.cancel()
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()
        await get_audiobook_queue().stop_background_audio()
        self._wake = asyncio.Event()

    async def enqueue(self, job_id: int) -> bool:
        """Wake database pollers; the job ID is never held as queue ownership."""
        del job_id
        self._wake.set()
        return True

    async def requeue_pending(self) -> int:
        async with SessionLocal() as db:
            canceled, exhausted = await crud.recover_abandoned_processing_jobs(db)
        self._wake.set()
        return canceled + exhausted

    async def _run(self, lane: str, worker_number: int) -> None:
        lease_owner = f"{self._instance_id}:{lane}:{worker_number}"
        while True:
            try:
                await backup_barrier.wait_until_writes_allowed()
                async with SessionLocal() as db:
                    await crud.recover_abandoned_processing_jobs(db)
                    job = await crud.claim_processing_job(
                        db,
                        resource_lane=lane,
                        lease_owner=lease_owner,
                        lease_seconds=self._lease_seconds,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Processing %s worker could not poll the durable queue.", lane)
                await asyncio.sleep(self._poll_seconds)
                continue
            if job is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._poll_seconds)
                except asyncio.TimeoutError:
                    pass
                continue

            if backup_barrier.backup_active and job.job_type != "create_backup":
                async with SessionLocal() as db:
                    await crud.defer_processing_job_for_backup(db, job.id, lease_owner=lease_owner)
                await backup_barrier.wait_until_writes_allowed()
                self._wake.set()
                continue

            with correlation_context(request_id=job.request_id, job_id=job.id):
                try:
                    detail = await self._execute_with_heartbeat(job, lease_owner)
                    async with SessionLocal() as db:
                        if await crud.is_processing_job_cancel_requested(db, job.id):
                            await crud.mark_processing_job_canceled(db, job.id)
                        else:
                            await crud.complete_processing_job(db, job.id, detail, lease_owner=lease_owner)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Processing job %s (%s) failed.", job.id, job.job_type)
                    async with SessionLocal() as db:
                        status = await crud.fail_processing_job(
                            db,
                            job.id,
                            redact_text(str(exc)),
                            lease_owner=lease_owner,
                            retry_backoff_seconds=self._retry_backoff_seconds,
                        )
                    if status == "queued":
                        self._wake.set()

    async def _execute_with_heartbeat(self, job: ProcessingJob, lease_owner: str) -> str:
        operation = asyncio.create_task(self._execute(job), name=f"processing-operation-{job.id}")
        heartbeat = asyncio.create_task(
            self._heartbeat(job.id, lease_owner),
            name=f"processing-heartbeat-{job.id}",
        )
        try:
            done, _pending = await asyncio.wait({operation, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if operation in done:
                return await operation
            reason = await heartbeat
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            if reason == "canceled":
                raise RuntimeError("Processing job was canceled.")
            raise RuntimeError("Processing job lease ownership was lost.")
        except asyncio.CancelledError:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, job_id: int, lease_owner: str) -> str:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            async with SessionLocal() as db:
                if await crud.is_processing_job_cancel_requested(db, job_id):
                    return "canceled"
                renewed = await crud.heartbeat_processing_job(
                    db,
                    job_id,
                    lease_owner=lease_owner,
                    lease_seconds=self._lease_seconds,
                )
            if not renewed:
                return "lost"

    async def _execute(self, job: ProcessingJob) -> str:
        validate_job_payload(job.job_type, job.payload)
        if job.job_type == "create_backup":
            async with backup_barrier.backup():
                async with SessionLocal() as db:
                    running_jobs = await db.scalar(
                        select(func.count(ProcessingJob.id)).where(
                            ProcessingJob.status == ProcessingJobStatus.RUNNING.value,
                            ProcessingJob.id != job.id,
                        )
                    )
                if running_jobs:
                    raise RuntimeError(
                        f"Backup paused because {running_jobs} other processing job(s) are still running. "
                        "Try again when Activity is idle."
                    )
                await self._update_progress(job.id, 0, 2, "Creating database and library snapshot")
                summary = await asyncio.to_thread(
                    create_backup_archive,
                    database_url=DATABASE_URL,
                    library_path=LIBRARY_PATH,
                    backup_path=BACKUP_PATH,
                    retention_count=BACKUP_RETENTION_COUNT,
                )
                await self._update_progress(job.id, 2, 2, f"Verified {summary['filename']}")
                return f"Backup created and verified: {summary['filename']}"
        if job.job_type == "verify_backup":
            filename = VerifyBackupPayload.model_validate(job.payload or {}).filename
            archive = resolve_backup(BACKUP_PATH, filename)
            await self._update_progress(job.id, 0, 1, f"Verifying {filename}")
            await asyncio.to_thread(verify_backup_archive, archive)
            await self._update_progress(job.id, 1, 1, f"Verified {filename}")
            return f"Backup verified: {filename}"
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
        if job.job_type == "import_web_book":
            if job.book_id is None:
                raise ValueError("Web import job has no book.")
            source_url = ImportWebBookPayload.model_validate(job.payload or {}).source_url
            if not source_url:
                raise ValueError("Web import job has no source URL.")
            await self._update_progress(job.id, 0, 1, "Downloading web book")
            await finish_web_novel_download(job.book_id, source_url)
            async with SessionLocal() as db:
                book = await db.get(Book, job.book_id)
                if book is None:
                    raise ValueError("Web import book no longer exists.")
                if book.download_status == "error":
                    raise RuntimeError(f"Web import failed: {book.title}")
                await crud.update_processing_job_progress(db, job.id, current=1, total=1, detail="Web book imported")
            return "Web book import completed"
        if job.job_type == "refresh_all":

            async def refresh_all() -> bool:
                return await run_web_novel_update(RefreshAllPayload.model_validate(job.payload or {}).trigger)

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
                settings = await crud.audiobook.get_audiobook_settings(db)
                matched_count = await db.scalar(
                    select(func.count(ImportedAudiobookTrack.id)).where(
                        ImportedAudiobookTrack.imported_audiobook_id == target_id,
                        ImportedAudiobookTrack.matched_chapter_id.is_not(None),
                    )
                )
            if (
                ImportAudiobookPayload.model_validate(job.payload or {}).auto_align
                and edition is not None
                and matched_count
                and transcription_provider_name(settings) != "none"
            ):
                child = await queue_processing_job(
                    job_type="align_imported_audiobook",
                    book_id=job.book_id,
                    target_type="imported_audiobook",
                    target_id=target_id,
                    target_content_version=edition.matched_content_version,
                    parent_job_id=job.id,
                    dedupe_key=f"align_imported_audiobook:imported_audiobook:{target_id}",
                    progress_detail="Queued automatically after audiobook import",
                )
                await self.enqueue(child.id)
                return "Human audiobook import completed; timestamp alignment queued"
            return "Human audiobook import completed"
        if job.job_type == "upgrade_imported_audiobook":
            target_id = _required_target(job)

            async def upgrade_audio() -> int:
                async with SessionLocal() as db:
                    return await upgrade_imported_audiobook(target_id, db)

            revision = await self._run_with_progress_mirror(
                job.id,
                upgrade_audio,
                lambda: self._imported_audio_progress(target_id),
            )
            return f"Human audiobook chapter assets upgraded to revision {revision}"
        if job.job_type == "rebuild_imported_audiobook":
            target_id = _required_target(job)

            async def rebuild_audio() -> HumanAudiobookRebuildResult:
                async with SessionLocal() as db:
                    return await rebuild_imported_audiobook(target_id, db)

            result = await self._run_with_progress_mirror(
                job.id,
                rebuild_audio,
                lambda: self._imported_audio_progress(target_id),
            )
            if result.realign:
                child = await queue_processing_job(
                    job_type="align_imported_audiobook",
                    book_id=job.book_id,
                    target_type="imported_audiobook",
                    target_id=target_id,
                    target_content_version=job.target_content_version,
                    parent_job_id=job.id,
                    dedupe_key=f"align_imported_audiobook:imported_audiobook:{target_id}",
                    progress_detail="Queued after human-audiobook rebuild",
                )
                await self.enqueue(child.id)
                return (
                    f"Human audiobook rebuilt ({result.matched_track_count} of {result.track_count} tracks); "
                    "timestamp alignment queued"
                )
            return f"Human audiobook rebuilt ({result.matched_track_count} of {result.track_count} tracks)"
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
            if RematchImportedAudiobookPayload.model_validate(job.payload or {}).realign:
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
            metadata_job_id = MetadataSyncPayload.model_validate(job.payload or {}).metadata_job_id or job.target_id
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
            book_id = _required_book(job)
            async with SessionLocal() as db:
                await crud.update_processing_job_progress(db, job.id, current=0, total=1, detail="Generating sentence audio")
                await crud.audiobook.set_sentence_status(db, sentence_id, "audio_generating")
                await generate_audio_for_sentence(book_id, sentence_id, db)
                await crud.update_processing_job_progress(db, job.id, current=1, total=1, detail="Sentence audio generated")
            return "Sentence audio generated"
        if job.job_type == "generate_chapter_preview":
            chapter_id = _required_target(job)
            book_id = _required_book(job)
            async with SessionLocal() as db:
                await crud.update_processing_job_progress(db, job.id, current=0, total=2, detail="Generating preview audio")
                await crud.audiobook.set_chapter_preview_status(db, chapter_id, "generating")
                await generate_audio_for_chapter_preview(book_id, chapter_id, db)
                await crud.update_processing_job_progress(db, job.id, current=1, total=2, detail="Assembling chapter preview")
                await assemble_chapter_preview(book_id, chapter_id, db)
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
        book_id = _required_book(job)
        mode = AudiobookPipelinePayload.model_validate(job.payload or {}).mode
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
            get_audiobook_queue().process_book(book_id),
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
                            await crud.audiobook.request_book_pipeline_pause(db, book_id)
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
        async def run_operation() -> _Result:
            return await operation()

        task = asyncio.create_task(run_operation(), name=f"processing-operation-{job_id}")
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


def _required_book(job: ProcessingJob) -> int:
    if job.book_id is None:
        raise ValueError("Processing job has no book.")
    return job.book_id


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
    payload: JobPayload | None = None,
    dedupe_key: str | None = None,
    progress_detail: str | None = "Queued",
) -> ProcessingJob:
    try:
        resource_lane, max_attempts = JOB_POLICIES[job_type]
    except KeyError as exc:
        raise ValueError(f"Unsupported processing job type: {job_type}") from exc
    payload = validate_job_payload(job_type, payload)
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
            resource_lane=resource_lane,
            max_attempts=max_attempts,
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
        transition_state(
            book,
            "audiobook_publication_state",
            AUDIOBOOK_PUBLICATION,
            AudiobookPublicationStatus.STALE,
            context=f"book {book.id}",
        )
        await db.commit()

    result = await db.execute(select(ImportedAudiobook).where(ImportedAudiobook.book_id == book.id))
    for edition in result.scalars().all():
        if edition.matched_content_version == content_version and edition.status != "stale":
            continue
        realign = edition.alignment_method in {"transcribed", "hybrid"}
        transition_state(
            edition,
            "status",
            IMPORTED_AUDIOBOOK,
            ImportedAudiobookStatus.STALE,
            context=f"imported audiobook {edition.id}",
        )
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
                payload=RematchImportedAudiobookPayload(realign=realign),
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
                payload=AudiobookPipelinePayload(mode="reconcile"),
                dedupe_key=f"audiobook_pipeline:book:{book.id}:v{content_version}",
                progress_detail=f"Queued for cleaned content v{content_version}",
            )
        )
    return queued
