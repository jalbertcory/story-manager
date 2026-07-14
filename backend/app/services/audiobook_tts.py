"""Phase 4: OmniVoice TTS — generate a per-sentence MP3 snippet."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import shutil

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..models import AudiobookCharacter

logger = logging.getLogger(__name__)

DEFAULT_VOICE_PROMPT = "[gender-neutral][pitch-medium][speed-normal]"


def _snippet_path(book_id: int, sentence_id: int) -> Path:
    return LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id) / "snippets" / f"{sentence_id}.mp3"


def _relative_path(full_path: Path) -> str:
    return str(full_path.relative_to(LIBRARY_PATH.parent))


def _get_mp3_duration_ms(path: Path) -> int:
    from mutagen.mp3 import MP3

    audio = MP3(str(path))
    return int(audio.info.length * 1000)


async def _call_omnivoice(endpoint: str, voice_prompt: str, tagged_text: str) -> bytes:
    if endpoint.startswith("stub://"):
        duration_ms = max(350, min(5000, len(tagged_text.split()) * 260))
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required by the local audiobook TTS harness.")
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=22050:cl=mono",
            "-t",
            f"{duration_ms / 1000:.3f}",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "64k",
            "-f",
            "mp3",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode:
            message = stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Local TTS harness failed: {message}")
        return stdout

    url = endpoint.rstrip("/") + "/generate"
    # Local neural TTS can take longer on the first MPS/CPU request while
    # kernels warm up. Keep connection failures fast but allow inference time.
    timeout = httpx.Timeout(600.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            json={"voice": voice_prompt, "text": tagged_text},
            headers={"Accept": "audio/mpeg"},
        )
        resp.raise_for_status()
    return resp.content


async def generate_audio_for_book(book_id: int, db: AsyncSession) -> None:
    """Phase 4: iterate ready_for_audio sentences and call OmniVoice for each."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    endpoint = settings.omnivoice_endpoint if settings else None
    if not endpoint and (settings is None or (settings.llm_provider or "stub").lower() == "stub"):
        endpoint = "stub://local"
    if not endpoint:
        raise RuntimeError("OmniVoice endpoint not configured. Set it in Audio Settings.")

    # Ensure snippets directory exists
    snippets_dir = LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id) / "snippets"
    snippets_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    failed = 0
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

            # Resolve voice prompt from the assigned character
            voice_prompt = DEFAULT_VOICE_PROMPT
            if sentence.character_id is not None:
                char = await db.get(AudiobookCharacter, sentence.character_id)
                if char and char.voice_design_prompt:
                    voice_prompt = char.voice_design_prompt

            text_to_speak = sentence.tagged_text or sentence.original_text

            logger.debug("Generating audio for sentence %s (book %s).", sentence.id, book_id)
            try:
                audio_bytes = await _call_omnivoice(endpoint, voice_prompt, text_to_speak)
                out_path = _snippet_path(book_id, sentence.id)
                out_path.write_bytes(audio_bytes)

                duration_ms = _get_mp3_duration_ms(out_path)
            except httpx.HTTPStatusError as exc:
                response_text = exc.response.text[:200] if exc.response is not None else ""
                logger.error(
                    "OmniVoice error for sentence %s: %s %s",
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

            await crud.audiobook.update_sentence_audio(db, sentence.id, _relative_path(out_path), duration_ms)
            processed += 1

            # Flag chapter for reassembly if all its sentences are done
            if await crud.audiobook.chapter_all_audio_generated(db, sentence.chapter_id):
                await crud.audiobook.flag_chapter_for_reassembly(db, sentence.chapter_id)

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
