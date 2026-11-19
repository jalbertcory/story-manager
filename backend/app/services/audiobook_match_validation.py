"""Fail closed when imported audio cannot safely follow the book's order."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..lifecycle import ImportedAudiobookStatus
from ..models import AudiobookChapter, AudiobookSentence, Book, ImportedAudiobook, ImportedAudiobookCue, ImportedAudiobookTrack
from .audiobook_chapter_titles import chapter_identity, numbered_title

MIN_MATCH_COVERAGE = 0.90
MIN_AUDIO_COVERAGE = 0.95
MIN_TRANSCRIPT_MATCH = 0.50
MATCH_REVIEW_PREFIX = "Chapter matching needs review."
_REFRESH_BATCH = 25
_CREDITS = re.compile(r"^(?:opening|closing|end)\s+credits?\b", re.IGNORECASE)
_PART = re.compile(r"^\[?\s*part\s+(?:[ivxlcdm]+|\d+)\b", re.IGNORECASE)


class MatchValidationError(ValueError):
    """Chapter matching needs review before synchronized text or alignment is safe."""


def is_match_review_error(message: str | None) -> bool:
    """Whether an error message is a match-safety block that only a person can clear."""
    return bool(message and message.startswith(MATCH_REVIEW_PREFIX))


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

    Credits and short part announcements are audio extras: they need no match,
    but a match they do have covers its text and must keep book order. Physical
    EPUB files belonging to the same logical chapter count once. All numbered
    chapters must match, even when a missing chapter would fit within the
    coverage tolerance.

    Book coverage is weighed by text when ``chapter_sizes`` is known. Counting
    sections would let unnarrated title pages, contents and part dividers block
    an audiobook whose every chapter matches; counting is the fallback when
    sizes are unavailable.
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
    placed = [track for track in tracks if track.matched_chapter_id in by_id]
    covered = {_group(by_id[track.matched_chapter_id]) for track in placed if track.matched_chapter_id is not None}
    duration = sum(max(0, track.duration_ms) for track in narration)
    matched_duration = sum(max(0, track.duration_ms) for track in matched)
    total_text = sum((chapter_sizes or {}).get(chapter.id, 0) for chapter in chapters)
    reasons = []
    if not narration or not groups or not matched:
        reasons.append("No complete audio-to-text match is available.")
    else:
        if len(matched) / len(narration) < MIN_MATCH_COVERAGE:
            reasons.append(f"Only {len(matched)} of {len(narration)} narration tracks match (90% required).")
        if not total_text and len(covered) / len(groups) < MIN_MATCH_COVERAGE:
            reasons.append(f"Only {len(covered)} of {len(groups)} logical book chapters match (90% required).")
        if duration and matched_duration / duration < MIN_AUDIO_COVERAGE:
            reasons.append(f"Only {matched_duration / duration:.0%} of narration time matches (95% required).")
    if chapter_sizes and total_text:
        matched_text = sum(chapter_sizes.get(chapter.id, 0) for chapter in chapters if _group(chapter) in covered)
        if matched_text / total_text < MIN_MATCH_COVERAGE:
            reasons.append(f"Only {matched_text / total_text:.0%} of book text is covered (90% required).")
    # A leading number before a subtitle ("02 - The Door") may be a track or
    # file index, so only stated chapter numbers are held to these two checks.
    numbered = {
        _group(chapter) for chapter in chapters if (number := numbered_title(chapter.title)) is not None and not number.indexed
    }
    missing_numbered = len(numbered - covered)
    if missing_numbered:
        reasons.append(f"{missing_numbered} numbered book chapters have no audio match.")
    seen = set()
    previous_position = -1
    previous_track: ImportedAudiobookTrack | None = None
    for track in sorted(placed, key=lambda item: item.sequence_order):
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
        (number := numbered_title(track.title)) is not None
        and not number.indexed
        and track.matched_chapter_id is not None
        and chapter_identity(track.title) != chapter_identity(by_id[track.matched_chapter_id].title)
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
        f"{MATCH_REVIEW_PREFIX} " + " ".join(reasons) + " Alignment and synchronized playback are blocked. "
        "Review track matching or rematch the book text; the original audio is preserved."
    )


async def imported_matching_errors(
    editions: Sequence[ImportedAudiobook],
    db: AsyncSession,
    *,
    tracks_by_edition: Mapping[int, Sequence[ImportedAudiobookTrack]] | None = None,
    check_transcripts: bool = True,
) -> dict[int, str | None]:
    """Check many editions' chapter matches with a fixed number of queries."""
    results: dict[int, str | None] = {edition.id: None for edition in editions}
    if not editions:
        return results
    books = {
        book.id: book
        for book in (await db.scalars(select(Book).where(Book.id.in_({edition.book_id for edition in editions})))).all()
    }
    # Audio-only books have no text to synchronize.
    checked = [edition for edition in editions if (book := books.get(edition.book_id)) is None or book.current_path]
    if not checked:
        return results
    book_ids = {edition.book_id for edition in checked}
    if tracks_by_edition is None:
        loaded: dict[int, list[ImportedAudiobookTrack]] = {edition.id: [] for edition in checked}
        for track in (
            await db.scalars(
                select(ImportedAudiobookTrack).where(
                    ImportedAudiobookTrack.imported_audiobook_id.in_([edition.id for edition in checked])
                )
            )
        ).all():
            loaded[track.imported_audiobook_id].append(track)
        tracks_by_edition = loaded
    chapters_by_book: dict[int, list[AudiobookChapter]] = {book_id: [] for book_id in book_ids}
    for chapter in (await db.scalars(select(AudiobookChapter).where(AudiobookChapter.book_id.in_(book_ids)))).all():
        chapters_by_book[chapter.book_id].append(chapter)
    sizes_by_book: dict[int, dict[int, int]] = {book_id: {} for book_id in book_ids}
    for book_id, chapter_id, size in (
        await db.execute(
            select(
                AudiobookChapter.book_id,
                AudiobookSentence.chapter_id,
                func.sum(func.length(AudiobookSentence.original_text)),
            )
            .join(AudiobookChapter)
            .where(AudiobookChapter.book_id.in_(book_ids))
            .group_by(AudiobookChapter.book_id, AudiobookSentence.chapter_id)
        )
    ).all():
        sizes_by_book[book_id][chapter_id] = int(size or 0)
    # Existing editions can legitimately split one text chapter over multiple
    # audio tracks. Permit that only with non-overlapping, ordered sentence cues.
    chapter_by_id = {chapter.id: chapter for chapters in chapters_by_book.values() for chapter in chapters}
    duplicate_ids: list[int] = []
    for edition in checked:
        group_tracks: dict[str, list[int]] = {}
        for track in tracks_by_edition.get(edition.id, ()):
            matched = chapter_by_id.get(track.matched_chapter_id) if track.matched_chapter_id is not None else None
            if matched is not None and matched.book_id == edition.book_id:
                group_tracks.setdefault(_group(matched), []).append(track.id)
        duplicate_ids.extend(track_id for ids in group_tracks.values() if len(ids) > 1 for track_id in ids)
    cue_ranges: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {}
    if duplicate_ids:
        rows = await db.execute(
            select(ImportedAudiobookCue.track_id, AudiobookSentence.chapter_id, AudiobookSentence.sequence_order)
            .join(AudiobookSentence, ImportedAudiobookCue.sentence_id == AudiobookSentence.id)
            .where(ImportedAudiobookCue.track_id.in_(duplicate_ids))
        )
        for track_id, chapter_id, sequence in rows:
            cue_chapter = chapter_by_id.get(chapter_id)
            if cue_chapter is None:
                continue
            point = (
                cue_chapter.spine_order if cue_chapter.spine_order is not None else cue_chapter.chapter_number,
                sequence,
            )
            start, end = cue_ranges.get(track_id, (point, point))
            cue_ranges[track_id] = min(start, point), max(end, point)
    for edition in checked:
        # A retry may improve poor transcripts. Structural coverage still has to pass.
        results[edition.id] = match_coverage_error(
            tracks_by_edition.get(edition.id, ()),
            chapters_by_book[edition.book_id],
            sizes_by_book[edition.book_id],
            check_transcripts=check_transcripts,
            cue_ranges=cue_ranges,
        )
    return results


