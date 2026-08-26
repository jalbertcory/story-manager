"""Phase 4: provider-neutral TTS — generate a per-sentence MP3 snippet."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..models import AudiobookChapter, AudiobookCharacter, AudiobookSentence, AudiobookSettings
from .audiobook_text import split_speech_segments
from .endpoint_pool import settings_for_provider
from .tts_providers import (
    DEFAULT_VOICE_PROMPT,
    TTSRequest,
    TTSResult,
    design_omnivoice_voice,
    materialize_qwen_preset_voice,
    synthesize_speech_batch,
    synthesize_speech_result,
    tts_provider_name,
)

logger = logging.getLogger(__name__)
TTS_BATCH_SIZE = max(1, int(os.getenv("AUDIOBOOK_TTS_BATCH_SIZE", "4")))
TTS_FETCH_SIZE = max(TTS_BATCH_SIZE, int(os.getenv("AUDIOBOOK_TTS_FETCH_SIZE", "64")))
_LOCAL_DESIGN_PROVIDERS = {"omnivoice", "qwen3"}
VOICE_ROSTER_MAX_SIMILARITY = 0.9
_QWEN_PRESET_VOICES = {
    "female": ("Vivian", "Serena", "Ono_Anna", "Sohee"),
    "male": ("Ryan", "Aiden", "Uncle_Fu", "Dylan", "Eric"),
    "neutral": ("Vivian", "Ryan", "Serena", "Aiden", "Ono_Anna", "Uncle_Fu", "Sohee", "Dylan", "Eric"),
}
_LEADING_EXPRESSION_RE = re.compile(
    r"^((?:\[(?:laughter|sigh|whisper|surprise-oh|dissatisfaction-hnn|confirmation-en)\]\s*)+)",
    re.IGNORECASE,
)
_VOICE_PROFILE_TOKEN_RE = re.compile(r"\[[a-z]+-[^\]]+\]", re.IGNORECASE)
_VOICE_TIMBRES = (
    "a dark, velvety timbre with restrained breath",
    "a bright, bell-like timbre with crisp edges",
    "a smoky, husky texture with gentle vocal fry",
    "a reedy, nasal-forward tone with a narrow focus",
    "a warm, rounded timbre with soft breathiness",
    "a cool, glass-clear tone with very little breath",
    "a brassy, projected timbre with broad overtones",
    "a dry, papery texture with an intimate scale",
    "a silvery, airy tone with light vocal weight",
    "an earthy, textured timbre with grounded weight",
    "a rich, theatrical tone with elastic intonation",
    "a plainspoken, close-mic tone with natural warmth",
    "a flinty, compact timbre with hard consonant edges",
    "a mellow, honeyed tone with rounded consonants",
    "a wiry, energetic timbre with a slight rasp",
    "a resonant, stately tone with a clean surface",
)
_VOICE_CADENCES = (
    "measured phrases and deliberate pauses",
    "quick, nimble phrases and sharply placed pauses",
    "a flowing, musical cadence with gentle rises",
    "a clipped, economical cadence with firm endings",
    "an unhurried cadence with long, confident phrases",
    "a lively staccato cadence with playful emphasis",
    "a precise, formal cadence with even timing",
    "a conversational cadence with irregular, human pauses",
    "a lilting cadence with buoyant sentence endings",
    "a grounded cadence with downward sentence endings",
    "a dramatic cadence with controlled changes in intensity",
    "a calm cadence with minimal pitch movement",
    "a curious cadence with lightly rising inflection",
    "an assertive cadence with emphatic key words",
    "a guarded cadence with short pauses before emphasis",
    "a relaxed cadence with smooth word connections",
)
_VOICE_RESONANCES = (
    "forward facial resonance",
    "deep chest resonance",
    "a balanced mid-mouth resonance",
    "light upper resonance",
    "a compact throat-centered resonance",
    "an open, spacious resonance",
    "a close, intimate resonance",
    "a broad, room-filling resonance",
)


async def _book_tts_settings(
    db: AsyncSession,
    book_id: int,
) -> AudiobookSettings | None:
    """Lock a book/series to one provider and expose only its endpoints."""
    settings = await crud.audiobook.get_audiobook_settings(db)
    provider = await crud.audiobook.lock_book_tts_provider(
        db,
        book_id,
        tts_provider_name(settings),
    )
    if settings is None:
        if provider == "stub":
            return None
        raise RuntimeError(f"This audiobook is locked to {provider}, but Audio & AI Configuration is missing.")
    return settings_for_provider(settings, "tts", provider)


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


def stable_character_seed(character: AudiobookCharacter) -> int:
    identity = f"{character.book_id}:{character.name.casefold()}"
    return int.from_bytes(hashlib.sha256(identity.encode("utf-8")).digest()[:4], "big") & 0x7FFFFFFF


def distinctive_voice_prompt(
    character: AudiobookCharacter,
    prompt: str | None = None,
) -> str:
    """Expand coarse roster tokens into a stable, character-specific acoustic identity."""
    base = (prompt or character.voice_prompt or DEFAULT_VOICE_PROMPT).strip()
    prose = _VOICE_PROFILE_TOKEN_RE.sub("", base).strip()
    if len(prose.split()) >= 6:
        return base

    digest = hashlib.sha256(f"{character.book_id}:{character.name.casefold()}:voice".encode("utf-8")).digest()
    timbre = _VOICE_TIMBRES[int.from_bytes(digest[0:2], "big") % len(_VOICE_TIMBRES)]
    cadence = _VOICE_CADENCES[int.from_bytes(digest[2:4], "big") % len(_VOICE_CADENCES)]
    resonance = _VOICE_RESONANCES[int.from_bytes(digest[4:6], "big") % len(_VOICE_RESONANCES)]
    return (
        f"{base} Speak with {timbre}, {resonance}, and {cadence}. "
        "Make this vocal identity immediately distinguishable from the rest of the cast, "
        "and keep its timbre, resonance, accent, and cadence unchanged across every line."
    )


def _compatible_qwen_presets(character: AudiobookCharacter) -> list[str]:
    match = re.search(r"\[gender-(female|male|neutral)\]", character.voice_prompt or "", re.IGNORECASE)
    gender = match.group(1).lower() if match else "neutral"
    presets = _QWEN_PRESET_VOICES[gender]
    offset = stable_character_seed(character) % len(presets)
    return [f"preset:{presets[(offset + index) % len(presets)]}" for index in range(len(presets))]


async def _materialize_distinct_qwen_preset(
    settings: AudiobookSettings,
    character: AudiobookCharacter,
    voice_prompt: str,
    avoid_voice_ids: list[str],
):
    last_conflict: httpx.HTTPStatusError | None = None
    for preset_voice_id in _compatible_qwen_presets(character):
        try:
            return await materialize_qwen_preset_voice(
                settings,
                preset_voice_id,
                voice_prompt,
                seed=character.tts_seed,
                avoid_voice_ids=avoid_voice_ids,
                max_voice_similarity=VOICE_ROSTER_MAX_SIMILARITY,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            last_conflict = exc
    if last_conflict is not None:
        raise last_conflict
    raise RuntimeError(f"No compatible Qwen preset voice is available for {character.name}.")


async def _ensure_character_voice(
    settings: AudiobookSettings | None,
    character: AudiobookCharacter | None,
    db: AsyncSession,
) -> None:
    """Provision a deterministic seed and durable local clone on first use."""
    if character is None:
        return
    changed = False
    if character.tts_seed is None:
        character.tts_seed = stable_character_seed(character)
        changed = True
    if settings is None or tts_provider_name(settings) not in _LOCAL_DESIGN_PROVIDERS:
        if changed:
            await db.commit()
        return
    provider = tts_provider_name(settings)
    if character.tts_voice_provider == provider and character.tts_voice_id:
        if changed:
            await db.commit()
        return

    voice_prompt = distinctive_voice_prompt(character)
    if character.voice_prompt != voice_prompt:
        character.voice_prompt = voice_prompt
        changed = True
    avoid_voice_ids = []
    if provider == "qwen3":
        avoid_voice_ids = [
            candidate.tts_voice_id
            for candidate in await crud.audiobook.get_characters_for_book(db, character.book_id)
            if candidate.id != character.id and candidate.tts_voice_provider == provider and candidate.tts_voice_id
        ]
    # Keep the legacy symbol as the patch point for integrations while the
    # implementation now supports both local design-capable providers.
    try:
        designed = await design_omnivoice_voice(
            settings,
            voice_prompt,
            seed=character.tts_seed,
            avoid_voice_ids=avoid_voice_ids,
            max_voice_similarity=VOICE_ROSTER_MAX_SIMILARITY,
        )
    except httpx.HTTPStatusError as exc:
        if provider != "qwen3" or exc.response.status_code != 409:
            raise
        logger.info("Voice design saturated for %s; trying a distinct official preset reference.", character.name)
        designed = await _materialize_distinct_qwen_preset(
            settings,
            character,
            voice_prompt,
            avoid_voice_ids,
        )
    character.tts_voice_id = designed.id
    character.tts_voice_provider = provider
    await db.commit()
    linked_characters = await crud.audiobook.propagate_character_profile_across_series(db, character)
    for linked_character in linked_characters:
        await crud.audiobook.cascade_voice_change(db, linked_character.id)
    logger.info(
        "Assigned reusable %s voice %s to %s (%d linked roster entries, closest voice %.3f, %d attempts).",
        provider,
        designed.id,
        character.name,
        len(linked_characters),
        designed.max_cross_voice_similarity or 0.0,
        designed.attempts,
    )


async def _generate_sentence_clip(
    settings: AudiobookSettings | None,
    book_id: int,
    sentence: AudiobookSentence,
    db: AsyncSession,
    requests: list[TTSRequest] | None = None,
) -> None:
    requests = requests or await _build_sentence_requests(settings, sentence, db)
    results = [await _synthesize_with_retries(settings, sentence.id, request) for request in requests]
    audio_bytes = await _concatenate_mp3_parts([result.audio_bytes for result in results], sentence.id)
    await _persist_sentence_audio(
        book_id,
        sentence,
        TTSResult(
            audio_bytes=audio_bytes,
            voice_similarity=min(
                (result.voice_similarity for result in results if result.voice_similarity is not None),
                default=None,
            ),
            attempts=sum(result.attempts or 1 for result in results),
        ),
        db,
    )


async def _build_sentence_request(
    settings: AudiobookSettings | None,
    sentence: AudiobookSentence,
    db: AsyncSession,
) -> TTSRequest:
    """Compatibility helper for callers that require a single request."""
    requests = await _build_sentence_requests(settings, sentence, db)
    return requests[0]


def _request_for_character(
    settings: AudiobookSettings | None,
    character: AudiobookCharacter | None,
    text: str,
) -> TTSRequest:
    voice_prompt = character.voice_prompt if character and character.voice_prompt else DEFAULT_VOICE_PROMPT
    voice_id = _voice_id_for_provider(settings, character) if character else None
    return TTSRequest(
        text=text,
        voice_prompt=voice_prompt,
        voice_id=voice_id,
        voice_provider=character.tts_voice_provider if character else None,
        seed=character.tts_seed if character else None,
        min_voice_similarity=(getattr(settings, "tts_voice_similarity_threshold", 0.45) if voice_id else None),
        quality_attempts=getattr(settings, "tts_quality_attempts", 3) or 3,
    )


async def _build_sentence_requests(
    settings: AudiobookSettings | None,
    sentence: AudiobookSentence,
    db: AsyncSession,
) -> list[TTSRequest]:
    """Render dialogue with its character and attribution prose with Narrator."""

    character = await db.get(AudiobookCharacter, sentence.character_id) if sentence.character_id is not None else None
    await _ensure_character_voice(settings, character, db)
    full_text = sentence.tagged_text or sentence.original_text
    if character is None or character.is_narrator:
        return [_request_for_character(settings, character, full_text)]

    segments, _quote_state = split_speech_segments(sentence.original_text)
    spoken_segments = [segment for segment in segments if segment.has_speech]
    roles = {segment.is_dialogue for segment in spoken_segments}
    if len(spoken_segments) < 2 or roles != {False, True}:
        return [_request_for_character(settings, character, full_text)]

    chapter = await db.get(AudiobookChapter, sentence.chapter_id)
    narrator = None
    if chapter is not None:
        narrator = next(
            (
                candidate
                for candidate in await crud.audiobook.get_characters_for_book(db, chapter.book_id)
                if candidate.is_narrator
            ),
            None,
        )
    await _ensure_character_voice(settings, narrator, db)

    expression_match = _LEADING_EXPRESSION_RE.match(full_text)
    expression_prefix = expression_match.group(1).strip() if expression_match else ""
    expression_applied = False
    requests: list[TTSRequest] = []
    for segment in spoken_segments:
        text = segment.text
        if segment.is_dialogue and expression_prefix and not expression_applied:
            text = f"{expression_prefix} {text}"
            expression_applied = True
        requests.append(
            _request_for_character(
                settings,
                character if segment.is_dialogue else narrator,
                text,
            )
        )
    return requests


async def _concatenate_mp3_parts(parts: list[bytes], sentence_id: int) -> bytes:
    if len(parts) == 1:
        return parts[0]
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to combine dialogue and narrator audio.")

    with tempfile.TemporaryDirectory(prefix=f"story-manager-sentence-{sentence_id}-") as directory:
        root = Path(directory)
        manifest_path = root / "parts.txt"
        output_path = root / "combined.mp3"
        input_paths = []
        for index, part in enumerate(parts):
            input_path = root / f"part-{index}.mp3"
            input_path.write_bytes(part)
            input_paths.append(input_path)
        manifest_path.write_text(
            "".join(f"file '{path}'\n" for path in input_paths),
            encoding="utf-8",
        )
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest_path),
            "-codec:a",
            "copy",
            "-y",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode:
            message = stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Unable to combine sentence {sentence_id} voice segments: {message}")
        return output_path.read_bytes()


async def _synthesize_with_retries(
    settings: AudiobookSettings | None,
    sentence_id: int,
    request: TTSRequest,
) -> TTSResult:
    result = None
    for attempt in range(1, 4):
        try:
            result = await synthesize_speech_result(settings, request)
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
    if result is None:
        raise RuntimeError(f"TTS returned no audio for sentence {sentence_id}.")
    return result


async def _synthesize_batch_with_retries(
    settings: AudiobookSettings | None,
    sentence_id: int,
    requests: list[TTSRequest],
) -> list[TTSResult]:
    results = None
    for attempt in range(1, 4):
        try:
            results = await synthesize_speech_batch(settings, requests)
            break
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if attempt == 3 or (status_code and status_code < 500 and status_code != 429):
                raise
            logger.warning(
                "TTS batch starting at sentence %s returned HTTP %s; retrying (%d/3).",
                sentence_id,
                status_code or "unknown",
                attempt + 1,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt == 3:
                raise
            logger.warning(
                "TTS batch starting at sentence %s failed transiently (%s); retrying (%d/3).",
                sentence_id,
                exc,
                attempt + 1,
            )
        await asyncio.sleep(2 ** (attempt - 1))
    if results is None:
        raise RuntimeError(f"TTS returned no batch audio starting at sentence {sentence_id}.")
    return results


async def _persist_sentence_audio(
    book_id: int,
    sentence: AudiobookSentence,
    result: TTSResult,
    db: AsyncSession,
    *,
    generation_group_id: str | None = None,
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
        generation_group_id=generation_group_id,
        voice_similarity=result.voice_similarity,
        tts_attempts=result.attempts,
    )


async def _generate_sentence_clips(
    settings: AudiobookSettings | None,
    book_id: int,
    sentences: list[AudiobookSentence],
    db: AsyncSession,
) -> dict[int, Exception]:
    """Generate adjacent same-voice sentences as longer, more stable blocks."""
    if not sentences:
        return {}
    request_groups = [await _build_sentence_requests(settings, sentence, db) for sentence in sentences]
    max_chars = max(100, getattr(settings, "tts_max_block_chars", 500) or 500)
    blocks = _generation_blocks(sentences, request_groups, max_chars=max_chars)
    failures: dict[int, Exception] = {}

    block_index = 0
    while block_index < len(blocks):
        block = blocks[block_index]
        block_sentences = [item[0] for item in block]
        try:
            if len(block) == 1 or len(block[0][1]) != 1:
                sentence, requests = block[0]
                await _generate_sentence_clip(settings, book_id, sentence, db, requests)
                block_index += 1
            else:
                stable_blocks = []
                while block_index < len(blocks) and len(stable_blocks) < TTS_BATCH_SIZE:
                    candidate = blocks[block_index]
                    if len(candidate) == 1 or len(candidate[0][1]) != 1:
                        break
                    stable_blocks.append(candidate)
                    block_index += 1
                await _generate_stable_blocks(settings, book_id, stable_blocks, db)
        except Exception as exc:
            for sentence in block_sentences:
                failures[sentence.id] = exc
            # Provider failures usually affect every later block as well. Stop
            # here so one outage does not turn an entire book into error rows.
            break
    return failures


def _generation_blocks(
    sentences: list[AudiobookSentence],
    request_groups: list[list[TTSRequest]],
    *,
    max_chars: int,
) -> list[list[tuple[AudiobookSentence, list[TTSRequest]]]]:
    """Coalesce only adjacent, single-role requests with identical voice controls."""
    blocks: list[list[tuple[AudiobookSentence, list[TTSRequest]]]] = []
    current: list[tuple[AudiobookSentence, list[TTSRequest]]] = []
    current_chars = 0
    current_signature = None
    previous_sentence = None
    for sentence, requests in zip(sentences, request_groups, strict=True):
        request = requests[0] if len(requests) == 1 else None
        signature = (
            sentence.chapter_id,
            sentence.character_id,
            request.voice_prompt if request else None,
            request.voice_id if request else None,
            request.voice_provider if request else None,
            request.seed if request else None,
        )
        text_chars = len(request.text) if request else 0
        contiguous = previous_sentence is not None and sentence.sequence_order == previous_sentence.sequence_order + 1
        can_append = (
            request is not None
            and current
            and signature == current_signature
            and contiguous
            and current_chars + 1 + text_chars <= max_chars
        )
        if not can_append:
            if current:
                blocks.append(current)
            current = [(sentence, requests)]
            current_chars = text_chars
            current_signature = signature if request is not None else None
        else:
            current.append((sentence, requests))
            current_chars += 1 + text_chars
        previous_sentence = sentence
    if current:
        blocks.append(current)
    return blocks


async def _generate_stable_block(
    settings: AudiobookSettings | None,
    book_id: int,
    sentences: list[AudiobookSentence],
    prototype: TTSRequest,
    db: AsyncSession,
) -> None:
    await _generate_stable_blocks(
        settings,
        book_id,
        [[(sentence, [prototype]) for sentence in sentences]],
        db,
    )


async def _generate_stable_blocks(
    settings: AudiobookSettings | None,
    book_id: int,
    blocks: list[list[tuple[AudiobookSentence, list[TTSRequest]]]],
    db: AsyncSession,
) -> None:
    plans = []
    for block in blocks:
        sentences = [item[0] for item in block]
        prototype = block[0][1][0]
        texts = [sentence.tagged_text or sentence.original_text for sentence in sentences]
        combined = " ".join(text.strip() for text in texts)
        group_digest = _stable_group_digest(sentences, prototype)
        plans.append((sentences, texts, group_digest, replace(prototype, text=combined)))

    results = await _synthesize_batch_with_retries(
        settings,
        plans[0][0][0].id,
        [plan[3] for plan in plans],
    )
    for (sentences, texts, group_digest, _request), result in zip(plans, results, strict=True):
        parts = await _split_block_audio(result.audio_bytes, texts, group_digest)
        if len(parts) != len(sentences):
            raise RuntimeError(f"TTS block {group_digest} produced {len(parts)} slices for {len(sentences)} sentences.")
        for sentence, audio_bytes in zip(sentences, parts, strict=True):
            await _persist_sentence_audio(
                book_id,
                sentence,
                replace(result, audio_bytes=audio_bytes, duration_ms=None),
                db,
                generation_group_id=group_digest,
            )


def _stable_group_digest(sentences: list[AudiobookSentence], prototype: TTSRequest) -> str:
    group_digest = hashlib.sha256(
        (
            f"{prototype.voice_provider}:{prototype.voice_id}:{prototype.seed}:" + ":".join(str(item.id) for item in sentences)
        ).encode("utf-8")
    ).hexdigest()[:32]
    return group_digest


async def _split_block_audio(audio_bytes: bytes, texts: list[str], group_id: str) -> list[bytes]:
    """Recover sentence boundaries from nearby pauses and slice a block to MP3s."""
    if len(texts) == 1:
        return [audio_bytes]
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to split stable TTS generation blocks.")
    with tempfile.TemporaryDirectory(prefix=f"story-manager-block-{group_id}-") as directory:
        root = Path(directory)
        source = root / "block.mp3"
        source.write_bytes(audio_bytes)
        duration_ms = _get_mp3_duration_ms(source)
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-v",
            "info",
            "-i",
            str(source),
            "-af",
            "silencedetect=noise=-38dB:d=0.06",
            "-f",
            "null",
            "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        silence_starts: list[float] = []
        silence_midpoints: list[int] = []
        for line in stderr.decode("utf-8", errors="replace").splitlines():
            start_match = re.search(r"silence_start:\s*([0-9.]+)", line)
            end_match = re.search(r"silence_end:\s*([0-9.]+)", line)
            if start_match:
                silence_starts.append(float(start_match.group(1)))
            if end_match and silence_starts:
                start = silence_starts.pop(0)
                end = float(end_match.group(1))
                silence_midpoints.append(round((start + end) * 500))

        boundaries = _estimated_block_boundaries(duration_ms, texts, silence_midpoints)

        parts: list[bytes] = []
        for index, (start_ms, end_ms) in enumerate(zip(boundaries, boundaries[1:])):
            output = root / f"part-{index}.mp3"
            process = await asyncio.create_subprocess_exec(
                ffmpeg,
                "-v",
                "error",
                "-ss",
                f"{start_ms / 1000:.3f}",
                "-t",
                f"{(end_ms - start_ms) / 1000:.3f}",
                "-i",
                str(source),
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "96k",
                "-y",
                str(output),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, split_stderr = await process.communicate()
            if process.returncode:
                message = split_stderr.decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"Unable to split TTS block {group_id}: {message}")
            parts.append(output.read_bytes())
        return parts


def _estimated_block_boundaries(
    duration_ms: int,
    texts: list[str],
    silence_midpoints: list[int],
) -> list[int]:
    """Allocate monotonic sentence slices, snapping weighted estimates to pauses."""
    weights = [max(1, len(re.sub(r"\W+", "", text))) for text in texts]
    total_weight = sum(weights)
    expected = []
    cumulative = 0
    for weight in weights[:-1]:
        cumulative += weight
        expected.append(round(duration_ms * cumulative / total_weight))
    search_radius = max(900, min(2500, duration_ms // max(2, len(texts)) // 2))
    minimum_gap = max(1, min(120, duration_ms // max(1, len(texts) * 2)))
    boundaries = [0]
    available = list(silence_midpoints)
    for boundary_index, estimate in enumerate(expected, start=1):
        lower = boundaries[-1] + minimum_gap
        upper = duration_ms - minimum_gap * (len(texts) - boundary_index)
        candidates = [point for point in available if lower <= point <= upper and abs(point - estimate) <= search_radius]
        boundary = min(candidates, key=lambda point: abs(point - estimate)) if candidates else estimate
        boundary = max(lower, min(boundary, upper))
        boundaries.append(boundary)
        available = [point for point in available if point > boundary]
    boundaries.append(duration_ms)
    return boundaries


async def generate_audio_for_sentences(
    book_id: int,
    sentence_ids: list[int],
    db: AsyncSession,
) -> dict[int, Exception]:
    """Generate a durable batch for the background speech lane."""
    settings = await _book_tts_settings(db, book_id)
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

    settings = await _book_tts_settings(db, book_id)
    await _generate_sentence_clip(settings, book_id, sentence, db)
    await crud.audiobook.flag_chapter_for_reassembly(db, chapter.id)


async def generate_audio_for_book(book_id: int, db: AsyncSession) -> None:
    """Phase 4: iterate ready_for_audio sentences and call the configured TTS provider."""
    settings = await _book_tts_settings(db, book_id)

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
            limit=TTS_FETCH_SIZE,
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

        if failures:
            await crud.audiobook.set_book_pipeline_status(db, book_id, "error")
            first_error = next(iter(failures.values()))
            raise RuntimeError(f"TTS failed for {len(failures)} sentence(s) in book {book_id}: {first_error}") from first_error

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

    settings = await _book_tts_settings(db, book_id)

    snippets_dir = LIBRARY_PATH.parent / "library" / "audiobooks" / str(book_id) / "snippets"
    snippets_dir.mkdir(parents=True, exist_ok=True)
    completed = 0
    to_generate: list[AudiobookSentence] = []
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
        to_generate.append(sentence)

    failures = await _generate_sentence_clips(settings, book_id, to_generate, db)
    if failures:
        for sentence_id in failures:
            await crud.audiobook.mark_sentence_error(db, sentence_id)
        raise next(iter(failures.values()))
    for sentence in to_generate:
        completed += 1
        await crud.audiobook.update_book_pipeline_progress(
            db,
            book_id,
            current=completed,
            total=len(sentences),
            detail=(f"Chapter {chapter.chapter_number} preview: " f"generated {completed} of {len(sentences)} sentences"),
        )
