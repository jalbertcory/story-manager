"""Audiobook pipeline API endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..database import get_db
from ..models import AudiobookChapter, AudiobookCharacter, AudiobookSentence, Book
from ..services.audiobook_queue import get_audiobook_queue
from ..services import audiobook_llm

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AudiobookStatusResponse(BaseModel):
    pipeline_status: Optional[str]
    next_phase: str
    pause_requested: bool
    stop_after_phase: Optional[str]
    last_error: Optional[str]
    sentence_counts: dict[str, int]
    review_counts: dict[str, int]
    summary: Optional[str]
    progress_current: int
    progress_total: int
    progress_percent: Optional[float]
    progress_detail: Optional[str]
    pipeline_started_at: Optional[datetime]
    pipeline_updated_at: Optional[datetime]
    batch_limit: Optional[int]
    llm_requests: int
    llm_provider: str
    llm_model: Optional[str]


class CharacterResponse(BaseModel):
    id: int
    book_id: int
    series_character_id: Optional[int] = None
    shared_series_name: Optional[str] = None
    name: str
    description: Optional[str]
    voice_design_prompt: Optional[str]
    is_narrator: bool
    aliases: Optional[list[str]] = None
    evidence: Optional[list[str]] = None
    sentence_count: int = 0
    average_confidence: Optional[float] = None

    model_config = {"from_attributes": True}


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    voice_design_prompt: Optional[str] = None
    is_narrator: Optional[bool] = None


class SentenceResponse(BaseModel):
    id: int
    chapter_id: int
    character_id: Optional[int]
    html_element_id: str
    sequence_order: int
    original_text: str
    tagged_text: Optional[str]
    audio_file_path: Optional[str]
    audio_duration_ms: Optional[int]
    speaker_confidence: Optional[float]
    speaker_reason: Optional[str]
    status: str

    model_config = {"from_attributes": True}


class SentenceUpdate(BaseModel):
    character_id: Optional[int] = None
    tagged_text: Optional[str] = None


class ChapterResponse(BaseModel):
    id: int
    book_id: int
    chapter_number: int
    content_file_name: Optional[str]
    smil_file_path: Optional[str]
    audio_file_path: Optional[str]
    needs_reassembly: bool
    summary: Optional[str]
    summary_updated_at: Optional[datetime]
    preview_status: Optional[str]
    preview_error: Optional[str]
    sentence_count: int = 0
    processed_sentence_count: int = 0
    audio_generated_count: int = 0
    low_confidence_count: int = 0

    model_config = {"from_attributes": True}


class SettingsResponse(BaseModel):
    id: Optional[int]
    llm_provider: Optional[str]
    llm_api_key_set: bool
    llm_base_url: Optional[str]
    llm_model: Optional[str]
    omnivoice_endpoint: Optional[str]
    roster_prompt_template: Optional[str]
    diarization_prompt_template: Optional[str]


class SettingsUpdate(BaseModel):
    llm_provider: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    omnivoice_endpoint: Optional[str] = None
    roster_prompt_template: Optional[str] = None
    diarization_prompt_template: Optional[str] = None


class SentenceListResponse(BaseModel):
    items: list[SentenceResponse]
    total: int
    page: int
    limit: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_book_or_404(book_id: int, db: AsyncSession) -> Book:
    book = await db.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


async def _get_audiobook_book_or_404(book_id: int, db: AsyncSession) -> Book:
    book = await _get_book_or_404(book_id, db)
    if not book.audiobook_enabled:
        raise HTTPException(status_code=403, detail="Audiobook pipeline is not enabled for this book")
    return book


def _resolve_path(relative_path: Optional[str]) -> Optional[Path]:
    if not relative_path:
        return None
    path = (LIBRARY_PATH.parent / relative_path).resolve()
    return path if path.is_relative_to(LIBRARY_PATH.resolve()) else None


# ---------------------------------------------------------------------------
# Pipeline control
# ---------------------------------------------------------------------------


@router.post("/api/books/{book_id}/audiobook/start")
async def start_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
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

    queue = get_audiobook_queue()
    queued = await queue.enqueue(book_id)
    current_status = (await db.get(Book, book_id)).audiobook_pipeline_status
    return {"status": current_status, "queued": queued}


@router.post("/api/books/{book_id}/audiobook/step")
async def step_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Run exactly the next recoverable phase, then stop for review."""
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        return {"status": book.audiobook_pipeline_status, "queued": False}

    if book.audiobook_pipeline_status == "error" and await crud.audiobook.has_sentence_status(db, book_id, "error"):
        await crud.audiobook.reset_error_sentences_for_book(db, book_id)

    next_phase = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    if next_phase == "complete":
        await crud.audiobook.configure_book_pipeline_run(db, book_id, status="complete", stop_after_phase=None)
        return {"status": "complete", "queued": False}

    await crud.audiobook.configure_book_pipeline_run(db, book_id, status=next_phase, stop_after_phase=next_phase)
    queued = await get_audiobook_queue().enqueue(book_id)
    return {"status": next_phase, "queued": queued, "stop_after_phase": next_phase}


