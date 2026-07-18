"""Phase 4: provider-neutral TTS — generate a per-sentence MP3 snippet."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..models import AudiobookChapter, AudiobookCharacter, AudiobookSentence, AudiobookSettings
from .tts_providers import DEFAULT_VOICE_PROMPT, TTSRequest, synthesize_speech

logger = logging.getLogger(__name__)


def _snippet_path(book_id: int, sentence_id: int) -> Path:
    return LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id) / "snippets" / f"{sentence_id}.mp3"


def _relative_path(full_path: Path) -> str:
    return str(full_path.relative_to(LIBRARY_PATH.parent))


def _get_mp3_duration_ms(path: Path) -> int:
    from mutagen.mp3 import MP3

    audio = MP3(str(path))
    return int(audio.info.length * 1000)


async def _generate_sentence_clip(
    settings: AudiobookSettings | None,
    book_id: int,
    sentence: AudiobookSentence,
    db: AsyncSession,
) -> None:
    voice_prompt = DEFAULT_VOICE_PROMPT
    voice_id = None
    if sentence.character_id is not None:
        char = await db.get(AudiobookCharacter, sentence.character_id)
        if char:
            voice_prompt = char.voice_prompt or voice_prompt
            voice_id = char.tts_voice_id

    audio_bytes = await synthesize_speech(
        settings,
        TTSRequest(
            text=sentence.tagged_text or sentence.original_text,
            voice_prompt=voice_prompt,
            voice_id=voice_id,
        ),
    )
    out_path = _snippet_path(book_id, sentence.id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio_bytes)
    duration_ms = _get_mp3_duration_ms(out_path)
    await crud.audiobook.update_sentence_audio(
        db,
        sentence.id,
        _relative_path(out_path),
        duration_ms,
    )


async def generate_audio_for_sentence(
    book_id: int,
    sentence_id: int,
    db: AsyncSession,
) -> None:
    """Generate one manually requested sentence without advancing the book pipeline."""
    sentence = await db.get(AudiobookSentence, sentence_id)
    if sentence is None:
        raise RuntimeError("Audiobook sentence not found.")
    chapter = await db.get(AudiobookChapter, sentence.chapter_id)
    if chapter is None or chapter.book_id != book_id:
        raise RuntimeError("Audiobook sentence does not belong to this book.")
    if sentence.character_id is None:
        raise RuntimeError("Assign a speaker before generating sentence audio.")

    settings = await crud.audiobook.get_audiobook_settings(db)
    await _generate_sentence_clip(settings, book_id, sentence, db)
    await crud.audiobook.flag_chapter_for_reassembly(db, chapter.id)


async def generate_audio_for_book(book_id: int, db: AsyncSession) -> None:
    """Phase 4: iterate ready_for_audio sentences and call the configured TTS provider."""
    settings = await crud.audiobook.get_audiobook_settings(db)

    # Ensure snippets directory exists
    snippets_dir = LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id) / "snippets"
    snippets_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    failed = 0
    counts = await crud.audiobook.count_sentences_by_status(db, book_id)
    total = counts.get("ready_for_audio", 0)
    await crud.audiobook.update_book_pipeline_progress(
        db, book_id, current=0, total=total, detail=f"Preparing speech for {total} sentences"
    )
    while True:
        if await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
            logger.info("Book %s paused during TTS generation.", book_id)
            return

        batch = await crud.audiobook.get_sentences_ready_for_audio(db, book_id, limit=20)
        if not batch:
            break

        for sentence in batch:
            if await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
                logger.info("Book %s paused during TTS generation.", book_id)
                return

            logger.debug("Generating audio for sentence %s (book %s).", sentence.id, book_id)
            try:
                await _generate_sentence_clip(settings, book_id, sentence, db)
            except httpx.HTTPStatusError as exc:
                response_text = exc.response.text[:200] if exc.response is not None else ""
                logger.error(
                    "TTS provider error for sentence %s: %s %s",
                    sentence.id,
                    exc.response.status_code if exc.response is not None else "unknown",
                    response_text,
                )
                await crud.audiobook.mark_sentence_error(db, sentence.id)
                failed += 1
                continue
            except Exception as exc:
                logger.exception(
                    "Unable to generate or inspect audio for sentence %s: %s",
                    sentence.id,
                    exc,
                )
                await crud.audiobook.mark_sentence_error(db, sentence.id)
                failed += 1
                continue

            processed += 1
            await crud.audiobook.update_book_pipeline_progress(
                db,
                book_id,
                current=processed,
                total=total,
                detail=f"Generated speech for {processed} of {total} sentences",
            )

            # Flag chapter for reassembly if all its sentences are done
            if await crud.audiobook.chapter_all_audio_generated(db, sentence.chapter_id):
                await crud.audiobook.flag_chapter_for_reassembly(db, sentence.chapter_id)
            if await crud.audiobook.consume_book_batch_limit(db, book_id):
                logger.info("Book %s paused after one TTS sentence.", book_id)
                return

    if failed or await crud.audiobook.has_sentence_status(db, book_id, "error"):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "error")
        raise RuntimeError(f"TTS failed for {failed} sentence(s) in book {book_id}.")

    if not await crud.audiobook.all_sentences_audio_generated(db, book_id):
        await crud.audiobook.set_book_pipeline_status(db, book_id, "error")
        raise RuntimeError(f"TTS finished before all sentences had audio for book {book_id}.")

    if await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
        logger.info("Book %s paused after TTS generation.", book_id)
        return

    logger.info("TTS complete for book %s: %d sentences generated.", book_id, processed)
    await crud.audiobook.set_book_pipeline_status(db, book_id, "assembling")


async def generate_audio_for_chapter_preview(
    book_id: int,
    chapter_id: int,
    db: AsyncSession,
) -> None:
    """Generate/reuse sentence clips for one fully diarized chapter only."""
    chapter = await db.get(AudiobookChapter, chapter_id)
    if chapter is None or chapter.book_id != book_id:
        raise RuntimeError("Audiobook chapter not found.")
    sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter_id)
    if not sentences:
        raise RuntimeError("Chapter has no narratable sentences.")
    pending = [sentence for sentence in sentences if sentence.status == "pending_diarization"]
    if pending:
        raise RuntimeError(f"Finish speaker analysis for this chapter first ({len(pending)} sentences remain).")
    if any(sentence.character_id is None for sentence in sentences):
        raise RuntimeError("Assign a speaker to every chapter sentence before generating a preview.")

    settings = await crud.audiobook.get_audiobook_settings(db)

    snippets_dir = LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id) / "snippets"
    snippets_dir.mkdir(parents=True, exist_ok=True)
    completed = 0
    await crud.audiobook.update_book_pipeline_progress(
        db,
        book_id,
        current=0,
        total=len(sentences),
        detail=f"Generating manual preview for chapter {chapter.chapter_number}",
    )
    for sentence in sentences:
        existing_path = LIBRARY_PATH.parent / sentence.audio_file_path if sentence.audio_file_path else None
        if sentence.status == "audio_generated" and existing_path and existing_path.exists():
            completed += 1
            continue

        try:
            await _generate_sentence_clip(settings, book_id, sentence, db)
        except Exception:
            await crud.audiobook.mark_sentence_error(db, sentence.id)
            raise
        completed += 1
        await crud.audiobook.update_book_pipeline_progress(
            db,
            book_id,
            current=completed,
            total=len(sentences),
            detail=(f"Chapter {chapter.chapter_number} preview: " f"generated {completed} of {len(sentences)} sentences"),
        )
