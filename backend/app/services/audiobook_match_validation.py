"""Fail closed when imported audio cannot safely follow the book's order."""

from __future__ import annotations

import re
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AudiobookChapter, AudiobookSentence, Book, ImportedAudiobook, ImportedAudiobookCue, ImportedAudiobookTrack
from .audiobook_chapter_titles import chapter_identity

MIN_MATCH_COVERAGE = 0.90
MIN_AUDIO_COVERAGE = 0.95
MIN_TRANSCRIPT_MATCH = 0.50
_CREDITS = re.compile(r"^(?:opening|closing|end)\s+credits?\b", re.IGNORECASE)
_PART = re.compile(r"^\[?\s*part\s+(?:[ivxlcdm]+|\d+)\b", re.IGNORECASE)


class MatchValidationError(ValueError):
    """Chapter matching needs review before alignment or playback is safe."""


def _group(chapter: AudiobookChapter) -> str:
    return chapter.logical_chapter_key or f"chapter-{chapter.id}"


def match_coverage_error(
    tracks: Sequence[ImportedAudiobookTrack],
    chapters: Sequence[AudiobookChapter],
    chapter_sizes: dict[int, int] | None = None,
    *,
    check_transcripts: bool = True,
    cue_ranges: dict[int, tuple[tuple[int, int], tuple[int, int]]] | None = None,
) -> str | None:
    """Compare logical chapters, narration tracks, duration, and reading order.

    Credits and short part announcements are audio extras. Physical EPUB files
    belonging to the same logical chapter count once. All numbered chapters must
    match, even when a missing chapter would fit within the coverage tolerance.
    """
    by_id = {chapter.id: chapter for chapter in chapters}
    groups = {_group(chapter) for chapter in chapters}
    positions: dict[str, int] = {}
    for chapter in chapters:
        position = chapter.spine_order if chapter.spine_order is not None else chapter.chapter_number
        key = _group(chapter)
        positions[key] = min(positions.get(key, position), position)
    narration = [
        track
        for track in tracks
        if not _CREDITS.search(track.title or "") and not (_PART.search(track.title or "") and track.duration_ms <= 30_000)
    ]
    matched = [track for track in narration if track.matched_chapter_id in by_id]
    covered = {_group(by_id[track.matched_chapter_id]) for track in matched if track.matched_chapter_id is not None}
    duration = sum(max(0, track.duration_ms) for track in narration)
    matched_duration = sum(max(0, track.duration_ms) for track in matched)
    reasons = []
    if not narration or not groups or not matched:
        reasons.append("No complete audio-to-text match is available.")
    else:
        if len(matched) / len(narration) < MIN_MATCH_COVERAGE:
            reasons.append(f"Only {len(matched)} of {len(narration)} narration tracks match (90% required).")
        if len(covered) / len(groups) < MIN_MATCH_COVERAGE:
            reasons.append(f"Only {len(covered)} of {len(groups)} logical book chapters match (90% required).")
        if duration and matched_duration / duration < MIN_AUDIO_COVERAGE:
            reasons.append(f"Only {matched_duration / duration:.0%} of narration time matches (95% required).")
    if chapter_sizes:
        total_text = sum(chapter_sizes.get(chapter.id, 0) for chapter in chapters)
        matched_text = sum(chapter_sizes.get(chapter.id, 0) for chapter in chapters if _group(chapter) in covered)
        if total_text and matched_text / total_text < MIN_MATCH_COVERAGE:
            reasons.append(f"Only {matched_text / total_text:.0%} of book text is covered (90% required).")
    numbered = {
        _group(chapter)
        for chapter in chapters
        if (identity := chapter_identity(chapter.title)) is not None and identity[0] == "chapter"
    }
    missing_numbered = len(numbered - covered)
    if missing_numbered:
        reasons.append(f"{missing_numbered} numbered book chapters have no audio match.")
    seen = set()
    previous_position = -1
    previous_track: ImportedAudiobookTrack | None = None
    for track in sorted(matched, key=lambda item: item.sequence_order):
        assert track.matched_chapter_id is not None
        chapter = by_id[track.matched_chapter_id]
        key = _group(chapter)
        position = positions[key]
        previous_range = (cue_ranges or {}).get(previous_track.id) if previous_track is not None else None
        current_range = (cue_ranges or {}).get(track.id)
        is_contiguous_split = (
            position == previous_position
            and previous_range is not None
            and current_range is not None
            and previous_range[1] < current_range[0]
        )
        if (key in seen and not is_contiguous_split) or position < previous_position:
            reasons.append("Audio matches repeat a chapter or run out of book order.")
            break
        seen.add(key)
        previous_position = position
        previous_track = track
    if any(
        (identity := chapter_identity(track.title)) is not None
        and identity[0] == "chapter"
        and track.matched_chapter_id is not None
        and identity != chapter_identity(by_id[track.matched_chapter_id].title)
        for track in matched
    ):
        reasons.append("Numbered audio tracks point to different book chapters.")
    if any(track.matched_chapter_id is not None and track.matched_chapter_id not in by_id for track in tracks):
        reasons.append("Some matches point to missing chapters or a different book.")
    if check_transcripts and any(
        track.alignment_score is not None and track.alignment_score < MIN_TRANSCRIPT_MATCH for track in matched
    ):
        reasons.append("Whisper found less than 50% text agreement for one or more tracks.")
    if not reasons:
        return None
    return (
        "Chapter matching needs review. " + " ".join(reasons) + " Alignment and synchronized playback are blocked. "
        "Review track matching or rematch the book text; the original audio is preserved."
    )