@router.post("/api/books/{book_id}/audiobook/run-batch")
async def run_pipeline_batch(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Run one durable LLM/TTS/assembly work unit, then pause for review."""
    book = await _get_audiobook_book_or_404(book_id, db)
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
    queued = await get_audiobook_queue().enqueue(book_id)
    return {"status": next_phase, "queued": queued, "batch_limit": 1}


@router.post("/api/books/{book_id}/audiobook/pause")
async def pause_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    active = book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling")
    await crud.audiobook.request_book_pipeline_pause(db, book_id)
    if active:
        return {"status": book.audiobook_pipeline_status, "pause_requested": True}
    await crud.audiobook.pause_book_pipeline_if_requested(db, book_id)
    return {"status": "paused", "pause_requested": False}


@router.post("/api/books/{book_id}/audiobook/rebuild")
async def rebuild_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    queue = get_audiobook_queue()
    if book.audiobook_pipeline_status in (
        "ingesting",
        "roster_gen",
        "diarizing",
        "audio_gen",
        "assembling",
    ) or queue.has_book_job(book_id):
        raise HTTPException(status_code=409, detail="Pause the active pipeline before rebuilding it")
    # Delete existing pipeline data so ingestion runs fresh
    await crud.audiobook.delete_chapters_for_book(db, book_id)
    await crud.audiobook.delete_characters_for_book(db, book_id)
    await crud.audiobook.set_book_audiobook_summary(db, book_id, None)
    await crud.audiobook.configure_book_pipeline_run(db, book_id, status="ingesting", stop_after_phase=None)
    await queue.enqueue(book_id)
    return {"status": "ingesting", "queued": True}


@router.post("/api/books/{book_id}/audiobook/roster/rebuild")
async def rebuild_character_roster(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Re-run roster and diarization analysis without parsing the EPUB again."""
    book = await _get_audiobook_book_or_404(book_id, db)
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
    queued = await get_audiobook_queue().enqueue(book_id)
    return {"status": "roster_gen", "queued": queued, "stop_after_phase": "roster_gen"}


@router.get("/api/books/{book_id}/audiobook/status", response_model=AudiobookStatusResponse)
async def get_pipeline_status(book_id: int, db: AsyncSession = Depends(get_db)) -> AudiobookStatusResponse:
    book = await _get_audiobook_book_or_404(book_id, db)
    counts = await crud.audiobook.count_sentences_by_status(db, book_id)
    review_counts = await crud.audiobook.count_sentence_review_flags(db, book_id)
    next_phase = await crud.audiobook.infer_audiobook_resume_status(db, book_id)
    settings = await crud.audiobook.get_audiobook_settings(db)
    await db.refresh(book)
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
    )


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


@router.get("/api/books/{book_id}/audiobook/characters", response_model=list[CharacterResponse])
async def list_characters(book_id: int, db: AsyncSession = Depends(get_db)) -> list[CharacterResponse]:
    book = await _get_audiobook_book_or_404(book_id, db)
    chars = await crud.audiobook.get_characters_for_book(db, book_id)
    stats = await crud.audiobook.get_character_sentence_stats(db, book_id)
    return [
        CharacterResponse(
            id=character.id,
            book_id=character.book_id,
            series_character_id=character.series_character_id,
            shared_series_name=book.series if character.series_character_id else None,
            name=character.name,
            description=character.description,
            voice_design_prompt=character.voice_design_prompt,
            is_narrator=character.is_narrator,
            aliases=character.aliases or [],
            evidence=character.evidence or [],
            sentence_count=stats.get(character.id, {}).get("sentence_count", 0),
            average_confidence=stats.get(character.id, {}).get("average_confidence"),
        )
        for character in chars
    ]