async def imported_matching_error(
    edition: ImportedAudiobook,
    db: AsyncSession,
    *,
    tracks: Sequence[ImportedAudiobookTrack] | None = None,
    check_transcripts: bool = True,
) -> str | None:
    errors = await imported_matching_errors(
        [edition],
        db,
        tracks_by_edition=None if tracks is None else {edition.id: tracks},
        check_transcripts=check_transcripts,
    )
    return errors[edition.id]


async def require_safe_matches(edition: ImportedAudiobook, db: AsyncSession, *, check_transcripts: bool = True) -> None:
    error = await imported_matching_error(edition, db, check_transcripts=check_transcripts)
    if error:
        raise MatchValidationError(error)


MATCH_REVIEW_PROGRESS = "Ready to play; chapter matching needs review"
MATCH_REPAIRED_PROGRESS = "Chapter matching repaired"


async def record_match_review(edition: ImportedAudiobook, db: AsyncSession) -> str | None:
    """Check an edition's chapter matches and store why they need review, if they do.

    The audio stays playable either way; the stored reason blocks only
    synchronized text and alignment. The caller commits.
    """
    reason = await imported_matching_error(edition, db)
    edition.match_review_reason = reason
    return reason


async def require_synchronized_text(edition: ImportedAudiobook, db: AsyncSession) -> None:
    """Refuse cues and SMIL while chapter matches need review.

    The stored reason keeps every view in agreement; the live check still
    guards against chapter changes that no writer has recorded yet.
    """
    if edition.match_review_reason:
        raise MatchValidationError(edition.match_review_reason)
    await require_safe_matches(edition, db)