async def imported_matching_error(
    edition: ImportedAudiobook,
    db: AsyncSession,
    *,
    tracks: Sequence[ImportedAudiobookTrack] | None = None,
    check_transcripts: bool = True,
) -> str | None:
    book = await db.get(Book, edition.book_id)
    if book is not None and not book.current_path:
        return None  # Audio-only books have no text to synchronize.
    if tracks is None:
        tracks = list(
            (
                await db.scalars(
                    select(ImportedAudiobookTrack).where(ImportedAudiobookTrack.imported_audiobook_id == edition.id)
                )
            ).all()
        )
    chapters = list((await db.scalars(select(AudiobookChapter).where(AudiobookChapter.book_id == edition.book_id))).all())
    sizes = dict(
        (
            await db.execute(
                select(AudiobookSentence.chapter_id, func.sum(func.length(AudiobookSentence.original_text)))
                .join(AudiobookChapter)
                .where(AudiobookChapter.book_id == edition.book_id)
                .group_by(AudiobookSentence.chapter_id)
            )
        ).all()
    )
    # Existing editions can legitimately split one text chapter over multiple
    # audio tracks. Permit that only with non-overlapping, ordered sentence cues.
    by_id = {chapter.id: chapter for chapter in chapters}
    group_tracks: dict[str, list[int]] = {}
    for track in tracks:
        chapter = by_id.get(track.matched_chapter_id) if track.matched_chapter_id is not None else None
        if chapter is not None:
            group_tracks.setdefault(_group(chapter), []).append(track.id)
    duplicate_ids = [track_id for ids in group_tracks.values() if len(ids) > 1 for track_id in ids]
    cue_ranges: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {}
    if duplicate_ids:
        rows = await db.execute(
            select(ImportedAudiobookCue.track_id, AudiobookSentence.chapter_id, AudiobookSentence.sequence_order)
            .join(AudiobookSentence, ImportedAudiobookCue.sentence_id == AudiobookSentence.id)
            .where(ImportedAudiobookCue.track_id.in_(duplicate_ids))
        )
        for track_id, chapter_id, sequence in rows:
            chapter = by_id.get(chapter_id)
            if chapter is None:
                continue
            point = (chapter.spine_order if chapter.spine_order is not None else chapter.chapter_number, sequence)
            start, end = cue_ranges.get(track_id, (point, point))
            cue_ranges[track_id] = min(start, point), max(end, point)
    # A retry may improve poor transcripts. Structural coverage still has to pass.
    return match_coverage_error(tracks, chapters, sizes, check_transcripts=check_transcripts, cue_ranges=cue_ranges)


async def require_safe_matches(edition: ImportedAudiobook, db: AsyncSession, *, check_transcripts: bool = True) -> None:
    error = await imported_matching_error(edition, db, check_transcripts=check_transcripts)
    if error:
        raise MatchValidationError(error)
