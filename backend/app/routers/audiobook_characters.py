"""Audiobook character roster and script (sentence) endpoints."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import api_schemas as contracts
from .. import crud
from ..audiobook_schemas import (
    CharacterResponse,
    CharacterUpdate,
    CharacterVoiceDesign,
    SentenceListResponse,
    SentenceResponse,
    SentenceUpdate,
    reading_block_fields,
)
from ..database import get_db
from ..models import (
    AudiobookChapter,
    AudiobookCharacter,
    AudiobookSentence,
)
from ..orm_updates import CharacterPatch
from ..services.audiobook_reading import ReadingBlock, chapter_reading_blocks
from ..services.audiobook_tts import (
    distinctive_voice_prompt,
    stable_character_seed,
)
from ..services.endpoint_pool import (
    EndpointSettings,
    settings_for_provider,
)
from ..services.library_paths import resolve_library_file
from ..services.processing_queue import queue_processing_job
from ..services.tts_providers import (
    design_omnivoice_voice,
    get_omnivoice_voice_sample,
    tts_provider_name,
)
from .audiobook_common import get_audiobook_book_or_404

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


async def _settings_for_locked_book_provider(
    db: AsyncSession,
    book_id: int,
) -> tuple[str, EndpointSettings | None]:
    settings = await crud.audiobook.get_audiobook_settings(db)
    try:
        provider = await crud.audiobook.lock_book_tts_provider(
            db,
            book_id,
            tts_provider_name(settings),
        )
        if settings is None:
            if provider != "stub":
                raise RuntimeError("Audiobook settings are required for the book's locked TTS provider")
            effective_settings = None
        else:
            effective_settings = settings_for_provider(settings, "tts", provider)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return provider, effective_settings


@router.get("/api/books/{book_id}/audiobook/characters", response_model=list[CharacterResponse])
async def list_characters(book_id: int, db: AsyncSession = Depends(get_db)) -> list[CharacterResponse]:
    book = await get_audiobook_book_or_404(book_id, db)
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
            voice_prompt=character.voice_prompt,
            tts_voice_id=character.tts_voice_id,
            tts_voice_provider=character.tts_voice_provider,
            tts_seed=character.tts_seed,
            is_narrator=character.is_narrator,
            aliases=character.aliases or [],
            evidence=character.evidence or [],
            sentence_count=stats[character.id]["sentence_count"] if character.id in stats else 0,
            average_confidence=stats[character.id]["average_confidence"] if character.id in stats else None,
        )
        for character in chars
    ]


@router.put("/api/audiobook/characters/{char_id}", response_model=CharacterResponse)
async def update_character(char_id: int, body: CharacterUpdate, db: AsyncSession = Depends(get_db)) -> CharacterResponse:
    data = body.model_dump(exclude_unset=True)
    voice_changed = bool({"voice_prompt", "tts_voice_id", "tts_seed"} & data.keys())

    existing = await crud.audiobook.get_character(db, char_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Character not found")
    await get_audiobook_book_or_404(existing.book_id, db)
    if (
        "voice_prompt" in data
        and data["voice_prompt"] != existing.voice_prompt
        and existing.tts_voice_provider in {"omnivoice", "qwen3"}
        and "tts_voice_id" not in data
    ):
        # The saved reference represents the old design. A new one will be
        # auditioned manually or provisioned automatically on next use.
        data["tts_voice_id"] = None
        data["tts_voice_provider"] = None
    if "tts_voice_id" in data:
        voice_id = data["tts_voice_id"]
        if isinstance(voice_id, str):
            voice_id = voice_id.strip() or None
        data["tts_voice_id"] = voice_id
        provider, _settings = await _settings_for_locked_book_provider(db, existing.book_id)
        data["tts_voice_provider"] = provider if voice_id else None

    try:
        patch = CharacterPatch.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="Invalid character update") from exc
    char = await crud.audiobook.update_character(db, char_id, patch)
    if char is None:
        raise HTTPException(status_code=404, detail="Character not found")
    linked_characters = await crud.audiobook.propagate_character_profile_across_series(db, char)

    if voice_changed:
        for linked_character in linked_characters:
            await crud.audiobook.cascade_voice_change(db, linked_character.id)

    return CharacterResponse.model_validate(char)


@router.post("/api/audiobook/characters/{char_id}/design-voice", response_model=CharacterResponse)
async def design_character_voice(
    char_id: int,
    body: CharacterVoiceDesign,
    db: AsyncSession = Depends(get_db),
) -> CharacterResponse:
    character = await crud.audiobook.get_character(db, char_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    await get_audiobook_book_or_404(character.book_id, db)
    provider, settings = await _settings_for_locked_book_provider(db, character.book_id)
    if settings is None or provider not in {"omnivoice", "qwen3"}:
        raise HTTPException(status_code=409, detail="Select OmniVoice or Qwen3-TTS in Audio Settings first")

    requested_prompt = body.voice_prompt if "voice_prompt" in body.model_fields_set else character.voice_prompt
    voice_prompt = distinctive_voice_prompt(
        character,
        requested_prompt or "[gender-neutral][pitch-medium][speed-normal]",
    )
    if character.tts_seed is None:
        character.tts_seed = stable_character_seed(character)
    avoid_voice_ids = [
        candidate.tts_voice_id
        for candidate in await crud.audiobook.get_characters_for_book(db, character.book_id)
        if candidate.id != character.id and candidate.tts_voice_provider == provider and candidate.tts_voice_id
    ]
    # Do not replace the saved profile/reference until a new design succeeds.
    designed = await design_omnivoice_voice(
        settings,
        voice_prompt,
        seed=character.tts_seed,
        avoid_voice_ids=avoid_voice_ids,
    )
    character.voice_prompt = designed.voice or voice_prompt
    character.tts_voice_id = designed.id
    character.tts_voice_provider = provider
    await db.commit()
    linked_characters = await crud.audiobook.propagate_character_profile_across_series(db, character)
    for linked_character in linked_characters:
        await crud.audiobook.cascade_voice_change(db, linked_character.id)
    await db.refresh(character)
    return CharacterResponse.model_validate(character)


@router.get(
    "/api/audiobook/characters/{char_id}/voice-sample", response_class=Response, responses=contracts.media_responses("audio/*")
)
async def get_character_voice_sample(
    char_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    character = await crud.audiobook.get_character(db, char_id)
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    await get_audiobook_book_or_404(character.book_id, db)
    if character.tts_voice_provider not in {"omnivoice", "qwen3"} or not character.tts_voice_id:
        raise HTTPException(status_code=404, detail="Design a consistent local voice first")
    provider, settings = await _settings_for_locked_book_provider(db, character.book_id)
    if settings is None or provider != character.tts_voice_provider:
        raise HTTPException(status_code=409, detail="The saved voice does not match this book's locked TTS provider")
    sample = await get_omnivoice_voice_sample(
        settings,
        character.tts_voice_id,
    )
    return Response(
        sample.audio_bytes,
        media_type=sample.media_type,
        # The character can be assigned a different provider voice later while
        # retaining the same sample URL, so do not let browsers keep a stale clip.
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/api/books/{book_id}/audiobook/roster/share-series", response_model=contracts.RosterShared)
async def share_character_roster_with_series(
    book_id: int,
    db: AsyncSession = Depends(get_db),
) -> contracts.RosterShared:
    book = await get_audiobook_book_or_404(book_id, db)
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
    book = await get_audiobook_book_or_404(book_id, db)
    sentences, total = await crud.audiobook.get_sentences_paginated(
        db,
        book_id,
        page=page,
        limit=limit,
        chapter_id=chapter_id,
        review_only=review_only,
    )
    reading_blocks: dict[str, ReadingBlock] = {}
    if chapter_id is not None:
        chapter = await db.get(AudiobookChapter, chapter_id)
        if chapter is not None and chapter.book_id == book_id:
            reading_blocks = chapter_reading_blocks(book, chapter)
    items = []
    for sentence in sentences:
        response = SentenceResponse.model_validate(sentence)
        items.append(
            response.model_copy(
                update=reading_block_fields(reading_blocks, sentence.html_element_id),
            )
        )
    return SentenceListResponse(
        items=items,
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
        await get_audiobook_book_or_404(chapter.book_id, db)
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


@router.post("/api/books/{book_id}/audiobook/sentences/{sentence_id}/generate-audio", response_model=contracts.SentenceQueued)
async def generate_sentence_audio(
    book_id: int,
    sentence_id: int,
    db: AsyncSession = Depends(get_db),
) -> contracts.SentenceQueued:
    book = await get_audiobook_book_or_404(book_id, db)
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
    await queue_processing_job(
        db=db,
        job_type="generate_sentence_audio",
        book_id=book_id,
        target_type="audiobook_sentence",
        target_id=sentence_id,
        target_content_version=book.content_version,
        dedupe_key=f"generate_sentence_audio:audiobook_sentence:{sentence_id}",
        progress_detail="Queued sentence-audio generation",
    )
    return {
        "status": "audio_queued",
        "queued": True,
        "sentence_id": sentence_id,
    }


@router.get(
    "/api/audiobook/sentences/{sentence_id}/audio", response_class=Response, responses=contracts.media_responses("audio/mpeg")
)
async def get_sentence_audio(sentence_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    sentence = await db.get(AudiobookSentence, sentence_id)
    if sentence is None or not sentence.audio_file_path:
        raise HTTPException(status_code=404, detail="Audio not available")
    chapter = await db.get(AudiobookChapter, sentence.chapter_id)
    if chapter:
        await get_audiobook_book_or_404(chapter.book_id, db)
    full_path = resolve_library_file(sentence.audio_file_path)
    if not full_path or not full_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    return FileResponse(str(full_path), media_type="audio/mpeg")
