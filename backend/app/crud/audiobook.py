"""CRUD operations for the audiobook pipeline tables."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

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


async def get_in_progress_audiobook_books(db: AsyncSession) -> list[Book]:
    active_statuses = ["ingesting", "roster_gen", "diarizing", "audio_gen", "assembling"]
    result = await db.execute(select(Book).where(Book.audiobook_pipeline_status.in_(active_statuses)))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------


async def create_chapter(db: AsyncSession, book_id: int, chapter_number: int) -> AudiobookChapter:
    chapter = AudiobookChapter(book_id=book_id, chapter_number=chapter_number)
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


async def chapter_all_audio_generated(db: AsyncSession, chapter_id: int) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(AudiobookSentence)
        .where(
            AudiobookSentence.chapter_id == chapter_id,
            AudiobookSentence.status != "audio_generated",
        )
    )
    return result.scalar_one() == 0


async def all_sentences_audio_generated(db: AsyncSession, book_id: int) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(AudiobookSentence)
        .join(AudiobookChapter, AudiobookSentence.chapter_id == AudiobookChapter.id)
        .where(
            AudiobookChapter.book_id == book_id,
            AudiobookSentence.status != "audio_generated",
        )
    )
    return result.scalar_one() == 0
