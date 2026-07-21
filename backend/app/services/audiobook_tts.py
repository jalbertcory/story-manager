"""Phase 4: provider-neutral TTS — generate a per-sentence MP3 snippet."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..models import AudiobookChapter, AudiobookCharacter, AudiobookSentence, AudiobookSettings
from .tts_providers import (
    DEFAULT_VOICE_PROMPT,
    TTSRequest,
    TTSResult,
    synthesize_speech,
    synthesize_speech_batch,
    tts_provider_name,
)

logger = logging.getLogger(__name__)
TTS_BATCH_SIZE = max(1, int(os.getenv("AUDIOBOOK_TTS_BATCH_SIZE", "4")))


def _snippet_path(book_id: int, sentence_id: int) -> Path:
    return LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id) / "snippets" / f"{sentence_id}.mp3"


def _relative_path(full_path: Path) -> str:
    return str(full_path.relative_to(LIBRARY_PATH.parent))


def _get_mp3_duration_ms(path: Path) -> int:
    from mutagen.mp3 import MP3

    audio = MP3(str(path))
    return round(audio.info.length * 1000)


def _voice_id_for_provider(
    settings: AudiobookSettings | None,
    character: AudiobookCharacter,
) -> str | None:
    if character.tts_voice_provider != tts_provider_name(settings):
        return None
    return character.tts_voice_id


async def _generate_sentence_clip(
    settings: AudiobookSettings | None,
    book_id: int,
    sentence: AudiobookSentence,
    db: AsyncSession,
) -> None:
    request = await _build_sentence_request(settings, sentence, db)
    audio_bytes = await _synthesize_with_retries(settings, sentence.id, request)
    await _persist_sentence_audio(
        book_id,
        sentence,
        TTSResult(audio_bytes=audio_bytes),
        db,
    )


async def _build_sentence_request(
    settings: AudiobookSettings | None,
    sentence: AudiobookSentence,
    db: AsyncSession,
) -> TTSRequest:
    voice_prompt = DEFAULT_VOICE_PROMPT
    voice_id = None
    if sentence.character_id is not None:
        char = await db.get(AudiobookCharacter, sentence.character_id)
        if char:
            voice_prompt = char.voice_prompt or voice_prompt
            voice_id = _voice_id_for_provider(settings, char)

    return TTSRequest(
        text=sentence.tagged_text or sentence.original_text,
        voice_prompt=voice_prompt,
        voice_id=voice_id,
    )


async def _synthesize_with_retries(
    settings: AudiobookSettings | None,
    sentence_id: int,
    request: TTSRequest,
) -> bytes:
    audio_bytes = None
    for attempt in range(1, 4):
        try:
            audio_bytes = await synthesize_speech(settings, request)
            break
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if attempt == 3 or (status_code and status_code < 500 and status_code != 429):
                raise
            logger.warning(
                "TTS request for sentence %s returned HTTP %s; retrying (%d/3).",
                sentence_id,
                status_code or "unknown",
                attempt + 1,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == 3:
                raise
            logger.warning(
                "TTS request for sentence %s failed transiently (%s); retrying (%d/3).",
                sentence_id,
                exc,
                attempt + 1,
            )
        await asyncio.sleep(2 ** (attempt - 1))
    if audio_bytes is None:
        raise RuntimeError(f"TTS returned no audio for sentence {sentence_id}.")
    return audio_bytes


async def _persist_sentence_audio(
    book_id: int,
    sentence: AudiobookSentence,
    result: TTSResult,
    db: AsyncSession,
) -> None:
    out_path = _snippet_path(book_id, sentence.id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(result.audio_bytes)
    # Always inspect the artifact we actually wrote. Provider metadata is
    # useful for transport, but accepting it without parsing could defer a
    # corrupt/empty MP3 failure until final chapter assembly.
    duration_ms = _get_mp3_duration_ms(out_path)
    if result.duration_ms and abs(result.duration_ms - duration_ms) > 1_000:
        logger.warning(
            "Sentence %s reported %d ms of audio but the MP3 contains %d ms.",
            sentence.id,
            result.duration_ms,
            duration_ms,
        )
    await crud.audiobook.update_sentence_audio(
        db,
        sentence.id,
        _relative_path(out_path),
        duration_ms,
    )


async def _generate_sentence_clips(
    settings: AudiobookSettings | None,
    book_id: int,
    sentences: list[AudiobookSentence],
    db: AsyncSession,
) -> dict[int, Exception]:
    """Generate a provider-native batch and isolate any batch failure by sentence."""
    if not sentences:
        return {}
    if len(sentences) == 1 or tts_provider_name(settings) != "omnivoice":
        failures = {}
        for sentence in sentences:
            try:
                await _generate_sentence_clip(settings, book_id, sentence, db)
            except Exception as exc:
                failures[sentence.id] = exc
        return failures

    requests = [await _build_sentence_request(settings, sentence, db) for sentence in sentences]
    results = None
    for attempt in range(1, 4):
        try:
            results = await synthesize_speech_batch(settings, requests)
            break
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if attempt == 3 or (status_code and status_code < 500 and status_code != 429):
                break
            logger.warning(
                "TTS batch returned HTTP %s; retrying (%d/3).",
                status_code or "unknown",
                attempt + 1,
            )
        except (httpx.TimeoutException, httpx.TransportError, RuntimeError) as exc:
            if attempt == 3:
                break
            logger.warning(
                "TTS batch failed transiently (%s); retrying (%d/3).",
                exc,
                attempt + 1,
            )
        await asyncio.sleep(2 ** (attempt - 1))

    if results is None:
        logger.warning(
            "TTS batch for %d sentences failed; retrying each sentence independently.",
            len(sentences),
        )
        failures = {}
        for sentence in sentences:
            try:
                await _generate_sentence_clip(settings, book_id, sentence, db)
            except Exception as exc:
                failures[sentence.id] = exc
        return failures

    failures = {}
    for sentence, result in zip(sentences, results, strict=True):
        try:
            await _persist_sentence_audio(book_id, sentence, result, db)
        except Exception as exc:
            failures[sentence.id] = exc
    return failures


async def generate_audio_for_sentences(
    book_id: int,
    sentence_ids: list[int],
    db: AsyncSession,
) -> dict[int, Exception]:
    """Generate a durable batch for the background speech lane."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    sentences = []
    for sentence_id in sentence_ids:
        sentence = await db.get(AudiobookSentence, sentence_id)
        if sentence is None:
            continue
        chapter = await db.get(AudiobookChapter, sentence.chapter_id)
        if chapter is None or chapter.book_id != book_id:
            continue
        sentences.append(sentence)
    failures = await _generate_sentence_clips(settings, book_id, sentences, db)
    for chapter_id in {sentence.chapter_id for sentence in sentences if sentence.id not in failures}:
        await crud.audiobook.flag_chapter_for_reassembly(db, chapter_id)
    return failures


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

    counts = await crud.audiobook.count_sentences_by_status(db, book_id)
    processed = counts.get("audio_generated", 0)
    total = sum(counts.values())
    failed = 0
    await crud.audiobook.update_book_pipeline_progress(
        db,
        book_id,
        current=processed,
        total=total,
        detail=f"Preparing remaining speech ({processed:,} of {total:,} clips generated)",
    )
    while True:
        if await crud.audiobook.pause_book_pipeline_if_requested(db, book_id):
            logger.info("Book %s paused during TTS generation.", book_id)
            return

        batch = await crud.audiobook.get_sentences_ready_for_audio(
            db,
            book_id,
            limit=TTS_BATCH_SIZE,
        )
        if not batch:
            break

        failures = await _generate_sentence_clips(settings, book_id, batch, db)
        for sentence in batch:
            if error := failures.get(sentence.id):
                logger.error(
                    "Unable to generate audio for sentence %s: %s",
                    sentence.id,
                    error,
                )
                await crud.audiobook.mark_sentence_error(db, sentence.id)
                failed += 1
            else:
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
