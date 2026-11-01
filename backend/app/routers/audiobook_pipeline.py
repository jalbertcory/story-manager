"""AI narration pipeline control, status and chapter endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import api_schemas as contracts
from .. import crud
from ..audiobook_schemas import (
    AudiobookStatusResponse,
    BookTTSProviderUpdate,
    ChapterResponse,
)
from ..database import get_db
from ..job_payloads import (
    AudiobookPipelinePayload,
)
from ..models import (
    AudiobookChapter,
)
from ..services import audiobook_views
from ..services.audiobook_views import AudiobookViewNotFoundError
from ..services.endpoint_pool import (
    configured_providers,
    reset_cooldowns,
    settings_for_provider,
)
from ..services.library_paths import book_audiobook_dir, resolve_library_file
from ..services.processing_queue import queue_processing_job
from ..services.tts_providers import (
    tts_provider_name,
)
from .audiobook_common import get_audiobook_book_or_404, get_book_or_404

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pipeline control
# ---------------------------------------------------------------------------


def _reset_phase_endpoint_cooldowns(phase: str) -> None:
    """Let an explicit retry probe endpoints immediately after recovery."""
    capability = {"roster_gen": "llm", "diarizing": "llm", "audio_gen": "tts"}.get(phase)
    if capability:
        reset_cooldowns(capability)


@router.post("/api/books/{book_id}/audiobook/start", response_model=contracts.PipelineQueued)
async def start_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> contracts.PipelineQueued:
    book = await get_audiobook_book_or_404(book_id, db)
    status = book.audiobook_pipeline_status

    if status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        # Already running; idempotent
        return {"status": status, "queued": False}

    if status == "error" and await crud.audiobook.has_sentence_status(db, book_id, "error"):
        await crud.audiobook.reset_error_sentences_for_book(db, book_id)

    resume_status = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    if resume_status == "complete":
        await crud.audiobook.configure_book_pipeline_run(db, book_id, status="complete", stop_after_phase=None)
        return {"status": "complete", "queued": False}

    await crud.audiobook.configure_book_pipeline_run(db, book_id, status=resume_status, stop_after_phase=None)
    _reset_phase_endpoint_cooldowns(resume_status)

    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload=AudiobookPipelinePayload(mode="resume"),
        dedupe_key=f"audiobook_pipeline:book:{book_id}:manual",
        progress_detail="Queued to run audiobook to completion",
    )
    current_status = (await get_book_or_404(book_id, db)).audiobook_pipeline_status
    return {"status": current_status, "queued": True}


@router.post("/api/books/{book_id}/audiobook/step", response_model=contracts.PipelineQueued)
async def step_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> contracts.PipelineQueued:
    """Run exactly the next recoverable phase, then stop for review."""
    book = await get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        return {"status": book.audiobook_pipeline_status, "queued": False}

    if book.audiobook_pipeline_status == "error" and await crud.audiobook.has_sentence_status(db, book_id, "error"):
        await crud.audiobook.reset_error_sentences_for_book(db, book_id)

    next_phase = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    if next_phase == "complete":
        await crud.audiobook.configure_book_pipeline_run(db, book_id, status="complete", stop_after_phase=None)
        return {"status": "complete", "queued": False}

    await crud.audiobook.configure_book_pipeline_run(db, book_id, status=next_phase, stop_after_phase=next_phase)
    _reset_phase_endpoint_cooldowns(next_phase)
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload=AudiobookPipelinePayload(mode="resume"),
        dedupe_key=f"audiobook_pipeline:book:{book_id}:manual",
        progress_detail=f"Queued next audiobook stage: {next_phase}",
    )
    return {"status": next_phase, "queued": True, "stop_after_phase": next_phase}


@router.post("/api/books/{book_id}/audiobook/run-batch", response_model=contracts.PipelineQueued)
async def run_pipeline_batch(book_id: int, db: AsyncSession = Depends(get_db)) -> contracts.PipelineQueued:
    """Run one durable LLM/TTS/assembly work unit, then pause for review."""
    book = await get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        return {"status": book.audiobook_pipeline_status, "queued": False}
    next_phase = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    if next_phase not in ("diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail=f"{next_phase} is atomic; use Run Next Stage instead")
    await crud.audiobook.configure_book_pipeline_run(
        db,
        book_id,
        status=next_phase,
        stop_after_phase=None,
        batch_limit=1,
    )
    _reset_phase_endpoint_cooldowns(next_phase)
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload=AudiobookPipelinePayload(mode="resume"),
        dedupe_key=f"audiobook_pipeline:book:{book_id}:manual",
        progress_detail=f"Queued one audiobook batch: {next_phase}",
    )
    return {"status": next_phase, "queued": True, "batch_limit": 1}


@router.post("/api/books/{book_id}/audiobook/pause", response_model=contracts.PipelinePaused)
async def pause_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> contracts.PipelinePaused:
    book = await get_audiobook_book_or_404(book_id, db)
    active = book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling")
    await crud.audiobook.request_book_pipeline_pause(db, book_id)
    if active:
        return {"status": book.audiobook_pipeline_status, "pause_requested": True}
    await crud.audiobook.pause_book_pipeline_if_requested(db, book_id)
    return {"status": "paused", "pause_requested": False}


@router.post("/api/books/{book_id}/audiobook/rebuild", response_model=contracts.PipelineQueued)
async def rebuild_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> contracts.PipelineQueued:
    book = await get_audiobook_book_or_404(book_id, db)
    running_jobs = await crud.get_processing_jobs(
        db, statuses=["running"], job_type="audiobook_pipeline", book_id=book_id, limit=1
    )
    if (
        book.audiobook_pipeline_status
        in (
            "ingesting",
            "roster_gen",
            "diarizing",
            "audio_gen",
            "assembling",
        )
        or running_jobs
    ):
        raise HTTPException(status_code=409, detail="Pause the active pipeline before rebuilding it")
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload=AudiobookPipelinePayload(mode="rebuild"),
        dedupe_key=f"audiobook_pipeline:book:{book_id}:rebuild",
        progress_detail="Queued AI audiobook rebuild; human editions preserved",
    )
    return {"status": book.audiobook_pipeline_status, "queued": True}


@router.post("/api/books/{book_id}/audiobook/audio/rebuild", response_model=contracts.PipelineQueued)
async def rebuild_audio_only(book_id: int, db: AsyncSession = Depends(get_db)) -> contracts.PipelineQueued:
    """Regenerate AI TTS and assembly without changing speaker analysis."""
    book = await get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail="Pause the active pipeline before regenerating AI audio")
    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    characters = await crud.audiobook.get_characters_for_book(db, book_id)
    review = await crud.audiobook.count_sentence_review_flags(db, book_id)
    if not chapters or not characters:
        raise HTTPException(status_code=409, detail="Run AI speaker analysis before regenerating TTS audio")
    if review.get("unassigned", 0):
        raise HTTPException(status_code=409, detail="Assign every sentence before regenerating TTS audio")

    await crud.audiobook.reset_audio_generation_for_book(db, book_id)
    await crud.audiobook.configure_book_pipeline_run(
        db,
        book_id,
        status="audio_gen",
        stop_after_phase=None,
    )
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload=AudiobookPipelinePayload(mode="audio"),
        dedupe_key=f"audiobook_pipeline:book:{book_id}:audio-rebuild",
        progress_detail="Queued AI TTS regeneration; speakers and human editions preserved",
    )
    return {"status": "audio_gen", "queued": True}


@router.post("/api/books/{book_id}/audiobook/roster/rebuild", response_model=contracts.PipelineQueued)
async def rebuild_character_roster(book_id: int, db: AsyncSession = Depends(get_db)) -> contracts.PipelineQueued:
    """Re-run roster and diarization analysis without parsing the EPUB again."""
    book = await get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail="Pause the active pipeline before regenerating the roster")
    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    if not chapters:
        raise HTTPException(status_code=409, detail="Run ingestion before regenerating the roster")
    await crud.audiobook.reset_roster_and_diarization_for_book(db, book_id)
    await crud.audiobook.set_book_audiobook_summary(db, book_id, None)
    await crud.audiobook.configure_book_pipeline_run(
        db,
        book_id,
        status="roster_gen",
        stop_after_phase="roster_gen",
    )
    await queue_processing_job(
        db=db,
        job_type="audiobook_pipeline",
        book_id=book_id,
        target_type="book",
        target_id=book_id,
        target_content_version=book.content_version,
        payload=AudiobookPipelinePayload(mode="roster"),
        dedupe_key=f"audiobook_pipeline:book:{book_id}:roster",
        progress_detail="Queued character-roster regeneration",
    )
    return {
        "status": "roster_gen",
        "queued": True,
        "stop_after_phase": "roster_gen",
    }


@router.get("/api/books/{book_id}/audiobook/status", response_model=AudiobookStatusResponse)
async def get_pipeline_status(book_id: int, db: AsyncSession = Depends(get_db)) -> AudiobookStatusResponse:
    book = await get_audiobook_book_or_404(book_id, db)
    counts = await crud.audiobook.count_sentences_by_status(db, book_id)
    review_counts = await crud.audiobook.count_sentence_review_flags(db, book_id)
    next_phase = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    settings = await crud.audiobook.get_audiobook_settings(db)
    await db.refresh(book)
    available_tts_providers = configured_providers(settings, "tts")
    locked_tts_provider = (
        book.audiobook_tts_provider.strip().lower()
        if book.audiobook_tts_provider and book.audiobook_tts_provider.strip()
        else None
    )
    selected_tts_provider = locked_tts_provider or tts_provider_name(settings)
    selected_tts_model = settings.tts_model if settings else None
    if settings is not None and locked_tts_provider in available_tts_providers:
        selected_tts_model = settings_for_provider(settings, "tts", locked_tts_provider).tts_model
    total = book.audiobook_progress_total or 0
    percent = round((book.audiobook_progress_current or 0) * 100 / total, 1) if total else None
    return AudiobookStatusResponse(
        pipeline_status=book.audiobook_pipeline_status,
        next_phase=next_phase,
        pause_requested=book.audiobook_pause_requested,
        stop_after_phase=book.audiobook_stop_after_phase,
        last_error=book.audiobook_last_error,
        sentence_counts=counts,
        review_counts=review_counts,
        summary=book.audiobook_summary,
        progress_current=book.audiobook_progress_current or 0,
        progress_total=total,
        progress_percent=percent,
        progress_detail=book.audiobook_progress_detail,
        pipeline_started_at=book.audiobook_pipeline_started_at,
        pipeline_updated_at=book.audiobook_pipeline_updated_at,
        batch_limit=book.audiobook_batch_limit,
        llm_requests=book.audiobook_llm_requests or 0,
        llm_provider=(settings.llm_provider or "stub") if settings else "stub",
        llm_model=settings.llm_model if settings else None,
        tts_provider=selected_tts_provider,
        tts_model=selected_tts_model,
        tts_provider_locked=locked_tts_provider is not None,
        available_tts_providers=available_tts_providers,
    )


@router.put("/api/books/{book_id}/audiobook/tts-provider", response_model=contracts.TTSProviderChanged)
async def update_book_tts_provider(
    book_id: int,
    body: BookTTSProviderUpdate,
    db: AsyncSession = Depends(get_db),
) -> contracts.TTSProviderChanged:
    book = await get_audiobook_book_or_404(book_id, db)
    settings = await crud.audiobook.get_audiobook_settings(db)
    provider = body.provider.strip().lower()
    available = configured_providers(settings, "tts")
    if provider not in available:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Configure a {provider} TTS endpoint in Audio & AI Configuration first. "
                f"Available providers: {', '.join(available) or 'none'}."
            ),
        )
    try:
        affected_books = await crud.audiobook.replace_tts_provider_lock(db, book_id, provider)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "provider": provider,
        "scope": "series" if book.series else "book",
        "affected_book_ids": [affected.id for affected in affected_books],
    }


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------


@router.get("/api/books/{book_id}/audiobook/chapters", response_model=list[ChapterResponse])
async def list_chapters(book_id: int, db: AsyncSession = Depends(get_db)) -> list[ChapterResponse]:
    try:
        return await audiobook_views.chapter_responses(book_id, db)
    except AudiobookViewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc


@router.post(
    "/api/books/{book_id}/audiobook/chapters/{chapter_id}/preview-audio", response_model=contracts.ChapterPreviewQueued
)
async def generate_chapter_preview(
    book_id: int,
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
) -> contracts.ChapterPreviewQueued:
    book = await get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail="Pause the full-book pipeline before generating a preview")
    chapter = await db.get(AudiobookChapter, chapter_id)
    if chapter is None or chapter.book_id != book_id:
        raise HTTPException(status_code=404, detail="Audiobook chapter not found")
    sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter_id)
    pending = sum(1 for sentence in sentences if sentence.status == "pending_diarization")
    if not sentences or pending:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Finish speaker analysis for this chapter first ({pending} sentences remain)"
                if pending
                else "Chapter has no narratable sentences"
            ),
        )
    if chapter.preview_status in ("queued", "generating"):
        return {"status": chapter.preview_status, "queued": False}
    await crud.audiobook.set_chapter_preview_status(db, chapter_id, "queued")
    await queue_processing_job(
        db=db,
        job_type="generate_chapter_preview",
        book_id=book_id,
        target_type="audiobook_chapter",
        target_id=chapter_id,
        target_content_version=book.content_version,
        dedupe_key=f"generate_chapter_preview:audiobook_chapter:{chapter_id}",
        progress_detail="Queued chapter-preview generation",
    )
    return {"status": "queued", "queued": True, "chapter_id": chapter_id}


@router.get(
    "/api/books/{book_id}/audiobook/chapters/{chapter_id}/audio",
    response_class=Response,
    responses=contracts.media_responses("audio/mpeg"),
)
async def get_chapter_audio(book_id: int, chapter_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    chapter = await db.get(AudiobookChapter, chapter_id)
    if chapter is None or chapter.book_id != book_id or not chapter.audio_file_path:
        raise HTTPException(status_code=404, detail="Audio not available")
    await get_audiobook_book_or_404(book_id, db)
    full_path = resolve_library_file(chapter.audio_file_path)
    if not full_path or not full_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    return FileResponse(str(full_path), media_type="audio/mpeg")


@router.get(
    "/api/books/{book_id}/audiobook/download",
    response_class=Response,
    responses=contracts.media_responses("application/epub+zip"),
)
async def download_audiobook(book_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    book = await get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status != "complete":
        raise HTTPException(status_code=409, detail="Audiobook generation is not complete")
    full_path = (book_audiobook_dir(book_id) / "audiobook.epub").resolve()
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Audiobook EPUB not found on disk")
    filename = f"{book.title or 'audiobook'}-audiobook.epub"
    return FileResponse(str(full_path), media_type="application/epub+zip", filename=filename)
