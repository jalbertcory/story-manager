"""Transcribe imported narration and align timestamped words to EPUB sentences."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from collections.abc import Mapping

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import crud
from ..config import LIBRARY_PATH
from ..lifecycle import (
    ALIGNMENT_METHOD,
    IMPORTED_AUDIOBOOK,
    AlignmentMethod,
    ImportedAudiobookStatus,
    transition_state,
)
from ..models import (
    AudiobookChapter,
    AudiobookSentence,
    ImportedAudiobook,
    ImportedAudiobookCue,
    ImportedAudiobookTrack,
)
from .audiobook_import import imported_audiobook_dir, relative_library_path, sentences_for_logical_chapter
from .endpoint_pool import configured_endpoints
from .endpoint_pool import ProviderSettings
from .transcription_providers import (
    TranscriptResult,
    TranscriptWord,
    transcribe_file,
    transcription_provider_name,
)

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", re.IGNORECASE)
_NUMBER_ALIASES = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}
_MAX_FUZZY_GAP_CELLS = 250_000


@dataclass(frozen=True)
class AlignedCue:
    sentence_id: int
    sequence_order: int
    clip_begin_ms: int
    clip_end_ms: int
    confidence: float
    method: str


@dataclass(frozen=True)
class AlignmentResult:
    cues: list[AlignedCue]
    score: float
    matched_token_count: int
    canonical_token_count: int
    matched_transcript_token_count: int
    transcript_token_count: int
    first_matched_ms: int | None
    last_matched_ms: int | None


@dataclass(frozen=True)
class _CanonicalToken:
    normalized: str
    sentence_index: int


@dataclass(frozen=True)
class _TranscriptToken:
    normalized: str
    word_index: int


def _normalized_tokens(text: str) -> list[str]:
    value = unicodedata.normalize("NFKC", text).casefold()
    value = value.replace("’", "'").replace("‘", "'")
    return [_NUMBER_ALIASES.get(token, token) for token in _TOKEN_RE.findall(value)]


def _token_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def _fuzzy_gap_matches(
    canonical: list[_CanonicalToken],
    transcript: list[_TranscriptToken],
    canonical_offset: int,
    transcript_offset: int,
) -> dict[int, tuple[int, float]]:
    """Globally align one unmatched gap and return credible substitutions."""
    m, n = len(canonical), len(transcript)
    if not m or not n or m * n > _MAX_FUZZY_GAP_CELLS:
        return {}

    gap_penalty = -1.15
    prior = [index * gap_penalty for index in range(n + 1)]
    trace = [bytearray(n + 1) for _ in range(m + 1)]
    for column in range(1, n + 1):
        trace[0][column] = 2  # left
    for row in range(1, m + 1):
        trace[row][0] = 1  # up
        current = [row * gap_penalty] + [0.0] * n
        for column in range(1, n + 1):
            similarity = _token_similarity(
                canonical[row - 1].normalized,
                transcript[column - 1].normalized,
            )
            diagonal_score = 2.5 if similarity == 1 else (2.0 * similarity - 1.25)
            diagonal = prior[column - 1] + diagonal_score
            up = prior[column] + gap_penalty
            left = current[column - 1] + gap_penalty
            best = max(diagonal, up, left)
            current[column] = best
            trace[row][column] = 0 if best == diagonal else (1 if best == up else 2)
        prior = current

    matches = {}
    row, column = m, n
    while row or column:
        direction = trace[row][column]
        if row and column and direction == 0:
            similarity = _token_similarity(
                canonical[row - 1].normalized,
                transcript[column - 1].normalized,
            )
            if similarity >= 0.58:
                matches[canonical_offset + row - 1] = (
                    transcript_offset + column - 1,
                    similarity,
                )
            row -= 1
            column -= 1
        elif row and (not column or direction == 1):
            row -= 1
        else:
            column -= 1
    return matches


def _token_matches(
    canonical: list[_CanonicalToken],
    transcript: list[_TranscriptToken],
) -> dict[int, tuple[int, float]]:
    canonical_values = [token.normalized for token in canonical]
    transcript_values = [token.normalized for token in transcript]
    blocks = SequenceMatcher(
        None,
        canonical_values,
        transcript_values,
        autojunk=False,
    ).get_matching_blocks()
    matches = {}
    prior_canonical = 0
    prior_transcript = 0
    for block in blocks:
        canonical_gap = canonical[slice(prior_canonical, block.a)]
        transcript_gap = transcript[slice(prior_transcript, block.b)]
        matches.update(
            _fuzzy_gap_matches(
                canonical_gap,
                transcript_gap,
                prior_canonical,
                prior_transcript,
            )
        )
        for offset in range(block.size):
            matches[block.a + offset] = (block.b + offset, 1.0)
        prior_canonical = block.a + block.size
        prior_transcript = block.b + block.size
    return matches


def _sentence_weight(text: str) -> int:
    return max(1, len(re.sub(r"\s+", "", text))) + 10


def _interpolate_boundaries(
    boundaries: list[int | None],
    sentence_texts: list[str],
    duration_ms: int,
) -> list[int]:
    """Fill ungrounded sentence boundaries while preserving timestamp anchors."""
    clean: list[int | None] = [None] * len(boundaries)
    clean[0] = 0
    last = 0
    for index in range(1, len(boundaries) - 1):
        candidate = boundaries[index]
        if candidate is not None:
            candidate = max(1, min(duration_ms - 1, candidate))
            if candidate > last:
                clean[index] = candidate
                last = candidate
    clean[-1] = duration_ms

    anchors = [index for index, value in enumerate(clean) if value is not None]
    for left_index, right_index in zip(anchors, anchors[1:], strict=False):
        left_value = clean[left_index]
        right_value = clean[right_index]
        assert left_value is not None and right_value is not None
        if right_index == left_index + 1:
            continue
        weights = [_sentence_weight(sentence_texts[index]) for index in range(left_index, right_index)]
        total = sum(weights)
        cumulative = 0
        for boundary_index, weight in zip(range(left_index + 1, right_index), weights, strict=False):
            cumulative += weight
            clean[boundary_index] = left_value + round((right_value - left_value) * cumulative / total)

    result: list[int] = []
    for value in clean:
        assert value is not None
        result.append(value)
    return result


def align_transcript_to_sentences(
    sentences: list[tuple[int, str]],
    transcript_words: list[TranscriptWord],
    duration_ms: int,
    source_start_ms: int = 0,
) -> AlignmentResult:
    """Align ASR words to canonical sentence text in reading order."""
    canonical: list[_CanonicalToken] = []
    sentence_token_indices: list[list[int]] = [[] for _ in sentences]
    for sentence_index, (_sentence_id, text) in enumerate(sentences):
        for normalized in _normalized_tokens(text):
            sentence_token_indices[sentence_index].append(len(canonical))
            canonical.append(_CanonicalToken(normalized=normalized, sentence_index=sentence_index))

    transcript = []
    for word_index, word in enumerate(transcript_words):
        for normalized in _normalized_tokens(word.text):
            transcript.append(_TranscriptToken(normalized=normalized, word_index=word_index))

    matches = _token_matches(canonical, transcript)
    sentence_word_indices: list[list[int]] = [[] for _ in sentences]
    sentence_similarities: list[list[float]] = [[] for _ in sentences]
    for canonical_index, (transcript_index, similarity) in matches.items():
        sentence_index = canonical[canonical_index].sentence_index
        sentence_word_indices[sentence_index].append(transcript[transcript_index].word_index)
        sentence_similarities[sentence_index].append(similarity)

    starts: list[int | None] = []
    ends: list[int | None] = []
    confidences = []
    methods = []
    for token_indices, word_indices, similarities in zip(
        sentence_token_indices,
        sentence_word_indices,
        sentence_similarities,
        strict=True,
    ):
        unique_words = sorted(set(word_indices))
        starts.append(transcript_words[unique_words[0]].start_ms if unique_words else None)
        ends.append(transcript_words[unique_words[-1]].end_ms if unique_words else None)
        coverage = len(similarities) / max(1, len(token_indices))
        asr_score = sum(transcript_words[index].score for index in unique_words) / len(unique_words) if unique_words else 0.0
        similarity_score = sum(similarities) / len(similarities) if similarities else 0.0
        confidence = coverage * (0.7 * similarity_score + 0.3 * asr_score)
        confidences.append(max(0.0, min(1.0, confidence)))
        methods.append("transcribed" if coverage >= 0.6 else ("hybrid" if unique_words else "estimated"))

    raw_boundaries: list[int | None] = [0]
    for index in range(len(sentences) - 1):
        left = ends[index]
        right = starts[index + 1]
        if left is not None and right is not None:
            raw_boundaries.append(round((left + right) / 2))
        else:
            raw_boundaries.append(left if left is not None else right)
    raw_boundaries.append(duration_ms)
    boundaries = _interpolate_boundaries(
        raw_boundaries,
        [text for _sentence_id, text in sentences],
        duration_ms,
    )

    cues = [
        AlignedCue(
            sentence_id=sentence_id,
            sequence_order=index,
            clip_begin_ms=source_start_ms + boundaries[index],
            clip_end_ms=source_start_ms + max(boundaries[index] + 1, boundaries[index + 1]),
            confidence=confidences[index],
            method=methods[index],
        )
        for index, (sentence_id, _text) in enumerate(sentences)
    ]
    score = sum(
        len(indices) * confidence for indices, confidence in zip(sentence_token_indices, confidences, strict=True)
    ) / max(1, len(canonical))
    matched_transcript_indices = sorted({transcript_index for transcript_index, _similarity in matches.values()})
    matched_word_indices = [transcript[index].word_index for index in matched_transcript_indices]
    return AlignmentResult(
        cues=cues,
        score=score,
        matched_token_count=len(matches),
        canonical_token_count=len(canonical),
        matched_transcript_token_count=len(matched_transcript_indices),
        transcript_token_count=len(transcript),
        first_matched_ms=(transcript_words[matched_word_indices[0]].start_ms if matched_word_indices else None),
        last_matched_ms=(transcript_words[matched_word_indices[-1]].end_ms if matched_word_indices else None),
    )


def _transcript_coverage(result: AlignmentResult) -> float:
    return result.matched_transcript_token_count / max(1, result.transcript_token_count)


def _continuation_improves_alignment(
    current: AlignmentResult,
    candidate: AlignmentResult,
    duration_ms: int,
) -> bool:
    """Accept more canonical text only when it explains a material transcript tail."""
    if current.transcript_token_count < 20 or _transcript_coverage(current) >= 0.75:
        return False
    coverage_gain = _transcript_coverage(candidate) - _transcript_coverage(current)
    current_tail = current.last_matched_ms or 0
    candidate_tail = candidate.last_matched_ms or 0
    tail_gain = (candidate_tail - current_tail) / max(1, duration_ms)
    return candidate.score >= 0.35 and (coverage_gain >= 0.08 or tail_gain >= 0.10)


def _resolve_library_path(relative_path: str | None) -> Path | None:
    if not relative_path:
        return None
    path = (LIBRARY_PATH.parent / relative_path).resolve()
    return path if path.is_relative_to(LIBRARY_PATH.resolve()) else None


async def _extract_track_clip(track: ImportedAudiobookTrack, destination: Path) -> None:
    source = _resolve_library_path(track.audio_file_path)
    if source is None or not source.is_file():
        raise ValueError(f"Audio source for track {track.title!r} is missing.")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to prepare audiobook transcription clips.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-v",
        "error",
        "-ss",
        f"{track.source_start_ms / 1000:.3f}",
        "-i",
        str(source),
        "-t",
        f"{track.duration_ms / 1000:.3f}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-compression_level",
        "8",
        "-y",
        str(destination),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await process.communicate()
    if process.returncode:
        message = stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Could not prepare {track.title!r} for transcription: {message}")


def _normalized_cache_language(language: str | None) -> str | None:
    value = (language or "").strip().casefold()
    return None if not value or value == "auto" else value


def _normalized_service_root(base_url: str | None) -> str | None:
    value = (base_url or "").strip().rstrip("/")
    if value.endswith("/transcribe"):
        value = value[: -len("/transcribe")]
    return value or None


def _transcript_cache_matches(
    payload: Mapping[str, object],
    provider: str,
    model: str | None,
    language: str | None,
    service_root: str | None,
) -> bool:
    return (
        payload.get("provider") == provider
        and payload.get("model") == model
        and payload.get("request_language") == _normalized_cache_language(language)
        and payload.get("service_root") == _normalized_service_root(service_root)
        and isinstance(payload.get("words"), list)
    )


def _read_transcript_cache(
    path: Path,
    provider: str,
    model: str | None,
    language: str | None,
    service_root: str | None,
) -> TranscriptResult | None:
    if not path.is_file():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not _transcript_cache_matches(payload, provider, model, language, service_root):
            return None
        return TranscriptResult(
            language=payload.get("language"),
            duration_ms=int(payload["duration_ms"]),
            words=[TranscriptWord(**word) for word in payload["words"]],
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Ignoring invalid audiobook transcript cache at %s.", path)
        return None


def _write_transcript_cache(
    path: Path,
    result: TranscriptResult,
    provider: str,
    model: str | None,
    language: str | None,
    service_root: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": provider,
        "model": model,
        "request_language": _normalized_cache_language(language),
        "service_root": _normalized_service_root(service_root),
        "language": result.language,
        "duration_ms": result.duration_ms,
        "words": [asdict(word) for word in result.words],
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _transcription_cache_config(settings: ProviderSettings) -> tuple[str, str | None, str | None, str | None]:
    """Fingerprint the whole ordered pool because any endpoint may do the work."""
    if settings.transcription_endpoints is None:
        return (
            transcription_provider_name(settings),
            settings.transcription_model,
            settings.transcription_language,
            settings.transcription_base_url,
        )
    signature = json.dumps(
        [
            {
                "provider": endpoint.get("provider"),
                "base_url": endpoint.get("base_url"),
                "model": endpoint.get("model"),
                "language": endpoint.get("language"),
            }
            for endpoint in configured_endpoints(settings, "transcription")
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return "endpoint-pool", signature, None, None


async def _sentences_for_track(track: ImportedAudiobookTrack, db: AsyncSession) -> list[AudiobookSentence]:
    if track.matched_chapter_id is None:
        return []
    return await sentences_for_logical_chapter(track.matched_chapter_id, db)


async def _continuation_sentence_batches(
    track: ImportedAudiobookTrack,
    next_track: ImportedAudiobookTrack | None,
    db: AsyncSession,
) -> list[list[AudiobookSentence]]:
    """Return intervening logical groups before the next matched audio track."""
    if track.matched_chapter_id is None or next_track is None or next_track.matched_chapter_id is None:
        return []
    primary = await db.get(AudiobookChapter, track.matched_chapter_id)
    boundary = await db.get(AudiobookChapter, next_track.matched_chapter_id)
    if (
        primary is None
        or boundary is None
        or primary.book_id != boundary.book_id
        or primary.spine_order is None
        or boundary.spine_order is None
        or boundary.spine_order <= primary.spine_order
    ):
        return []

    current_group_filter = [AudiobookChapter.id == primary.id]
    if primary.logical_chapter_key:
        current_group_filter = [
            AudiobookChapter.book_id == primary.book_id,
            AudiobookChapter.logical_chapter_key == primary.logical_chapter_key,
        ]
    current_end = await db.scalar(
        select(AudiobookChapter.spine_order)
        .where(*current_group_filter)
        .order_by(AudiobookChapter.spine_order.desc())
        .limit(1)
    )
    if current_end is None:
        return []
    result = await db.execute(
        select(AudiobookChapter)
        .where(
            AudiobookChapter.book_id == primary.book_id,
            AudiobookChapter.spine_order > current_end,
            AudiobookChapter.spine_order < boundary.spine_order,
        )
        .order_by(AudiobookChapter.spine_order)
    )
    batches = []
    seen_groups: set[str] = set()
    for chapter in result.scalars().all():
        group_key = chapter.logical_chapter_key or f"chapter-{chapter.id}"
        if group_key in seen_groups:
            continue
        seen_groups.add(group_key)
        sentences = await sentences_for_logical_chapter(chapter.id, db)
        if sentences:
            batches.append(sentences)
    return batches


async def process_alignment(edition_id: int, db: AsyncSession) -> None:
    """Transcribe and align every matched track in one imported edition."""
    edition = await db.get(ImportedAudiobook, edition_id)
    if edition is None:
        return
    settings = await crud.audiobook.get_audiobook_settings(db)
    provider = transcription_provider_name(settings)
    if settings is None or provider == "none":
        transition_state(
            edition,
            "status",
            IMPORTED_AUDIOBOOK,
            ImportedAudiobookStatus.READY,
            context=f"imported audiobook {edition.id}",
        )
        edition.alignment_error = "Configure a transcription provider in Audio Settings first."
        edition.progress_detail = "Timestamp alignment not configured"
        await db.commit()
        return

    result = await db.execute(
        select(ImportedAudiobookTrack)
        .where(
            ImportedAudiobookTrack.imported_audiobook_id == edition.id,
            ImportedAudiobookTrack.matched_chapter_id.is_not(None),
        )
        .order_by(ImportedAudiobookTrack.sequence_order)
    )
    tracks = list(result.scalars().all())
    transition_state(
        edition,
        "status",
        IMPORTED_AUDIOBOOK,
        ImportedAudiobookStatus.ALIGNING,
        context=f"imported audiobook {edition.id}",
    )
    edition.alignment_error = None
    edition.progress_current = 0
    edition.progress_total = len(tracks)
    edition.progress_detail = "Preparing timestamp alignment"
    await db.commit()

    try:
        scores = []
        edition_dir = imported_audiobook_dir(edition.book_id, edition.id)
        cache_provider, cache_model, cache_language, cache_root = _transcription_cache_config(settings)
        for index, track in enumerate(tracks, start=1):
            edition.progress_detail = f"Transcribing {track.title} ({index} of {len(tracks)})"
            await db.commit()

            cache_path = edition_dir / "alignment" / "transcripts" / f"track-{track.id}.json.gz"
            transcript = _read_transcript_cache(
                cache_path,
                cache_provider,
                cache_model,
                cache_language,
                cache_root,
            )
            if transcript is None:
                clip_path = edition_dir / "alignment" / "clips" / f"track-{track.id}.flac"
                await _extract_track_clip(track, clip_path)
                try:
                    transcript = await transcribe_file(settings, clip_path)
                finally:
                    clip_path.unlink(missing_ok=True)
                _write_transcript_cache(
                    cache_path,
                    transcript,
                    cache_provider,
                    cache_model,
                    cache_language,
                    cache_root,
                )
            track.transcript_file_path = relative_library_path(cache_path)

            sentences = await _sentences_for_track(track, db)
            if not sentences:
                raise ValueError(f"Matched chapter for {track.title!r} contains no synchronized text.")
            alignment = align_transcript_to_sentences(
                [(sentence.id, sentence.original_text) for sentence in sentences],
                transcript.words,
                duration_ms=track.duration_ms,
                source_start_ms=track.source_start_ms,
            )
            next_track = tracks[index] if index < len(tracks) else None
            for continuation in await _continuation_sentence_batches(track, next_track, db):
                candidate_sentences = [*sentences, *continuation]
                candidate = align_transcript_to_sentences(
                    [(sentence.id, sentence.original_text) for sentence in candidate_sentences],
                    transcript.words,
                    duration_ms=track.duration_ms,
                    source_start_ms=track.source_start_ms,
                )
                if not _continuation_improves_alignment(alignment, candidate, track.duration_ms):
                    break
                sentences = candidate_sentences
                alignment = candidate
            await db.execute(delete(ImportedAudiobookCue).where(ImportedAudiobookCue.track_id == track.id))
            db.add_all(
                [
                    ImportedAudiobookCue(
                        track_id=track.id,
                        sentence_id=cue.sentence_id,
                        sequence_order=cue.sequence_order,
                        clip_begin_ms=cue.clip_begin_ms,
                        clip_end_ms=cue.clip_end_ms,
                        confidence=cue.confidence,
                        method=cue.method,
                    )
                    for cue in alignment.cues
                ]
            )
            track.alignment_score = alignment.score
            scores.append(alignment.score)
            edition.progress_current = index
            await db.commit()

        average_score = sum(scores) / max(1, len(scores))
        transition_state(
            edition,
            "status",
            IMPORTED_AUDIOBOOK,
            ImportedAudiobookStatus.READY,
            context=f"imported audiobook {edition.id}",
        )
        transition_state(
            edition,
            "alignment_method",
            ALIGNMENT_METHOD,
            AlignmentMethod.TRANSCRIBED if average_score >= 0.65 else AlignmentMethod.HYBRID,
            context=f"imported audiobook {edition.id}",
        )
        edition.progress_current = len(tracks)
        edition.progress_total = len(tracks)
        edition.progress_detail = f"Timestamp alignment ready ({average_score:.0%} confidence)"
        edition.alignment_error = None
        await db.commit()
        shutil.rmtree(edition_dir / "alignment" / "clips", ignore_errors=True)
    except Exception as exc:
        logger.exception("Audiobook timestamp alignment %s failed.", edition_id)
        await db.rollback()
        edition = await db.get(ImportedAudiobook, edition_id)
        if edition is not None:
            transition_state(
                edition,
                "status",
                IMPORTED_AUDIOBOOK,
                ImportedAudiobookStatus.READY,
                context=f"imported audiobook {edition.id}",
            )
            edition.alignment_error = str(exc)
            edition.progress_detail = "Timestamp alignment failed; estimated cues retained where available"
            await db.commit()
