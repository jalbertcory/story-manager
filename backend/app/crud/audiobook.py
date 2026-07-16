"""CRUD operations for the audiobook pipeline tables."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import LIBRARY_PATH
from ..models import AudiobookSettings, AudiobookChapter, AudiobookCharacter, AudiobookSentence, Book

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
    await db.execute(update(Book).where(Book.id == book_id).values(audiobook_pipeline_status=status))
    await db.commit()


async def configure_book_pipeline_run(
    db: AsyncSession,
    book_id: int,
    *,
    status: str,
    stop_after_phase: Optional[str],
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
        )
    )
    await db.commit()


async def request_book_pipeline_pause(db: AsyncSession, book_id: int) -> None:
    await db.execute(update(Book).where(Book.id == book_id).values(audiobook_pause_requested=True))
    await db.commit()


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
    if row is None or row.audiobook_stop_after_phase != phase or row.audiobook_pipeline_status == "complete":
        return False
    await db.execute(
        update(Book).where(Book.id == book_id).values(audiobook_pipeline_status="paused", audiobook_stop_after_phase=None)
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


async def flag_chapter_for_reassembly(db: AsyncSession, chapter_id: int) -> None:
    await db.execute(update(AudiobookChapter).where(AudiobookChapter.id == chapter_id).values(needs_reassembly=True))
    await db.commit()


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
        await db.execute(update(AudiobookChapter).where(AudiobookChapter.id.in_(chapter_ids)).values(needs_reassembly=True))
    await db.commit()


async def delete_characters_for_book(db: AsyncSession, book_id: int) -> None:
    chars = await get_characters_for_book(db, book_id)
    for c in chars:
        await db.delete(c)
    await db.commit()


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

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    result = await db.execute(
        base_query.order_by(AudiobookChapter.chapter_number, AudiobookSentence.sequence_order)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_sentences_pending_diarization(db: AsyncSession, book_id: int, limit: int = 50) -> list[AudiobookSentence]:
    result = await db.execute(
        select(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(
            AudiobookChapter.book_id == book_id,
            AudiobookSentence.status == "pending_diarization",
        )
        .order_by(AudiobookChapter.chapter_number, AudiobookSentence.sequence_order)
        .limit(limit)
    )
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


async def update_sentence_diarization(
    db: AsyncSession, sentence_id: int, character_id: Optional[int], tagged_text: str
) -> None:
    await db.execute(
        update(AudiobookSentence)
        .where(AudiobookSentence.id == sentence_id)
        .values(character_id=character_id, tagged_text=tagged_text, status="ready_for_audio")
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
    sentence.status = "ready_for_audio"
    sentence.audio_file_path = None
    sentence.audio_duration_ms = None
    await db.execute(update(AudiobookChapter).where(AudiobookChapter.id == sentence.chapter_id).values(needs_reassembly=True))
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
    if counts.get("ready_for_audio", 0) > 0 or counts.get("error", 0) > 0:
        return "audio_gen"

    total = sum(counts.values())
    if total > 0 and counts.get("audio_generated", 0) == total:
        pending_chapters = await get_chapters_pending_assembly(db, book_id)
        packaged_epub = LIBRARY_PATH / "audiobooks" / str(book_id) / "audiobook.epub"
        return "assembling" if pending_chapters or not packaged_epub.is_file() else "complete"

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