async def refresh_match_reviews(db: AsyncSession, *, book_id: int | None = None) -> tuple[int, int]:
    """Recheck ready editions' chapter matches and store the result.

    Covers editions whose book text changed without a rematch and editions
    from before the reason was stored. Returns how many were checked and how
    many need review.
    """
    query = select(ImportedAudiobook.id).where(ImportedAudiobook.status == ImportedAudiobookStatus.READY.value)
    if book_id is not None:
        query = query.where(ImportedAudiobook.book_id == book_id)
    edition_ids = list((await db.scalars(query.order_by(ImportedAudiobook.id))).all())
    flagged = 0
    for start in range(0, len(edition_ids), _REFRESH_BATCH):
        batch = edition_ids[start:][:_REFRESH_BATCH]
        editions = list(
            (
                await db.scalars(
                    select(ImportedAudiobook)
                    .where(
                        ImportedAudiobook.id.in_(batch),
                        # Skip editions a job picked up since the ids were read.
                        ImportedAudiobook.status == ImportedAudiobookStatus.READY.value,
                    )
                    .order_by(ImportedAudiobook.id)
                    # A manual rematch or rebuild that commits while this batch
                    # is being checked would otherwise be overwritten with a
                    # reason computed from the matches it replaced.
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        reasons = await imported_matching_errors(editions, db)
        for edition in editions:
            reason = reasons[edition.id]
            if reason != edition.match_review_reason:
                edition.progress_detail = MATCH_REVIEW_PROGRESS if reason else MATCH_REPAIRED_PROGRESS
            edition.match_review_reason = reason
            flagged += int(reason is not None)
        await db.commit()
    return len(edition_ids), flagged
