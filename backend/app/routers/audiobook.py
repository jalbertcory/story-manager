"""Audiobook pipeline API endpoints."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AudiobookStatusResponse(BaseModel):
    pipeline_status: Optional[str]
    sentence_counts: dict[str, int]


class CharacterResponse(BaseModel):
    id: int
    book_id: int
    name: str
    description: Optional[str]
    voice_design_prompt: Optional[str]
    is_narrator: bool

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
        await crud.audiobook.set_book_pipeline_status(db, book_id, "complete")
        return {"status": "complete", "queued": False}

    await crud.audiobook.set_book_pipeline_status(db, book_id, resume_status)

    queue = get_audiobook_queue()
    queued = await queue.enqueue(book_id)
    current_status = (await db.get(Book, book_id)).audiobook_pipeline_status
    return {"status": current_status, "queued": queued}


@router.post("/api/books/{book_id}/audiobook/pause")
async def pause_pipeline(book_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _get_audiobook_book_or_404(book_id, db)
    await crud.audiobook.set_book_pipeline_status(db, book_id, "paused")
    return {"status": "paused"}


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
    await crud.audiobook.set_book_pipeline_status(db, book_id, "ingesting")
    await queue.enqueue(book_id)
    return {"status": "ingesting", "queued": True}


@router.get("/api/books/{book_id}/audiobook/status", response_model=AudiobookStatusResponse)
async def get_pipeline_status(book_id: int, db: AsyncSession = Depends(get_db)) -> AudiobookStatusResponse:
    book = await _get_audiobook_book_or_404(book_id, db)
    counts = await crud.audiobook.count_sentences_by_status(db, book_id)
    return AudiobookStatusResponse(
        pipeline_status=book.audiobook_pipeline_status,
        sentence_counts=counts,
    )


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


@router.get("/api/books/{book_id}/audiobook/characters", response_model=list[CharacterResponse])
async def list_characters(book_id: int, db: AsyncSession = Depends(get_db)) -> list[CharacterResponse]:
    await _get_audiobook_book_or_404(book_id, db)
    chars = await crud.audiobook.get_characters_for_book(db, book_id)
    return [CharacterResponse.model_validate(c) for c in chars]


@router.put("/api/audiobook/characters/{char_id}", response_model=CharacterResponse)
async def update_character(char_id: int, body: CharacterUpdate, db: AsyncSession = Depends(get_db)) -> CharacterResponse:
    data = body.model_dump(exclude_none=True)
    voice_changed = "voice_design_prompt" in data

    existing = await crud.audiobook.get_character(db, char_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Character not found")
    await _get_audiobook_book_or_404(existing.book_id, db)

    char = await crud.audiobook.update_character(db, char_id, data)

    if voice_changed:
        await crud.audiobook.cascade_voice_change(db, char_id)
        # Re-enqueue for TTS phase
        queue = get_audiobook_queue()
        await crud.audiobook.set_book_pipeline_status(db, char.book_id, "audio_gen")
        await queue.enqueue(char.book_id)

    return CharacterResponse.model_validate(char)


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------


@router.get("/api/books/{book_id}/audiobook/sentences", response_model=SentenceListResponse)
async def list_sentences(
    book_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    chapter_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> SentenceListResponse:
    await _get_audiobook_book_or_404(book_id, db)
    sentences, total = await crud.audiobook.get_sentences_paginated(db, book_id, page=page, limit=limit, chapter_id=chapter_id)
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

    # Re-enqueue for TTS
    if chapter:
        queue = get_audiobook_queue()
        await crud.audiobook.set_book_pipeline_status(db, chapter.book_id, "audio_gen")
        await queue.enqueue(chapter.book_id)

    return SentenceResponse.model_validate(sentence)


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
    return [ChapterResponse.model_validate(c) for c in chapters]


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
