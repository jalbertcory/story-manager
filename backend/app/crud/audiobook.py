"""CRUD operations for the audiobook pipeline tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    AudiobookSettings,
    AudiobookChapter,
    AudiobookCharacter,
    AudiobookSeriesCharacter,
    AudiobookSentence,
    Book,
)

ROSTER_REFRESH_STOP_MARKER = "roster_gen:refresh_series_metadata"

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


async def get_audiobook_settings(db: AsyncSession) -> Optional[AudiobookSettings]:
    result = await db.execute(select(AudiobookSettings).limit(1))
    return result.scalar_one_or_none()


async def upsert_audiobook_settings(db: AsyncSession, data: dict) -> AudiobookSettings:
    settings = await get_audiobook_settings(db)
    if settings is None:
        settings = AudiobookSettings(**data)
        db.add(settings)
    else:
        for key, value in data.items():
            setattr(settings, key, value)
    await db.commit()
    await db.refresh(settings)
    return settings


# ---------------------------------------------------------------------------
# Book pipeline status
# ---------------------------------------------------------------------------


async def set_book_pipeline_status(db: AsyncSession, book_id: int, status: Optional[str]) -> None:
    await db.execute(
        update(Book)
        .where(Book.id == book_id)
        .values(audiobook_pipeline_status=status, audiobook_pipeline_updated_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def configure_book_pipeline_run(
    db: AsyncSession,
    book_id: int,
    *,
    status: str,
    stop_after_phase: Optional[str],
    batch_limit: Optional[int] = None,
) -> None:
    """Start or resume a run and clear stale pause/error state atomically."""
    await db.execute(
        update(Book)
        .where(Book.id == book_id)
        .values(
            audiobook_pipeline_status=status,
            audiobook_stop_after_phase=stop_after_phase,
            audiobook_pause_requested=False,
            audiobook_last_error=None,
            audiobook_batch_limit=batch_limit,
            audiobook_progress_current=0,
            audiobook_progress_total=0,
            audiobook_progress_detail=None,
            audiobook_pipeline_started_at=datetime.now(timezone.utc),
            audiobook_pipeline_updated_at=datetime.now(timezone.utc),
            audiobook_llm_requests=0,
        )
    )
    await db.commit()


async def request_book_pipeline_pause(db: AsyncSession, book_id: int) -> None:
    await db.execute(update(Book).where(Book.id == book_id).values(audiobook_pause_requested=True))
    await db.commit()


async def update_book_pipeline_progress(
    db: AsyncSession,
    book_id: int,
    *,
    current: int,
    total: int,
    detail: Optional[str],
    llm_request_increment: int = 0,
) -> None:
    values = {
        "audiobook_progress_current": max(0, current),
        "audiobook_progress_total": max(0, total),
        "audiobook_progress_detail": detail,
        "audiobook_pipeline_updated_at": datetime.now(timezone.utc),
    }
    if llm_request_increment:
        values["audiobook_llm_requests"] = Book.audiobook_llm_requests + llm_request_increment
    await db.execute(update(Book).where(Book.id == book_id).values(**values))
    await db.commit()


async def set_book_audiobook_summary(db: AsyncSession, book_id: int, summary: Optional[str]) -> None:
    await db.execute(
        update(Book)
        .where(Book.id == book_id)
        .values(audiobook_summary=summary, audiobook_pipeline_updated_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def consume_book_batch_limit(db: AsyncSession, book_id: int) -> bool:
    """Consume one durable work unit and pause when a one-batch run is exhausted."""
    result = await db.execute(select(Book.audiobook_batch_limit).where(Book.id == book_id))
    remaining = result.scalar_one_or_none()
    if remaining is None:
        return False
    remaining -= 1
    if remaining > 0:
        await db.execute(update(Book).where(Book.id == book_id).values(audiobook_batch_limit=remaining))
        await db.commit()
        return False
    await db.execute(
        update(Book)
        .where(Book.id == book_id)
        .values(
            audiobook_pipeline_status="paused",
            audiobook_batch_limit=None,
            audiobook_stop_after_phase=None,
            audiobook_pause_requested=False,
            audiobook_pipeline_updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return True


async def pause_book_pipeline_if_requested(db: AsyncSession, book_id: int) -> bool:
    """Acknowledge a cooperative pause request at a durable work boundary."""
    result = await db.execute(select(Book.audiobook_pause_requested).where(Book.id == book_id))
    if not result.scalar_one_or_none():
        return False
    await db.execute(
        update(Book)
        .where(Book.id == book_id)
        .values(
            audiobook_pipeline_status="paused",
            audiobook_pause_requested=False,
            audiobook_stop_after_phase=None,
            audiobook_batch_limit=None,
            audiobook_pipeline_updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return True


async def pause_book_pipeline_after_phase(db: AsyncSession, book_id: int, phase: str) -> bool:
    """Stop a single-stage run once its requested phase has committed."""
    result = await db.execute(
        select(Book.audiobook_stop_after_phase, Book.audiobook_pipeline_status).where(Book.id == book_id)
    )
    row = result.one_or_none()
    requested_phase = row.audiobook_stop_after_phase.split(":", 1)[0] if row and row.audiobook_stop_after_phase else None
    if row is None or requested_phase != phase or row.audiobook_pipeline_status == "complete":
        return False
    await db.execute(
        update(Book)
        .where(Book.id == book_id)
        .values(
            audiobook_pipeline_status="paused",
            audiobook_stop_after_phase=None,
            audiobook_batch_limit=None,
            audiobook_pipeline_updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return True


async def set_book_pipeline_error(db: AsyncSession, book_id: int, message: str) -> None:
    await db.execute(
        update(Book)
        .where(Book.id == book_id)
        .values(
            audiobook_pipeline_status="error",
            audiobook_pause_requested=False,
            audiobook_stop_after_phase=None,
            audiobook_batch_limit=None,
            audiobook_pipeline_updated_at=datetime.now(timezone.utc),
            audiobook_last_error=message,
        )
    )
    await db.commit()


async def get_in_progress_audiobook_books(db: AsyncSession) -> list[Book]:
    active_statuses = ["ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"]
    result = await db.execute(
        select(Book).where(
            Book.audiobook_enabled.is_(True),
            Book.audiobook_pipeline_status.in_(active_statuses),
        )
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------


async def create_chapter(
    db: AsyncSession,
    book_id: int,
    chapter_number: int,
    content_file_name: Optional[str] = None,
) -> AudiobookChapter:
    chapter = AudiobookChapter(book_id=book_id, chapter_number=chapter_number, content_file_name=content_file_name)
    db.add(chapter)
    await db.flush()
    return chapter


async def get_chapters_for_book(db: AsyncSession, book_id: int) -> list[AudiobookChapter]:
    result = await db.execute(
        select(AudiobookChapter).where(AudiobookChapter.book_id == book_id).order_by(AudiobookChapter.chapter_number)
    )
    return list(result.scalars().all())


async def get_chapters_needing_reassembly(db: AsyncSession, book_id: int) -> list[AudiobookChapter]:
    result = await db.execute(
        select(AudiobookChapter)
        .where(AudiobookChapter.book_id == book_id, AudiobookChapter.needs_reassembly.is_(True))
        .order_by(AudiobookChapter.chapter_number)
    )
    return list(result.scalars().all())


async def get_chapters_pending_assembly(db: AsyncSession, book_id: int) -> list[AudiobookChapter]:
    result = await db.execute(
        select(AudiobookChapter)
        .where(
            AudiobookChapter.book_id == book_id,
            or_(
                AudiobookChapter.needs_reassembly.is_(True),
                AudiobookChapter.audio_file_path.is_(None),
                AudiobookChapter.smil_file_path.is_(None),
            ),
        )
        .order_by(AudiobookChapter.chapter_number)
    )
    return list(result.scalars().all())


async def update_chapter_assembly(
    db: AsyncSession,
    chapter_id: int,
    audio_file_path: str,
    smil_file_path: str,
) -> None:
    await db.execute(
        update(AudiobookChapter)
        .where(AudiobookChapter.id == chapter_id)
        .values(audio_file_path=audio_file_path, smil_file_path=smil_file_path, needs_reassembly=False)
    )
    await db.commit()


async def update_chapter_summary(db: AsyncSession, chapter_id: int, summary: Optional[str]) -> None:
    await db.execute(
        update(AudiobookChapter)
        .where(AudiobookChapter.id == chapter_id)
        .values(summary=summary, summary_updated_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def flag_chapter_for_reassembly(db: AsyncSession, chapter_id: int) -> None:
    await db.execute(
        update(AudiobookChapter)
        .where(AudiobookChapter.id == chapter_id)
        .values(needs_reassembly=True, preview_status=None, preview_error=None)
    )
    await db.commit()


async def set_chapter_preview_status(
    db: AsyncSession,
    chapter_id: int,
    status: Optional[str],
    error: Optional[str] = None,
) -> None:
    await db.execute(
        update(AudiobookChapter).where(AudiobookChapter.id == chapter_id).values(preview_status=status, preview_error=error)
    )
    await db.commit()


async def get_chapters_with_pending_previews(db: AsyncSession) -> list[AudiobookChapter]:
    result = await db.execute(select(AudiobookChapter).where(AudiobookChapter.preview_status.in_(["queued", "generating"])))
    return list(result.scalars().all())


async def delete_chapters_for_book(db: AsyncSession, book_id: int) -> None:
    chapters = await get_chapters_for_book(db, book_id)
    for ch in chapters:
        await db.delete(ch)
    await db.commit()


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------


async def create_characters_bulk(db: AsyncSession, book_id: int, characters_data: list[dict]) -> list[AudiobookCharacter]:
    chars = [AudiobookCharacter(book_id=book_id, **c) for c in characters_data]
    db.add_all(chars)
    await db.commit()
    for c in chars:
        await db.refresh(c)
    return chars


async def get_characters_for_book(db: AsyncSession, book_id: int) -> list[AudiobookCharacter]:
    result = await db.execute(
        select(AudiobookCharacter)
        .where(AudiobookCharacter.book_id == book_id)
        .order_by(AudiobookCharacter.is_narrator.desc(), AudiobookCharacter.name)
    )
    return list(result.scalars().all())


async def get_character(db: AsyncSession, char_id: int) -> Optional[AudiobookCharacter]:
    return await db.get(AudiobookCharacter, char_id)


async def update_character(db: AsyncSession, char_id: int, data: dict) -> Optional[AudiobookCharacter]:
    char = await db.get(AudiobookCharacter, char_id)
    if char is None:
        return None
    for key, value in data.items():
        setattr(char, key, value)
    await db.commit()
    await db.refresh(char)
    return char


def _canonical_character_name(name: str) -> str:
    return " ".join(name.casefold().split())


async def get_series_characters(db: AsyncSession, series_name: str) -> list[AudiobookSeriesCharacter]:
    result = await db.execute(
        select(AudiobookSeriesCharacter)
        .where(func.lower(AudiobookSeriesCharacter.series_name) == series_name.lower())
        .order_by(AudiobookSeriesCharacter.is_narrator.desc(), AudiobookSeriesCharacter.name)
    )
    return list(result.scalars().all())


async def get_sibling_series_characters(
    db: AsyncSession, series_name: str, current_book_id: int
) -> list[AudiobookSeriesCharacter]:
    """Return profiles backed by another book, excluding current-book-only guesses."""
    linked_profile_ids = select(AudiobookCharacter.series_character_id).where(
        AudiobookCharacter.book_id != current_book_id,
        AudiobookCharacter.series_character_id.is_not(None),
    )
    result = await db.execute(
        select(AudiobookSeriesCharacter)
        .where(
            func.lower(AudiobookSeriesCharacter.series_name) == series_name.lower(),
            AudiobookSeriesCharacter.id.in_(linked_profile_ids),
        )
        .order_by(AudiobookSeriesCharacter.is_narrator.desc(), AudiobookSeriesCharacter.name)
    )
    return list(result.scalars().all())


async def delete_orphaned_series_characters(db: AsyncSession, series_name: str) -> int:
    """Remove stale profiles left behind by an explicit roster refresh."""
    linked_profile_ids = select(AudiobookCharacter.series_character_id).where(
        AudiobookCharacter.series_character_id.is_not(None)
    )
    result = await db.execute(
        delete(AudiobookSeriesCharacter).where(
            func.lower(AudiobookSeriesCharacter.series_name) == series_name.lower(),
            AudiobookSeriesCharacter.id.not_in(linked_profile_ids),
        )
    )
    await db.commit()
    return result.rowcount or 0


def _copy_series_profile_to_book_character(
    profile: AudiobookSeriesCharacter,
    character: AudiobookCharacter,
) -> None:
    character.series_character_id = profile.id
    character.name = profile.name
    character.description = profile.description
    character.voice_design_prompt = profile.voice_design_prompt
    character.is_narrator = profile.is_narrator
    character.aliases = profile.aliases or []
    character.evidence = profile.evidence or []


async def sync_book_roster_with_series(
    db: AsyncSession,
    book: Book,
    characters: list[AudiobookCharacter],
    *,
    prefer_series: bool = True,
) -> int:
    """Link a book roster to durable series profiles without changing sentence IDs."""
    if not book.series:
        return 0

    profiles = await get_series_characters(db, book.series)
    by_name = {profile.canonical_name: profile for profile in profiles}
    refreshed_profiles: dict[int, AudiobookSeriesCharacter] = {}
    voice_changed_profiles: set[int] = set()
    linked = 0
    for character in characters:
        canonical = _canonical_character_name(character.name)
        profile = by_name.get(canonical)
        if profile is None:
            profile = AudiobookSeriesCharacter(
                series_name=book.series,
                canonical_name=canonical,
                name=character.name,
                description=character.description,
                voice_design_prompt=character.voice_design_prompt,
                is_narrator=character.is_narrator,
                aliases=character.aliases or [],
                evidence=character.evidence or [],
            )
            db.add(profile)
            await db.flush()
            by_name[canonical] = profile
        elif prefer_series:
            _copy_series_profile_to_book_character(profile, character)
        else:
            # An explicit roster rebuild refreshes shared analysis while
            # retaining the established cross-book voice unless it was empty.
            profile.name = character.name
            profile.description = character.description
            profile.aliases = character.aliases or []
            profile.evidence = character.evidence or []
            profile.is_narrator = character.is_narrator
            if character.voice_design_prompt and profile.voice_design_prompt != character.voice_design_prompt:
                profile.voice_design_prompt = character.voice_design_prompt
                voice_changed_profiles.add(profile.id)
            refreshed_profiles[profile.id] = profile
        character.series_character_id = profile.id
        linked += 1

    changed_voice_character_ids: list[int] = []
    if refreshed_profiles:
        result = await db.execute(
            select(AudiobookCharacter).where(AudiobookCharacter.series_character_id.in_(list(refreshed_profiles)))
        )
        for linked_character in result.scalars().all():
            _copy_series_profile_to_book_character(
                refreshed_profiles[linked_character.series_character_id],
                linked_character,
            )
            if linked_character.series_character_id in voice_changed_profiles:
                changed_voice_character_ids.append(linked_character.id)

    await db.commit()
    for character_id in changed_voice_character_ids:
        await cascade_voice_change(db, character_id)
    return linked


async def unlink_book_roster_from_series(db: AsyncSession, book_id: int) -> None:
    """Detach book-local characters when a book is removed from a series."""
    await db.execute(update(AudiobookCharacter).where(AudiobookCharacter.book_id == book_id).values(series_character_id=None))
    await db.commit()


async def propagate_character_profile_across_series(
    db: AsyncSession,
    character: AudiobookCharacter,
) -> list[AudiobookCharacter]:
    """Promote an edited character and update matching profiles in sibling books."""
    book = await db.get(Book, character.book_id)
    if book is None or not book.series:
        return [character]

    linked_profile = (
        await db.get(AudiobookSeriesCharacter, character.series_character_id) if character.series_character_id else None
    )
    canonical = _canonical_character_name(character.name)
    result = await db.execute(
        select(AudiobookSeriesCharacter).where(
            func.lower(AudiobookSeriesCharacter.series_name) == book.series.lower(),
            AudiobookSeriesCharacter.canonical_name == canonical,
        )
    )
    matching_profile = result.scalar_one_or_none()
    profile = matching_profile or linked_profile
    if matching_profile is not None and linked_profile is not None and matching_profile.id != linked_profile.id:
        await db.execute(
            update(AudiobookCharacter)
            .where(AudiobookCharacter.series_character_id == linked_profile.id)
            .values(series_character_id=matching_profile.id)
        )
        await db.delete(linked_profile)
        await db.flush()
    if profile is None:
        profile = AudiobookSeriesCharacter(series_name=book.series, canonical_name=canonical, name=character.name)
        db.add(profile)
        await db.flush()

    profile.canonical_name = canonical
    profile.name = character.name
    profile.description = character.description
    profile.voice_design_prompt = character.voice_design_prompt
    profile.is_narrator = character.is_narrator
    profile.aliases = character.aliases or []
    profile.evidence = character.evidence or []

    result = await db.execute(
        select(AudiobookCharacter)
        .join(Book, Book.id == AudiobookCharacter.book_id)
        .where(
            func.lower(Book.series) == book.series.lower(),
            or_(
                AudiobookCharacter.series_character_id == profile.id,
                func.lower(AudiobookCharacter.name) == character.name.lower(),
            ),
        )
    )
    matching = list(result.scalars().all())
    if character not in matching:
        matching.append(character)
    for sibling in matching:
        _copy_series_profile_to_book_character(profile, sibling)
    await db.commit()
    return matching


async def cascade_voice_change(db: AsyncSession, char_id: int) -> None:
    """Reset audio for all sentences by this character and flag affected chapters."""
    await db.execute(
        update(AudiobookSentence)
        .where(AudiobookSentence.character_id == char_id)
        .values(status="ready_for_audio", audio_file_path=None, audio_duration_ms=None)
    )
    result = await db.execute(select(AudiobookSentence.chapter_id).where(AudiobookSentence.character_id == char_id).distinct())
    chapter_ids = [row[0] for row in result.all()]
    if chapter_ids:
        await db.execute(
            update(AudiobookChapter)
            .where(AudiobookChapter.id.in_(chapter_ids))
            .values(needs_reassembly=True, preview_status=None, preview_error=None)
        )
    await db.commit()


async def delete_characters_for_book(db: AsyncSession, book_id: int) -> None:
    chars = await get_characters_for_book(db, book_id)
    for c in chars:
        await db.delete(c)
    await db.commit()


async def reset_roster_and_diarization_for_book(db: AsyncSession, book_id: int) -> None:
    """Clear derived speaker analysis while preserving the expensive EPUB ingestion."""
    chapter_ids = select(AudiobookChapter.id).where(AudiobookChapter.book_id == book_id)
    await db.execute(
        update(AudiobookSentence)
        .where(AudiobookSentence.chapter_id.in_(chapter_ids))
        .values(
            character_id=None,
            tagged_text=AudiobookSentence.original_text,
            audio_file_path=None,
            audio_duration_ms=None,
            speaker_confidence=None,
            speaker_reason=None,
            status="pending_diarization",
        )
    )
    await db.execute(
        update(AudiobookChapter)
        .where(AudiobookChapter.book_id == book_id)
        .values(
            summary=None,
            summary_updated_at=None,
            needs_reassembly=True,
            preview_status=None,
            preview_error=None,
        )
    )
    await db.commit()
    await delete_characters_for_book(db, book_id)


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------


async def create_sentences_bulk(db: AsyncSession, chapter_id: int, sentences_data: list[dict]) -> int:
    sentences = [AudiobookSentence(chapter_id=chapter_id, **s) for s in sentences_data]
    db.add_all(sentences)
    await db.commit()
    return len(sentences)


async def get_sentences_for_chapter(db: AsyncSession, chapter_id: int) -> list[AudiobookSentence]:
    result = await db.execute(
        select(AudiobookSentence).where(AudiobookSentence.chapter_id == chapter_id).order_by(AudiobookSentence.sequence_order)
    )
    return list(result.scalars().all())


async def get_sentences_paginated(
    db: AsyncSession,
    book_id: int,
    page: int = 1,
    limit: int = 50,
    chapter_id: Optional[int] = None,
    review_only: bool = False,
) -> tuple[list[AudiobookSentence], int]:
    base_query = (
        select(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(AudiobookChapter.book_id == book_id)
    )
    count_query = (
        select(func.count())
        .select_from(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(AudiobookChapter.book_id == book_id)
    )
    if chapter_id is not None:
        base_query = base_query.where(AudiobookSentence.chapter_id == chapter_id)
        count_query = count_query.where(AudiobookSentence.chapter_id == chapter_id)
    if review_only:
        review_filter = and_(
            AudiobookSentence.status != "pending_diarization",
            or_(
                AudiobookSentence.character_id.is_(None),
                AudiobookSentence.speaker_confidence.is_(None),
                AudiobookSentence.speaker_confidence < 0.65,
            ),
        )
        base_query = base_query.where(review_filter)
        count_query = count_query.where(review_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    result = await db.execute(
        base_query.order_by(AudiobookChapter.chapter_number, AudiobookSentence.sequence_order)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_sentences_pending_diarization(
    db: AsyncSession,
    book_id: int,
    limit: int = 50,
    chapter_id: Optional[int] = None,
) -> list[AudiobookSentence]:
    query = (
        select(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(
            AudiobookChapter.book_id == book_id,
            AudiobookSentence.status == "pending_diarization",
        )
        .order_by(AudiobookChapter.chapter_number, AudiobookSentence.sequence_order)
        .limit(limit)
    )
    if chapter_id is not None:
        query = query.where(AudiobookSentence.chapter_id == chapter_id)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_sentences_ready_for_audio(db: AsyncSession, book_id: int, limit: int = 20) -> list[AudiobookSentence]:
    result = await db.execute(
        select(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(
            AudiobookChapter.book_id == book_id,
            AudiobookSentence.status == "ready_for_audio",
        )
        .order_by(AudiobookChapter.chapter_number, AudiobookSentence.sequence_order)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_pending_sentence_audio_jobs(db: AsyncSession) -> list[tuple[int, int]]:
    """Return durable manual sentence jobs as (book_id, sentence_id)."""
    result = await db.execute(
        select(AudiobookChapter.book_id, AudiobookSentence.id)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(AudiobookSentence.status.in_(["audio_queued", "audio_generating"]))
        .order_by(AudiobookSentence.id)
    )
    return [(book_id, sentence_id) for book_id, sentence_id in result.all()]


async def set_sentence_status(db: AsyncSession, sentence_id: int, status: str) -> None:
    await db.execute(update(AudiobookSentence).where(AudiobookSentence.id == sentence_id).values(status=status))
    await db.commit()


async def update_sentence_diarization(
    db: AsyncSession,
    sentence_id: int,
    character_id: Optional[int],
    tagged_text: str,
    speaker_confidence: Optional[float] = None,
    speaker_reason: Optional[str] = None,
) -> None:
    await db.execute(
        update(AudiobookSentence)
        .where(AudiobookSentence.id == sentence_id)
        .values(
            character_id=character_id,
            tagged_text=tagged_text,
            speaker_confidence=speaker_confidence,
            speaker_reason=speaker_reason,
            status="ready_for_audio",
        )
    )
    await db.commit()


async def update_sentence_audio(db: AsyncSession, sentence_id: int, audio_file_path: str, audio_duration_ms: int) -> None:
    await db.execute(
        update(AudiobookSentence)
        .where(AudiobookSentence.id == sentence_id)
        .values(audio_file_path=audio_file_path, audio_duration_ms=audio_duration_ms, status="audio_generated")
    )
    await db.commit()


async def mark_sentence_error(db: AsyncSession, sentence_id: int) -> None:
    await db.execute(update(AudiobookSentence).where(AudiobookSentence.id == sentence_id).values(status="error"))
    await db.commit()


async def reset_error_sentences_for_book(db: AsyncSession, book_id: int) -> int:
    chapter_ids = select(AudiobookChapter.id).where(AudiobookChapter.book_id == book_id)
    result = await db.execute(
        update(AudiobookSentence)
        .where(
            AudiobookSentence.chapter_id.in_(chapter_ids),
            AudiobookSentence.status == "error",
        )
        .values(status="ready_for_audio", audio_file_path=None, audio_duration_ms=None)
    )
    await db.execute(update(AudiobookChapter).where(AudiobookChapter.book_id == book_id).values(needs_reassembly=True))
    await db.commit()
    return result.rowcount or 0


async def update_sentence_speaker(
    db: AsyncSession, sentence_id: int, character_id: Optional[int], tagged_text: str
) -> Optional[AudiobookSentence]:
    """Update sentence speaker/tags and cascade invalidation to the parent chapter."""
    sentence = await db.get(AudiobookSentence, sentence_id)
    if sentence is None:
        return None
    sentence.character_id = character_id
    sentence.tagged_text = tagged_text
    sentence.speaker_confidence = 1.0
    sentence.speaker_reason = "Manually assigned"
    sentence.status = "ready_for_audio"
    sentence.audio_file_path = None
    sentence.audio_duration_ms = None
    await db.execute(
        update(AudiobookChapter)
        .where(AudiobookChapter.id == sentence.chapter_id)
        .values(needs_reassembly=True, preview_status=None, preview_error=None)
    )
    await db.commit()
    await db.refresh(sentence)
    return sentence


async def count_sentences_by_status(db: AsyncSession, book_id: int) -> dict[str, int]:
    result = await db.execute(
        select(AudiobookSentence.status, func.count())
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(AudiobookChapter.book_id == book_id)
        .group_by(AudiobookSentence.status)
    )
    return {row[0]: row[1] for row in result.all()}


async def count_sentence_review_flags(db: AsyncSession, book_id: int) -> dict[str, int]:
    base = (
        select(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(AudiobookChapter.book_id == book_id)
        .subquery()
    )
    result = await db.execute(
        select(
            func.count().filter(base.c.character_id.is_(None)),
            func.count().filter(base.c.speaker_confidence < 0.65),
            func.count().filter(base.c.speaker_confidence.is_not(None)),
        ).select_from(base)
    )
    unassigned, low_confidence, reviewed = result.one()
    return {
        "unassigned": unassigned or 0,
        "low_confidence": low_confidence or 0,
        "with_confidence": reviewed or 0,
    }


async def get_character_sentence_stats(db: AsyncSession, book_id: int) -> dict[int, dict[str, float | int | None]]:
    result = await db.execute(
        select(
            AudiobookSentence.character_id,
            func.count(),
            func.avg(AudiobookSentence.speaker_confidence),
        )
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(AudiobookChapter.book_id == book_id, AudiobookSentence.character_id.is_not(None))
        .group_by(AudiobookSentence.character_id)
    )
    return {
        character_id: {
            "sentence_count": sentence_count,
            "average_confidence": float(average_confidence) if average_confidence is not None else None,
        }
        for character_id, sentence_count, average_confidence in result.all()
    }


async def has_sentence_status(db: AsyncSession, book_id: int, statuses: str | list[str]) -> bool:
    status_values = [statuses] if isinstance(statuses, str) else statuses
    result = await db.execute(
        select(func.count())
        .select_from(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(
            AudiobookChapter.book_id == book_id,
            AudiobookSentence.status.in_(status_values),
        )
    )
    return result.scalar_one() > 0


async def get_book_pipeline_status(db: AsyncSession, book_id: int) -> Optional[str]:
    result = await db.execute(select(Book.audiobook_pipeline_status).where(Book.id == book_id))
    return result.scalar_one_or_none()


async def infer_audiobook_resume_status(db: AsyncSession, book_id: int) -> str:
    """Infer the earliest safe phase from durable chapter/sentence state."""
    chapters = await get_chapters_for_book(db, book_id)
    if not chapters:
        return "ingesting"

    characters = await get_characters_for_book(db, book_id)
    if not characters:
        return "roster_gen"

    counts = await count_sentences_by_status(db, book_id)
    if counts.get("pending_diarization", 0) > 0:
        return "diarizing"
    if any(counts.get(status, 0) > 0 for status in ("ready_for_audio", "audio_queued", "audio_generating", "error")):
        return "audio_gen"

    total = sum(counts.values())
    if total > 0 and counts.get("audio_generated", 0) == total:
        pending_chapters = await get_chapters_pending_assembly(db, book_id)
        return "assembling" if pending_chapters else "complete"

    return "ingesting"


async def chapter_all_audio_generated(db: AsyncSession, chapter_id: int) -> bool:
    result = await db.execute(
        select(func.count(), func.count().filter(AudiobookSentence.status != "audio_generated"))
        .select_from(AudiobookSentence)
        .where(AudiobookSentence.chapter_id == chapter_id)
    )
    total, pending = result.one()
    return total > 0 and pending == 0


async def all_sentences_audio_generated(db: AsyncSession, book_id: int) -> bool:
    result = await db.execute(
        select(func.count(), func.count().filter(AudiobookSentence.status != "audio_generated"))
        .select_from(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(AudiobookChapter.book_id == book_id)
    )
    total, pending = result.one()
    return total > 0 and pending == 0