@router.put("/api/audiobook/characters/{char_id}", response_model=CharacterResponse)
async def update_character(char_id: int, body: CharacterUpdate, db: AsyncSession = Depends(get_db)) -> CharacterResponse:
    data = body.model_dump(exclude_none=True)
    voice_changed = "voice_design_prompt" in data

    existing = await crud.audiobook.get_character(db, char_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Character not found")
    await _get_audiobook_book_or_404(existing.book_id, db)

    char = await crud.audiobook.update_character(db, char_id, data)
    linked_characters = await crud.audiobook.propagate_character_profile_across_series(db, char)

    if voice_changed:
        for linked_character in linked_characters:
            await crud.audiobook.cascade_voice_change(db, linked_character.id)

    return CharacterResponse.model_validate(char)


@router.post("/api/books/{book_id}/audiobook/roster/share-series")
async def share_character_roster_with_series(
    book_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    if not book.series:
        raise HTTPException(status_code=409, detail="Assign this book to a series before sharing its roster")
    characters = await crud.audiobook.get_characters_for_book(db, book_id)
    if not characters:
        raise HTTPException(status_code=409, detail="Generate a character roster before sharing it")
    linked = await crud.audiobook.sync_book_roster_with_series(
        db,
        book,
        characters,
        prefer_series=True,
    )
    affected_book_ids: set[int] = {book_id}
    for character in characters:
        siblings = await crud.audiobook.propagate_character_profile_across_series(db, character)
        affected_book_ids.update(sibling.book_id for sibling in siblings)
    return {
        "series": book.series,
        "profiles": linked,
        "books_updated": len(affected_book_ids),
    }


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------


@router.get("/api/books/{book_id}/audiobook/sentences", response_model=SentenceListResponse)
async def list_sentences(
    book_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=1000),
    chapter_id: Optional[int] = Query(None),
    review_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> SentenceListResponse:
    await _get_audiobook_book_or_404(book_id, db)
    sentences, total = await crud.audiobook.get_sentences_paginated(
        db,
        book_id,
        page=page,
        limit=limit,
        chapter_id=chapter_id,
        review_only=review_only,
    )
    return SentenceListResponse(
        items=[SentenceResponse.model_validate(s) for s in sentences],
        total=total,
        page=page,
        limit=limit,
    )


@router.put("/api/audiobook/sentences/{sentence_id}", response_model=SentenceResponse)
async def update_sentence(sentence_id: int, body: SentenceUpdate, db: AsyncSession = Depends(get_db)) -> SentenceResponse:
    existing = await db.get(AudiobookSentence, sentence_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Sentence not found")
    chapter = await db.get(AudiobookChapter, existing.chapter_id)
    if chapter:
        await _get_audiobook_book_or_404(chapter.book_id, db)
    if body.character_id is not None:
        character = await db.get(AudiobookCharacter, body.character_id)
        if chapter is None or character is None or character.book_id != chapter.book_id:
            raise HTTPException(status_code=404, detail="Character not found for this book")

    sentence = await crud.audiobook.update_sentence_speaker(
        db,
        sentence_id=sentence_id,
        character_id=body.character_id,
        tagged_text=body.tagged_text or "",
    )

    return SentenceResponse.model_validate(sentence)


@router.post("/api/books/{book_id}/audiobook/sentences/{sentence_id}/generate-audio")
async def generate_sentence_audio(
    book_id: int,
    sentence_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status in ("ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"):
        raise HTTPException(status_code=409, detail="Pause the full-book pipeline before generating sentence audio")
    sentence = await db.get(AudiobookSentence, sentence_id)
    if sentence is None:
        raise HTTPException(status_code=404, detail="Audiobook sentence not found")
    chapter = await db.get(AudiobookChapter, sentence.chapter_id)
    if chapter is None or chapter.book_id != book_id:
        raise HTTPException(status_code=404, detail="Audiobook sentence not found")
    if sentence.status in ("audio_queued", "audio_generating"):
        return {"status": sentence.status, "queued": False, "sentence_id": sentence_id}
    if sentence.status not in ("ready_for_audio", "error"):
        raise HTTPException(status_code=409, detail=f"Sentence is {sentence.status}, not ready for audio")
    if sentence.character_id is None:
        raise HTTPException(status_code=409, detail="Assign a speaker before generating sentence audio")

    await crud.audiobook.set_sentence_status(db, sentence_id, "audio_queued")
    queued = await get_audiobook_queue().enqueue_sentence_audio(book_id, sentence_id)
    return {"status": "audio_queued", "queued": queued, "sentence_id": sentence_id}


@router.get("/api/audiobook/sentences/{sentence_id}/audio")
async def get_sentence_audio(sentence_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    sentence = await db.get(AudiobookSentence, sentence_id)
    if sentence is None or not sentence.audio_file_path:
        raise HTTPException(status_code=404, detail="Audio not available")
    chapter = await db.get(AudiobookChapter, sentence.chapter_id)
    if chapter:
        await _get_audiobook_book_or_404(chapter.book_id, db)
    full_path = _resolve_path(sentence.audio_file_path)
    if not full_path or not full_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    return FileResponse(str(full_path), media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------


@router.get("/api/books/{book_id}/audiobook/chapters", response_model=list[ChapterResponse])
async def list_chapters(book_id: int, db: AsyncSession = Depends(get_db)) -> list[ChapterResponse]:
    await _get_audiobook_book_or_404(book_id, db)
    chapters = await crud.audiobook.get_chapters_for_book(db, book_id)
    response = []
    for chapter in chapters:
        sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        processed = [sentence for sentence in sentences if sentence.status != "pending_diarization"]
        response.append(
            ChapterResponse(
                id=chapter.id,
                book_id=chapter.book_id,
                chapter_number=chapter.chapter_number,
                content_file_name=chapter.content_file_name,
                smil_file_path=chapter.smil_file_path,
                audio_file_path=chapter.audio_file_path,
                needs_reassembly=chapter.needs_reassembly,
                summary=chapter.summary,
                summary_updated_at=chapter.summary_updated_at,
                preview_status=chapter.preview_status,
                preview_error=chapter.preview_error,
                sentence_count=len(sentences),
                processed_sentence_count=len(processed),
                audio_generated_count=sum(1 for sentence in sentences if sentence.status == "audio_generated"),
                low_confidence_count=sum(
                    1
                    for sentence in sentences
                    if sentence.speaker_confidence is not None and sentence.speaker_confidence < 0.65
                ),
            )
        )
    return response


@router.post("/api/books/{book_id}/audiobook/chapters/{chapter_id}/preview-audio")
async def generate_chapter_preview(
    book_id: int,
    chapter_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    book = await _get_audiobook_book_or_404(book_id, db)
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
    queued = await get_audiobook_queue().enqueue_preview(book_id, chapter_id)
    return {"status": "queued", "queued": queued, "chapter_id": chapter_id}


@router.get("/api/books/{book_id}/audiobook/chapters/{chapter_id}/audio")
async def get_chapter_audio(book_id: int, chapter_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    chapter = await db.get(AudiobookChapter, chapter_id)
    if chapter is None or chapter.book_id != book_id or not chapter.audio_file_path:
        raise HTTPException(status_code=404, detail="Audio not available")
    await _get_audiobook_book_or_404(book_id, db)
    full_path = _resolve_path(chapter.audio_file_path)
    if not full_path or not full_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    return FileResponse(str(full_path), media_type="audio/mpeg")


@router.get("/api/books/{book_id}/audiobook/download")
async def download_audiobook(book_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    book = await _get_audiobook_book_or_404(book_id, db)
    if book.audiobook_pipeline_status != "complete":
        raise HTTPException(status_code=409, detail="Audiobook generation is not complete")
    full_path = (LIBRARY_PATH / "audiobooks" / str(book_id) / "audiobook.epub").resolve()
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Audiobook EPUB not found on disk")
    filename = f"{book.title or 'audiobook'}-audiobook.epub"
    return FileResponse(str(full_path), media_type="application/epub+zip", filename=filename)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/api/audiobook/settings", response_model=SettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None:
        return SettingsResponse(
            id=None,
            llm_provider=None,
            llm_api_key_set=False,
            llm_base_url=None,
            llm_model=None,
            omnivoice_endpoint=None,
            roster_prompt_template=None,
            diarization_prompt_template=None,
        )
    return SettingsResponse(
        id=settings.id,
        llm_provider=settings.llm_provider,
        llm_api_key_set=bool(settings.llm_api_key),
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        omnivoice_endpoint=settings.omnivoice_endpoint,
        roster_prompt_template=settings.roster_prompt_template,
        diarization_prompt_template=settings.diarization_prompt_template,
    )


@router.put("/api/audiobook/settings", response_model=SettingsResponse)
async def update_settings(body: SettingsUpdate, db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    data = body.model_dump(exclude_none=True)
    settings = await crud.audiobook.upsert_audiobook_settings(db, data)
    return SettingsResponse(
        id=settings.id,
        llm_provider=settings.llm_provider,
        llm_api_key_set=bool(settings.llm_api_key),
        llm_base_url=settings.llm_base_url,
        llm_model=settings.llm_model,
        omnivoice_endpoint=settings.omnivoice_endpoint,
        roster_prompt_template=settings.roster_prompt_template,
        diarization_prompt_template=settings.diarization_prompt_template,
    )


@router.post("/api/audiobook/settings/test-llm")
async def test_llm_settings(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    settings = await crud.audiobook.get_audiobook_settings(db)
    if settings is None or (settings.llm_provider or "stub").lower() == "stub":
        return {"status": "ready", "provider": "stub", "model": None, "response": "local harness"}
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }
    raw = await audiobook_llm._call_llm(
        settings,
        [{"role": "user", "content": "Return JSON with status set to ready."}],
        response_schema=schema,
    )
    parsed = audiobook_llm._extract_json(raw)
    return {
        "status": parsed.get("status", "unknown") if isinstance(parsed, dict) else "unknown",
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "response": parsed,
    }
