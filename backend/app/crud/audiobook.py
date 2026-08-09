"""CRUD operations for the audiobook pipeline tables."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AUDIOBOOK_ASSEMBLY_MARKER, LIBRARY_PATH
from ..lifecycle import (
    AUDIOBOOK_PIPELINE,
    CHAPTER_PREVIEW,
    SENTENCE,
    AudiobookPipelineStatus,
    ChapterGenerationStatus,
    SentenceStatus,
    transition_state,
)
from ..models import (
    AudiobookSettings,
    AudiobookChapter,
    AudiobookCharacter,
    AudiobookSeriesCharacter,
    AudiobookSentence,
    Book,
    ImportedAudiobook,
)


async def get_human_audiobook_book_ids(db: AsyncSession, book_ids: list[int]) -> set[int]:
    """Return books that have at least one attached human-narrated edition."""
    if not book_ids:
        return set()
    result = await db.execute(select(ImportedAudiobook.book_id).where(ImportedAudiobook.book_id.in_(book_ids)).distinct())
    return set(result.scalars().all())


async def invalidate_packaged_audiobook(db: AsyncSession, book_id: int) -> None:
    """Remove a stale EPUB package and make a completed book resumable."""
    packaged_epub = LIBRARY_PATH / "audiobooks" / str(book_id) / "audiobook.epub"
    packaged_epub.unlink(missing_ok=True)
    await db.execute(
        update(Book)
        .where(Book.id == book_id, Book.audiobook_pipeline_status == AudiobookPipelineStatus.COMPLETE.value)
        .values(
            audiobook_pipeline_status=AudiobookPipelineStatus.PAUSED.value,
            audiobook_pipeline_updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()


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
    book = await db.get(Book, book_id)
    if book is None:
        return
    transition_state(book, "audiobook_pipeline_status", AUDIOBOOK_PIPELINE, status, context=f"book {book_id}")
    book.audiobook_pipeline_updated_at = datetime.now(timezone.utc)
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
    book = await db.get(Book, book_id)
    if book is None:
        return
    transition_state(book, "audiobook_pipeline_status", AUDIOBOOK_PIPELINE, status, context=f"book {book_id}")
    book.audiobook_stop_after_phase = stop_after_phase
    book.audiobook_pause_requested = False
    book.audiobook_last_error = None
    book.audiobook_batch_limit = batch_limit
    book.audiobook_progress_current = 0
    book.audiobook_progress_total = 0
    book.audiobook_progress_detail = None
    book.audiobook_pipeline_started_at = datetime.now(timezone.utc)
    book.audiobook_pipeline_updated_at = datetime.now(timezone.utc)
    book.audiobook_llm_requests = 0
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
    book = await db.get(Book, book_id)
    if book is None or book.audiobook_batch_limit is None:
        return False
    remaining = book.audiobook_batch_limit - 1
    if remaining > 0:
        await db.execute(update(Book).where(Book.id == book_id).values(audiobook_batch_limit=remaining))
        await db.commit()
        return False
    transition_state(
        book,
        "audiobook_pipeline_status",
        AUDIOBOOK_PIPELINE,
        AudiobookPipelineStatus.PAUSED,
        context=f"book {book_id}",
    )
    book.audiobook_batch_limit = None
    book.audiobook_stop_after_phase = None
    book.audiobook_pause_requested = False
    book.audiobook_pipeline_updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def pause_book_pipeline_if_requested(db: AsyncSession, book_id: int) -> bool:
    """Acknowledge a cooperative pause request at a durable work boundary."""
    book = await db.get(Book, book_id)
    if book is None or not book.audiobook_pause_requested:
        return False
    transition_state(
        book,
        "audiobook_pipeline_status",
        AUDIOBOOK_PIPELINE,
        AudiobookPipelineStatus.PAUSED,
        context=f"book {book_id}",
    )
    book.audiobook_pause_requested = False
    book.audiobook_stop_after_phase = None
    book.audiobook_batch_limit = None
    book.audiobook_pipeline_updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def pause_book_pipeline_after_phase(db: AsyncSession, book_id: int, phase: str) -> bool:
    """Stop a single-stage run once its requested phase has committed."""
    book = await db.get(Book, book_id)
    if (
        book is None
        or book.audiobook_stop_after_phase != phase
        or book.audiobook_pipeline_status == AudiobookPipelineStatus.COMPLETE.value
    ):
        return False
    transition_state(
        book,
        "audiobook_pipeline_status",
        AUDIOBOOK_PIPELINE,
        AudiobookPipelineStatus.PAUSED,
        context=f"book {book_id}",
    )
    book.audiobook_stop_after_phase = None
    book.audiobook_batch_limit = None
    book.audiobook_pipeline_updated_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def set_book_pipeline_error(db: AsyncSession, book_id: int, message: str) -> None:
    book = await db.get(Book, book_id)
    if book is None:
        return
    transition_state(
        book,
        "audiobook_pipeline_status",
        AUDIOBOOK_PIPELINE,
        AudiobookPipelineStatus.ERROR,
        context=f"book {book_id}",
    )
    book.audiobook_pause_requested = False
    book.audiobook_stop_after_phase = None
    book.audiobook_batch_limit = None
    book.audiobook_pipeline_updated_at = datetime.now(timezone.utc)
    book.audiobook_last_error = message
    await db.commit()


async def get_in_progress_audiobook_books(db: AsyncSession) -> list[Book]:
    active_statuses = tuple(AUDIOBOOK_PIPELINE.active_states)
    result = await db.execute(
        select(Book).where(
            Book.audiobook_enabled.is_(True),
            or_(
                Book.audiobook_pipeline_status.in_(active_statuses),
                and_(
                    Book.audiobook_pending_content_version.is_not(None),
                    or_(
                        Book.audiobook_source_content_version.is_(None),
                        Book.audiobook_pending_content_version > Book.audiobook_source_content_version,
                    ),
                ),
            ),
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


async def get_chapters_for_books(db: AsyncSession, book_ids: list[int]) -> dict[int, list[AudiobookChapter]]:
    if not book_ids:
        return {}
    result = await db.execute(
        select(AudiobookChapter)
        .where(AudiobookChapter.book_id.in_(book_ids))
        .order_by(
            AudiobookChapter.book_id,
            AudiobookChapter.spine_order,
            AudiobookChapter.chapter_number,
        )
    )
    grouped: dict[int, list[AudiobookChapter]] = {book_id: [] for book_id in book_ids}
    for chapter in result.scalars().all():
        grouped.setdefault(chapter.book_id, []).append(chapter)
    return grouped


async def get_chapter_by_stable_key(db: AsyncSession, book_id: int, stable_chapter_key: str) -> Optional[AudiobookChapter]:
    result = await db.execute(
        select(AudiobookChapter).where(
            AudiobookChapter.book_id == book_id,
            AudiobookChapter.stable_chapter_key == stable_chapter_key,
        )
    )
    return result.scalar_one_or_none()


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
    result = await db.execute(select(AudiobookChapter.book_id).where(AudiobookChapter.id == chapter_id))
    book_id = result.scalar_one_or_none()
    await db.execute(
        update(AudiobookChapter)
        .where(AudiobookChapter.id == chapter_id)
        .values(needs_reassembly=True, preview_status=None, preview_error=None)
    )
    await db.commit()
    if book_id is not None:
        await invalidate_packaged_audiobook(db, book_id)


async def set_chapter_preview_status(
    db: AsyncSession,
    chapter_id: int,
    status: Optional[str],
    error: Optional[str] = None,
) -> None:
    chapter = await db.get(AudiobookChapter, chapter_id)
    if chapter is None:
        return
    transition_state(chapter, "preview_status", CHAPTER_PREVIEW, status, context=f"audiobook chapter {chapter_id}")
    chapter.preview_error = error
    await db.commit()


async def get_chapters_with_pending_previews(db: AsyncSession) -> list[AudiobookChapter]:
    result = await db.execute(
        select(AudiobookChapter).where(AudiobookChapter.preview_status.in_(tuple(CHAPTER_PREVIEW.active_states)))
    )
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


def _copy_series_profile_to_book_character(
    profile: AudiobookSeriesCharacter,
    character: AudiobookCharacter,
) -> None:
    character.series_character_id = profile.id
    character.name = profile.name
    character.description = profile.description
    character.voice_prompt = profile.voice_prompt
    character.tts_voice_id = profile.tts_voice_id
    character.tts_voice_provider = profile.tts_voice_provider
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
                voice_prompt=character.voice_prompt,
                tts_voice_id=character.tts_voice_id,
                tts_voice_provider=character.tts_voice_provider,
                is_narrator=character.is_narrator,
                aliases=character.aliases or [],
                evidence=character.evidence or [],
            )
            db.add(profile)
            await db.flush()
            by_name[canonical] = profile
        elif prefer_series:
            _copy_series_profile_to_book_character(profile, character)
        character.series_character_id = profile.id
        linked += 1

    await db.commit()
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
    profile.voice_prompt = character.voice_prompt
    profile.tts_voice_id = character.tts_voice_id
    profile.tts_voice_provider = character.tts_voice_provider
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
        .values(status=SentenceStatus.READY_FOR_AUDIO.value, audio_file_path=None, audio_duration_ms=None)
    )
    result = await db.execute(select(AudiobookSentence.chapter_id).where(AudiobookSentence.character_id == char_id).distinct())
    chapter_ids = [row[0] for row in result.all()]
    book_ids: list[int] = []
    if chapter_ids:
        result = await db.execute(select(AudiobookChapter.book_id).where(AudiobookChapter.id.in_(chapter_ids)).distinct())
        book_ids = [row[0] for row in result.all()]
        await db.execute(
            update(AudiobookChapter)
            .where(AudiobookChapter.id.in_(chapter_ids))
            .values(needs_reassembly=True, preview_status=None, preview_error=None)
        )
    await db.commit()
    for book_id in book_ids:
        await invalidate_packaged_audiobook(db, book_id)


async def invalidate_generated_audio_for_tts_change(
    db: AsyncSession,
    *,
    completion_threshold: float = 0.8,
) -> list[int]:
    """Reset generated clips only for unfinished books below the threshold."""
    result = await db.execute(
        select(
            Book.id,
            func.count(AudiobookSentence.id),
            func.count(AudiobookSentence.id).filter(AudiobookSentence.status == SentenceStatus.AUDIO_GENERATED.value),
        )
        .join(AudiobookChapter, AudiobookChapter.book_id == Book.id)
        .join(AudiobookSentence, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(
            Book.audiobook_enabled.is_(True),
            or_(
                Book.audiobook_pipeline_status.is_(None),
                Book.audiobook_pipeline_status != AudiobookPipelineStatus.COMPLETE.value,
            ),
        )
        .group_by(Book.id)
    )
    book_ids = [
        book_id
        for book_id, total, generated in result.all()
        if generated and total and generated / total < completion_threshold
    ]
    if not book_ids:
        return []

    chapter_result = await db.execute(
        select(AudiobookSentence.chapter_id)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(
            AudiobookChapter.book_id.in_(book_ids),
            AudiobookSentence.status == SentenceStatus.AUDIO_GENERATED.value,
        )
        .distinct()
    )
    chapter_ids = [chapter_id for (chapter_id,) in chapter_result.all()]

    await db.execute(
        update(AudiobookSentence)
        .where(
            AudiobookSentence.chapter_id.in_(chapter_ids),
            AudiobookSentence.status == SentenceStatus.AUDIO_GENERATED.value,
        )
        .values(status=SentenceStatus.READY_FOR_AUDIO.value, audio_file_path=None, audio_duration_ms=None)
    )
    if chapter_ids:
        await db.execute(
            update(AudiobookChapter)
            .where(AudiobookChapter.id.in_(chapter_ids))
            .values(needs_reassembly=True, preview_status=None, preview_error=None)
        )
    await db.commit()
    for book_id in book_ids:
        await invalidate_packaged_audiobook(db, book_id)
    return book_ids


async def delete_characters_for_book(db: AsyncSession, book_id: int) -> None:
    chars = await get_characters_for_book(db, book_id)
    for c in chars:
        await db.delete(c)
    await db.commit()


async def reset_roster_and_diarization_for_book(db: AsyncSession, book_id: int) -> None:
    """Clear AI analysis/audio while preserving ingestion and human audiobook cues."""
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
            status=SentenceStatus.PENDING_DIARIZATION.value,
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
            audio_file_path=None,
            smil_file_path=None,
            reader_audio_file_path=None,
            reader_smil_file_path=None,
            audio_size_bytes=None,
            audio_sha256=None,
            smil_size_bytes=None,
            smil_sha256=None,
            duration_ms=None,
            generation_state=ChapterGenerationStatus.PENDING.value,
        )
    )
    await db.commit()
    await invalidate_packaged_audiobook(db, book_id)
    await delete_characters_for_book(db, book_id)


async def reset_audio_generation_for_book(db: AsyncSession, book_id: int) -> int:
    """Clear only AI TTS/assembly output, preserving speakers and human cues."""
    chapter_ids = select(AudiobookChapter.id).where(AudiobookChapter.book_id == book_id)
    result = await db.execute(
        update(AudiobookSentence)
        .where(AudiobookSentence.chapter_id.in_(chapter_ids))
        .values(
            audio_file_path=None,
            audio_duration_ms=None,
            status=SentenceStatus.READY_FOR_AUDIO.value,
        )
    )
    await db.execute(
        update(AudiobookChapter)
        .where(AudiobookChapter.book_id == book_id)
        .values(
            needs_reassembly=True,
            preview_status=None,
            preview_error=None,
            audio_file_path=None,
            smil_file_path=None,
            reader_audio_file_path=None,
            reader_smil_file_path=None,
            audio_size_bytes=None,
            audio_sha256=None,
            smil_size_bytes=None,
            smil_sha256=None,
            duration_ms=None,
            generation_state=ChapterGenerationStatus.PENDING.value,
        )
    )
    await db.commit()
    await invalidate_packaged_audiobook(db, book_id)
    return result.rowcount or 0


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
            AudiobookSentence.status != SentenceStatus.PENDING_DIARIZATION.value,
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
            AudiobookSentence.status == SentenceStatus.PENDING_DIARIZATION.value,
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
            AudiobookSentence.status == SentenceStatus.READY_FOR_AUDIO.value,
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
        .where(AudiobookSentence.status.in_((SentenceStatus.AUDIO_QUEUED.value, SentenceStatus.AUDIO_GENERATING.value)))
        .order_by(AudiobookSentence.id)
    )
    return [(book_id, sentence_id) for book_id, sentence_id in result.all()]


async def set_sentence_status(db: AsyncSession, sentence_id: int, status: str) -> None:
    sentence = await db.get(AudiobookSentence, sentence_id)
    if sentence is None:
        return
    transition_state(sentence, "status", SENTENCE, status, context=f"audiobook sentence {sentence_id}")
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
            status=SentenceStatus.READY_FOR_AUDIO.value,
        )
    )
    await db.commit()


async def mark_sentences_as_narration(
    db: AsyncSession,
    sentence_ids: list[int],
    narrator_id: Optional[int],
) -> None:
    """Bulk-complete sentences known to be prose outside a dialogue span."""
    if not sentence_ids:
        return
    await db.execute(
        update(AudiobookSentence)
        .where(
            AudiobookSentence.id.in_(sentence_ids),
            AudiobookSentence.status == SentenceStatus.PENDING_DIARIZATION.value,
        )
        .values(
            character_id=narrator_id,
            tagged_text=AudiobookSentence.original_text,
            speaker_confidence=1.0,
            speaker_reason="Deterministic prose outside dialogue",
            status=SentenceStatus.READY_FOR_AUDIO.value,
        )
    )
    await db.commit()


async def update_sentence_audio(db: AsyncSession, sentence_id: int, audio_file_path: str, audio_duration_ms: int) -> None:
    await db.execute(
        update(AudiobookSentence)
        .where(AudiobookSentence.id == sentence_id)
        .values(
            audio_file_path=audio_file_path,
            audio_duration_ms=audio_duration_ms,
            status=SentenceStatus.AUDIO_GENERATED.value,
        )
    )
    await db.commit()


async def mark_sentence_error(db: AsyncSession, sentence_id: int) -> None:
    await set_sentence_status(db, sentence_id, SentenceStatus.ERROR.value)


async def reset_error_sentences_for_book(db: AsyncSession, book_id: int) -> int:
    chapter_ids = select(AudiobookChapter.id).where(AudiobookChapter.book_id == book_id)
    result = await db.execute(
        update(AudiobookSentence)
        .where(
            AudiobookSentence.chapter_id.in_(chapter_ids),
            AudiobookSentence.status == SentenceStatus.ERROR.value,
        )
        .values(status=SentenceStatus.READY_FOR_AUDIO.value, audio_file_path=None, audio_duration_ms=None)
    )
    await db.execute(update(AudiobookChapter).where(AudiobookChapter.book_id == book_id).values(needs_reassembly=True))
    await db.commit()
    return result.rowcount or 0


async def reset_interrupted_sentences_for_book(db: AsyncSession, book_id: int) -> int:
    """Reclaim speech clips whose in-memory worker disappeared during a restart."""
    chapter_ids = select(AudiobookChapter.id).where(AudiobookChapter.book_id == book_id)
    result = await db.execute(
        update(AudiobookSentence)
        .where(
            AudiobookSentence.chapter_id.in_(chapter_ids),
            AudiobookSentence.status.in_((SentenceStatus.AUDIO_QUEUED.value, SentenceStatus.AUDIO_GENERATING.value)),
        )
        .values(status=SentenceStatus.READY_FOR_AUDIO.value, audio_file_path=None, audio_duration_ms=None)
    )
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
    transition_state(
        sentence,
        "status",
        SENTENCE,
        SentenceStatus.READY_FOR_AUDIO,
        context=f"audiobook sentence {sentence_id}",
    )
    sentence.audio_file_path = None
    sentence.audio_duration_ms = None
    await db.execute(
        update(AudiobookChapter)
        .where(AudiobookChapter.id == sentence.chapter_id)
        .values(needs_reassembly=True, preview_status=None, preview_error=None)
    )
    await db.commit()
    chapter = await db.get(AudiobookChapter, sentence.chapter_id)
    if chapter is not None:
        await invalidate_packaged_audiobook(db, chapter.book_id)
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
        return AudiobookPipelineStatus.INGESTING.value

    characters = await get_characters_for_book(db, book_id)
    if not characters:
        return AudiobookPipelineStatus.ROSTER_GENERATION.value

    counts = await count_sentences_by_status(db, book_id)
    if counts.get(SentenceStatus.PENDING_DIARIZATION.value, 0) > 0:
        return AudiobookPipelineStatus.DIARIZING.value
    if any(
        counts.get(status, 0) > 0
        for status in (
            SentenceStatus.READY_FOR_AUDIO.value,
            SentenceStatus.AUDIO_QUEUED.value,
            SentenceStatus.AUDIO_GENERATING.value,
            SentenceStatus.ERROR.value,
        )
    ):
        return AudiobookPipelineStatus.AUDIO_GENERATION.value

    total = sum(counts.values())
    if total > 0 and counts.get(SentenceStatus.AUDIO_GENERATED.value, 0) == total:
        pending_chapters = await get_chapters_pending_assembly(db, book_id)
        output_dir = LIBRARY_PATH / "audiobooks" / str(book_id)
        packaged_epub = output_dir / "audiobook.epub"
        assembly_marker = output_dir / AUDIOBOOK_ASSEMBLY_MARKER
        return (
            AudiobookPipelineStatus.ASSEMBLING.value
            if pending_chapters or not packaged_epub.is_file() or not assembly_marker.is_file()
            else AudiobookPipelineStatus.COMPLETE.value
        )

    return AudiobookPipelineStatus.INGESTING.value


async def chapter_all_audio_generated(db: AsyncSession, chapter_id: int) -> bool:
    result = await db.execute(
        select(
            func.count(),
            func.count().filter(AudiobookSentence.status != SentenceStatus.AUDIO_GENERATED.value),
        )
        .select_from(AudiobookSentence)
        .where(AudiobookSentence.chapter_id == chapter_id)
    )
    total, pending = result.one()
    return total > 0 and pending == 0


async def all_sentences_audio_generated(db: AsyncSession, book_id: int) -> bool:
    result = await db.execute(
        select(
            func.count(),
            func.count().filter(AudiobookSentence.status != SentenceStatus.AUDIO_GENERATED.value),
        )
        .select_from(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(AudiobookChapter.book_id == book_id)
    )
    total, pending = result.one()
    return total > 0 and pending == 0
