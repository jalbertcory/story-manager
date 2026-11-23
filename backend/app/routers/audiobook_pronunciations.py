"""Pronunciation lexicon endpoints for AI narration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import api_schemas as contracts
from .. import crud
from ..audiobook_schemas import (
    PronunciationChange,
    PronunciationCreate,
    PronunciationListResponse,
    PronunciationPreview,
    PronunciationResponse,
    PronunciationUpdate,
)
from ..database import get_db
from ..models import AudiobookPronunciation, Book
from ..services.audiobook_pronunciation import (
    PronunciationRule,
    books_in_rule_scope,
    count_term_sentences,
    effective_rules,
    find_scope_duplicate,
    regenerate_sentences_with_terms,
    rule_scope,
    rules_for_book,
)
from ..services.endpoint_pool import settings_for_provider
from ..services.tts_providers import DEFAULT_VOICE_PROMPT, TTSRequest, synthesize_speech, tts_provider_name
from .audiobook_common import get_audiobook_book_or_404

router = APIRouter()


def _clean(value: str) -> str:
    return " ".join(value.split())


def _as_rule(rule: AudiobookPronunciation) -> PronunciationRule:
    return PronunciationRule(term=rule.term, spoken=rule.spoken, case_sensitive=rule.case_sensitive)


async def _response(
    db: AsyncSession,
    rule: AudiobookPronunciation,
    *,
    book: Book | None,
    active: bool,
) -> PronunciationResponse:
    return PronunciationResponse(
        id=rule.id,
        scope=rule_scope(rule),
        book_id=rule.book_id,
        series_name=rule.series_name,
        term=rule.term,
        spoken=rule.spoken,
        case_sensitive=rule.case_sensitive,
        active=active,
        sentence_count=await count_term_sentences(db, book.id, _as_rule(rule)) if book is not None and active else 0,
    )


async def _regenerate(
    db: AsyncSession,
    rule: AudiobookPronunciation,
    terms: list[PronunciationRule],
) -> tuple[int, int]:
    book_ids = await books_in_rule_scope(db, rule)
    reset = await regenerate_sentences_with_terms(db, book_ids, terms)
    return reset, len(book_ids) if reset else 0


async def _rule_or_404(db: AsyncSession, rule_id: int) -> AudiobookPronunciation:
    rule = await db.get(AudiobookPronunciation, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Pronunciation not found")
    return rule


@router.get("/api/books/{book_id}/audiobook/pronunciations", response_model=PronunciationListResponse)
async def list_pronunciations(book_id: int, db: AsyncSession = Depends(get_db)) -> PronunciationListResponse:
    book = await get_audiobook_book_or_404(book_id, db)
    rules = await rules_for_book(db, book)
    active_ids = {rule.id for rule in effective_rules(rules)}
    return PronunciationListResponse(
        series_name=book.series,
        rules=[await _response(db, rule, book=book, active=rule.id in active_ids) for rule in rules],
    )


@router.post("/api/books/{book_id}/audiobook/pronunciations", response_model=PronunciationChange, status_code=201)
async def create_pronunciation(
    book_id: int,
    body: PronunciationCreate,
    db: AsyncSession = Depends(get_db),
) -> PronunciationChange:
    book = await get_audiobook_book_or_404(book_id, db)
    term, spoken = _clean(body.term), _clean(body.spoken)
    if not term or not spoken:
        raise HTTPException(status_code=422, detail="Enter both the written word and how to say it")
    if body.scope == "series" and not book.series:
        raise HTTPException(status_code=409, detail="Assign this book to a series before adding a series pronunciation")
    scope_book_id = book.id if body.scope == "book" else None
    scope_series = book.series if body.scope == "series" else None
    if await find_scope_duplicate(db, term=term, book_id=scope_book_id, series_name=scope_series):
        raise HTTPException(status_code=409, detail=f"“{term}” already has a pronunciation at this level")

    rule = AudiobookPronunciation(
        book_id=scope_book_id,
        series_name=scope_series,
        term=term,
        spoken=spoken,
        case_sensitive=body.case_sensitive,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    reset, books = await _regenerate(db, rule, [_as_rule(rule)]) if body.regenerate else (0, 0)
    await db.refresh(rule)
    active_ids = {item.id for item in effective_rules(await rules_for_book(db, book))}
    return PronunciationChange(
        rule=await _response(db, rule, book=book, active=rule.id in active_ids),
        sentences_reset=reset,
        books_affected=books,
    )


@router.put("/api/audiobook/pronunciations/{rule_id}", response_model=PronunciationChange)
async def update_pronunciation(
    rule_id: int,
    body: PronunciationUpdate,
    db: AsyncSession = Depends(get_db),
) -> PronunciationChange:
    rule = await _rule_or_404(db, rule_id)
    previous = _as_rule(rule)
    data = body.model_dump(exclude_unset=True, exclude={"regenerate"})
    if isinstance(data.get("term"), str):
        term = _clean(data["term"])
        if not term:
            raise HTTPException(status_code=422, detail="Enter the written word")
        if await find_scope_duplicate(db, term=term, book_id=rule.book_id, series_name=rule.series_name, exclude_id=rule.id):
            raise HTTPException(status_code=409, detail=f"“{term}” already has a pronunciation at this level")
        rule.term = term
    if isinstance(data.get("spoken"), str):
        spoken = _clean(data["spoken"])
        if not spoken:
            raise HTTPException(status_code=422, detail="Enter how to say the word")
        rule.spoken = spoken
    if isinstance(data.get("case_sensitive"), bool):
        rule.case_sensitive = data["case_sensitive"]
    await db.commit()
    await db.refresh(rule)

    current = _as_rule(rule)
    # Sentences with the old spelling lose the rule; ones with the new gain it.
    reset, books = await _regenerate(db, rule, [previous, current]) if body.regenerate and current != previous else (0, 0)
    await db.refresh(rule)
    return PronunciationChange(
        rule=await _response(db, rule, book=None, active=True),
        sentences_reset=reset,
        books_affected=books,
    )


@router.delete("/api/audiobook/pronunciations/{rule_id}", response_model=PronunciationChange)
async def delete_pronunciation(
    rule_id: int,
    regenerate: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> PronunciationChange:
    rule = await _rule_or_404(db, rule_id)
    removed = _as_rule(rule)
    scope_rule = AudiobookPronunciation(book_id=rule.book_id, series_name=rule.series_name, term=rule.term, spoken=rule.spoken)
    await db.delete(rule)
    await db.commit()
    reset, books = await _regenerate(db, scope_rule, [removed]) if regenerate else (0, 0)
    return PronunciationChange(rule=None, sentences_reset=reset, books_affected=books)


@router.post(
    "/api/books/{book_id}/audiobook/pronunciations/preview",
    response_class=Response,
    responses=contracts.media_responses("audio/mpeg"),
)
async def preview_pronunciation(
    book_id: int,
    body: PronunciationPreview,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Speak a candidate respelling in the book's narrator voice."""
    await get_audiobook_book_or_404(book_id, db)
    text = _clean(body.text)
    if not any(character.isalnum() for character in text):
        raise HTTPException(status_code=422, detail="Enter something that can be spoken")
    settings = await crud.audiobook.get_audiobook_settings(db)
    try:
        provider = await crud.audiobook.lock_book_tts_provider(db, book_id, tts_provider_name(settings))
        if settings is None and provider != "stub":
            raise RuntimeError("Audio & AI Configuration is required for this book's speech provider")
        effective = settings_for_provider(settings, "tts", provider) if settings is not None else None
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    cast = await crud.audiobook.get_characters_for_book(db, book_id)
    narrator = next((character for character in cast if character.is_narrator), None)
    voice_matches = narrator is not None and narrator.tts_voice_provider == provider and bool(narrator.tts_voice_id)
    request = TTSRequest(
        text=text,
        voice_prompt=narrator.voice_prompt if narrator and narrator.voice_prompt else DEFAULT_VOICE_PROMPT,
        voice_id=narrator.tts_voice_id if narrator and voice_matches else None,
        voice_provider=narrator.tts_voice_provider if narrator and voice_matches else None,
        seed=narrator.tts_seed if narrator else None,
    )
    try:
        audio = await synthesize_speech(effective, request)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"The speech provider could not preview this: {exc}") from exc
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, no-store"})
