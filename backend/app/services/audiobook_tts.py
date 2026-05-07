"""Phase 4: OmniVoice TTS — generate a per-sentence MP3 snippet."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..models import AudiobookCharacter, AudiobookSentence

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
    url = endpoint.rstrip("/") + "/generate"
    async with httpx.AsyncClient(timeout=120.0) as client:
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
    if not settings or not settings.omnivoice_endpoint:
        raise RuntimeError("OmniVoice endpoint not configured. Set it in Audio Settings.")

    endpoint = settings.omnivoice_endpoint

    # Ensure snippets directory exists
    snippets_dir = LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id) / "snippets"
    snippets_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    while True:
        batch = await crud.audiobook.get_sentences_ready_for_audio(db, book_id, limit=20)
        if not batch:
            break

        for sentence in batch:
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
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "OmniVoice error for sentence %s: %s %s",
                    sentence.id,
                    exc.response.status_code,
                    exc.response.text[:200],
                )
                # Mark as error but continue with remaining sentences
                from sqlalchemy import update
                from ..database import SessionLocal
                async with SessionLocal() as err_db:
                    await err_db.execute(
                        update(AudiobookSentence)
                        .where(AudiobookSentence.id == sentence.id)
                        .values(status="error")
                    )
                    await err_db.commit()
                continue

            out_path = _snippet_path(book_id, sentence.id)
            out_path.write_bytes(audio_bytes)

            duration_ms = _get_mp3_duration_ms(out_path)
            await crud.audiobook.update_sentence_audio(
                db, sentence.id, _relative_path(out_path), duration_ms
            )
            processed += 1

            # Flag chapter for reassembly if all its sentences are done
            if await crud.audiobook.chapter_all_audio_generated(db, sentence.chapter_id):
                await crud.audiobook.flag_chapter_for_reassembly(db, sentence.chapter_id)

    logger.info("TTS complete for book %s: %d sentences generated.", book_id, processed)
    await crud.audiobook.set_book_pipeline_status(db, book_id, "assembling")
