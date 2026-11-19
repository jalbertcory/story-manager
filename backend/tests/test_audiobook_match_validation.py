"""Keep incomplete or misordered narration out of synchronized playback."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app.models import (
    AudiobookChapter,
    AudiobookSentence,
    AudiobookSettings,
    Book,
    ImportedAudiobook,
    ImportedAudiobookTrack,
    ProcessingJob,
)
from backend.app.routers import audiobook_imports, reader
from backend.app.services import audiobook_alignment, audiobook_import, audiobook_views
from backend.app.services.audiobook_match_validation import (
    MATCH_REVIEW_PREFIX,
    MatchValidationError,
    imported_matching_error,
    match_coverage_error,
    record_match_review,
    refresh_match_reviews,
    require_synchronized_text,
)


def _chapters(count=20, *, numbered=True):
    return [
        AudiobookChapter(
            id=i,
            book_id=1,
            chapter_number=i,
            spine_order=i - 1,
            logical_chapter_key=f"chapter-{i}",
            title=f"[ {i} ]" if numbered else f"Scene {i}",
        )
        for i in range(1, count + 1)
    ]


def _tracks(count=20, *, numbered=True):
    return [
        ImportedAudiobookTrack(
            id=i,
            imported_audiobook_id=1,
            sequence_order=i - 1,
            title=f"Chapter {i}" if numbered else f"Scene {i}",
            matched_chapter_id=i,
            duration_ms=1000,
            source_start_ms=0,
            source_end_ms=1000,
            audio_file_path=f"library/track-{i}.m4a",
            media_type="audio/mp4",
        )
        for i in range(1, count + 1)
    ]


def test_rejects_the_sixteen_of_108_reproduction():
    chapters = _chapters(108)
    tracks = _tracks(108)
    for track in tracks[16:]:
        track.matched_chapter_id = None
    error = match_coverage_error(tracks, chapters)
    assert "16 of 108 narration tracks" in error
    assert "16 of 108 logical book chapters" in error
    assert "92 numbered book chapters" in error


def test_all_numbered_chapters_are_required_even_above_count_tolerance():
    tracks = _tracks(100)
    tracks[50].matched_chapter_id = None
    assert "1 numbered book chapters" in match_coverage_error(tracks, _chapters(100))


@pytest.mark.parametrize("mutation", ["reverse", "duplicate", "wrong_book"])
def test_equal_counts_do_not_hide_bad_matches(mutation):
    tracks = _tracks()
    if mutation == "reverse":
        tracks[4].matched_chapter_id, tracks[5].matched_chapter_id = 6, 5
    elif mutation == "duplicate":
        tracks[5].matched_chapter_id = 5
    else:
        tracks[5].matched_chapter_id = 999
    assert match_coverage_error(tracks, _chapters()) is not None


def test_numbered_audio_cannot_match_front_matter_with_equal_counts():
    chapters = _chapters()
    chapters[5].title = "Copyright"
    assert "different book chapters" in match_coverage_error(_tracks(), chapters)


def test_long_missing_track_fails_despite_sufficient_track_counts():
    tracks = _tracks(20, numbered=False)
    tracks[10].matched_chapter_id = None
    tracks[10].duration_ms = 100_000
    error = match_coverage_error(tracks, _chapters(20, numbered=False))
    assert "narration time" in error
    assert "narration tracks match" not in error


def test_long_missing_book_section_fails_despite_sufficient_chapter_counts():
    tracks = _tracks(20, numbered=False)
    tracks[10].matched_chapter_id = None
    sizes = {i: 10 for i in range(1, 21)}
    sizes[11] = 10_000
    assert "book text is covered" in match_coverage_error(tracks, _chapters(20, numbered=False), sizes)


def test_logical_chapters_and_audio_extras_do_not_inflate_counts():
    chapters = _chapters(2)
    chapters.append(
        AudiobookChapter(
            id=3, book_id=1, chapter_number=3, spine_order=1, logical_chapter_key="chapter-1", title="Continuation"
        )
    )
    tracks = _tracks(2)
    for i, title in enumerate(["Opening Credits", "Closing Credits", "Part II: The next part"], start=3):
        tracks.append(ImportedAudiobookTrack(id=i, sequence_order=i, title=title, duration_ms=4000))
    assert match_coverage_error(tracks, chapters) is None


def test_long_part_track_is_not_treated_as_an_announcement():
    tracks = _tracks(2)
    tracks.append(ImportedAudiobookTrack(id=3, sequence_order=3, title="Part II", duration_ms=100_000))
    assert match_coverage_error(tracks, _chapters(2)) is not None


def test_ten_percent_unnumbered_front_matter_is_allowed():
    assert match_coverage_error(_tracks(18, numbered=False), _chapters(20, numbered=False)) is None


def test_poor_transcript_blocks_playback_but_allows_a_structurally_valid_retry():
    tracks = _tracks()
    tracks[5].alignment_score = 0.49
    assert "less than 50%" in match_coverage_error(tracks, _chapters())
    assert match_coverage_error(tracks, _chapters(), check_transcripts=False) is None


def test_repeated_logical_chapter_requires_disjoint_ordered_cues():
    tracks = _tracks(2, numbered=False)
    tracks[1].matched_chapter_id = 1
    ranges = {1: ((0, 0), (0, 4)), 2: ((0, 5), (0, 8))}
    assert match_coverage_error(tracks, _chapters(1, numbered=False), cue_ranges=ranges) is None
    ranges[2] = ((0, 4), (0, 8))
    assert "repeat a chapter" in match_coverage_error(tracks, _chapters(1, numbered=False), cue_ranges=ranges)


@pytest.mark.parametrize("tracks,chapters", [([], []), ([], _chapters()), (_tracks(), [])])
def test_empty_or_missing_text_fails_closed(tracks, chapters):
    assert match_coverage_error(tracks, chapters) is not None


def _unnarrated_sections():
    """Title pages, contents and part dividers ahead of the narrated chapters."""
    titles = ["THIS INEVITABLE RUIN", "BOOK VII", "AUTHOR", "PUBLISHER", "Section 6", "Section 7", "CONTENTS"]
    titles += [f"[ PART {i} ] TITLE" for i in range(1, 6)]
    return [
        AudiobookChapter(
            id=1000 + i,
            book_id=1,
            chapter_number=1000 + i,
            spine_order=-len(titles) + i,
            logical_chapter_key=f"front-{i}",
            title=title,
        )
        for i, title in enumerate(titles)
    ]


def test_unnarrated_front_matter_does_not_block_a_fully_matched_book():
    # Book 1194: every narrated chapter matched, yet 12 unnarrated pages made
    # it "100 of 112 logical book chapters".
    front = _unnarrated_sections()
    chapters = [*front, *_chapters(100)]
    tracks = _tracks(100)
    for track in tracks:
        track.duration_ms = 600_000
    tracks += [
        ImportedAudiobookTrack(id=201, sequence_order=-3, title="Opening Credits", duration_ms=26_000),
        ImportedAudiobookTrack(id=202, sequence_order=-2, title="Dedication", duration_ms=34_000),
        ImportedAudiobookTrack(id=203, sequence_order=-1, title="Part I: The Ceasefire", duration_ms=4_000),
    ]
    sizes = {chapter.id: 20 for chapter in front} | {i: 20_000 for i in range(1, 101)}

    assert match_coverage_error(tracks, chapters, sizes) is None
    # Without text sizes, section counts remain the fallback safeguard.
    assert "100 of 112 logical book chapters" in match_coverage_error(tracks, chapters)


def _parted_book():
    chapters = [
        AudiobookChapter(id=101, book_id=1, chapter_number=101, spine_order=0, logical_chapter_key="p1", title="PART 1"),
        *_chapters(9),
        AudiobookChapter(id=102, book_id=1, chapter_number=102, spine_order=5, logical_chapter_key="p2", title="PART 2"),
    ]
    for chapter in chapters[1:10]:
        chapter.spine_order = chapter.chapter_number + (0 if chapter.chapter_number <= 5 else 1)
    tracks = _tracks(9)
    tracks.insert(0, ImportedAudiobookTrack(id=101, sequence_order=-1, title="Part I: Arrival", duration_ms=4_000))
    tracks.insert(6, ImportedAudiobookTrack(id=102, sequence_order=4, title="Part II: Departure", duration_ms=4_000))
    for track in tracks[7:]:
        track.sequence_order += 1
    return tracks, chapters


def test_matched_part_announcement_covers_its_divider_page():
    tracks, chapters = _parted_book()
    assert "9 of 11 logical book chapters" in match_coverage_error(tracks, chapters)
    tracks[0].matched_chapter_id, tracks[6].matched_chapter_id = 101, 102
    assert match_coverage_error(tracks, chapters) is None


def test_matched_part_announcement_must_keep_book_order():
    tracks, chapters = _parted_book()
    tracks[0].matched_chapter_id, tracks[6].matched_chapter_id = 102, 101
    assert "run out of book order" in match_coverage_error(tracks, chapters)


async def _seed(db):
    book = Book(id=1, title="Matching safeguard", current_path="library/test.epub")
    edition = ImportedAudiobook(id=1, book_id=1, name="Incomplete", status="ready", alignment_method="estimated")
    chapters = _chapters()
    tracks = _tracks()
    tracks[5].matched_chapter_id = None
    db.add_all([book, edition, *chapters, *tracks])
    await db.commit()
    return book, edition, chapters, tracks


_SYNCHRONIZED_TEXT = [
    audiobook_imports.get_imported_track_cues,
    audiobook_imports.get_imported_track_smil,
    reader.get_reader_human_audiobook_smil,
]
_AUDIO = [audiobook_imports.get_imported_track_audio, reader.get_reader_human_audiobook_audio]


@pytest.mark.asyncio
async def test_editions_needing_review_play_audio_without_synchronized_text(db, monkeypatch, tmp_path):
    _book, edition, _chapters_list, tracks = await _seed(db)
    assert await record_match_review(edition, db)
    await db.commit()
    audio_file = tmp_path / "track.m4a"
    audio_file.write_bytes(b"audio")
    monkeypatch.setattr(audiobook_views, "imported_track_audio_path", lambda _track: audio_file)

    responses = await audiobook_views.list_imported_audiobook_responses(1, db)
    assert responses[0].matching_error == edition.match_review_reason
    assert responses[0].state == "needs_review"
    assert not responses[0].is_reader_default
    assert all(track.smil_url is None for track in responses[0].tracks)
    [listed] = await reader.get_reader_human_audiobooks(1, db)
    assert listed.id == edition.id
    assert all(track.smil_url is None for track in listed.tracks)
    for endpoint in _AUDIO:
        assert Path((await endpoint(edition.id, tracks[0].id, db)).path) == audio_file
    for endpoint in _SYNCHRONIZED_TEXT:
        with pytest.raises(HTTPException) as exc:
            await endpoint(edition.id, tracks[0].id, db)
        assert exc.value.status_code == 409
        assert "Chapter matching needs review" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await audiobook_imports.align_imported_audiobook(edition.id, db)
    assert exc.value.status_code == 409
    assert list((await db.scalars(select(ProcessingJob))).all()) == []


@pytest.mark.asyncio
async def test_synchronized_text_checks_matches_before_a_reason_is_recorded(db):
    # Covers editions that have not been revalidated yet.
    _book, edition, _chapters_list, tracks = await _seed(db)
    assert edition.match_review_reason is None
    for endpoint in _SYNCHRONIZED_TEXT:
        with pytest.raises(HTTPException) as exc:
            await endpoint(edition.id, tracks[0].id, db)
        assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_a_recorded_reason_blocks_synchronized_text_until_cleared(db):
    _book, edition, chapters, tracks = await _seed(db)
    tracks[5].matched_chapter_id = chapters[5].id
    edition.match_review_reason = f"{MATCH_REVIEW_PREFIX} Whisper heard a different chapter."
    await db.commit()
    assert await imported_matching_error(edition, db) is None
    with pytest.raises(MatchValidationError, match="Whisper heard a different chapter"):
        await require_synchronized_text(edition, db)
    edition.match_review_reason = None
    await require_synchronized_text(edition, db)


@pytest.mark.asyncio
async def test_refresh_records_review_for_ready_editions_only(db):
    _book, edition, chapters, _tracks_list = await _seed(db)
    repaired = ImportedAudiobook(
        id=2,
        book_id=1,
        name="Repaired",
        status="ready",
        match_review_reason=f"{MATCH_REVIEW_PREFIX} Old reason.",
    )
    importing = ImportedAudiobook(id=3, book_id=1, name="Importing", status="importing")
    other_book = Book(id=2, title="Other", current_path="library/other.epub")
    elsewhere = ImportedAudiobook(id=4, book_id=2, name="Elsewhere", status="ready")
    db.add_all([repaired, importing, other_book, elsewhere])
    for track in _tracks():
        db.add(
            ImportedAudiobookTrack(
                imported_audiobook_id=2,
                sequence_order=track.sequence_order,
                title=track.title,
                matched_chapter_id=track.matched_chapter_id,
                duration_ms=1000,
                source_start_ms=0,
                source_end_ms=1000,
                audio_file_path=f"library/repaired-{track.id}.m4a",
                media_type="audio/mp4",
            )
        )
    await db.commit()

    assert await refresh_match_reviews(db, book_id=1) == (2, 1)
    assert "numbered book chapters" in edition.match_review_reason
    assert repaired.match_review_reason is None
    assert importing.match_review_reason is None
    assert elsewhere.match_review_reason is None
    # Without a book, every ready edition is checked; one with no tracks fails closed.
    assert await refresh_match_reviews(db) == (3, 2)
    assert elsewhere.match_review_reason


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "importing", "stale"])
async def test_running_import_is_not_reported_as_needing_review(db, status):
    # A job rewrites the tracks and records a fresh reason when it finishes,
    # so the reason left from before it started does not describe them.
    db.add_all(
        [
            Book(id=1, title="Import in progress", current_path="library/test.epub"),
            ImportedAudiobook(
                id=1,
                book_id=1,
                name="Importing",
                status=status,
                match_review_reason=f"{MATCH_REVIEW_PREFIX} Old reason.",
            ),
            *_chapters(),
            *_tracks()[:3],
        ]
    )
    await db.commit()
    edition = await db.get(ImportedAudiobook, 1)
    assert edition is not None

    response = await audiobook_views.imported_audiobook_response(edition, db)
    assert response.matching_error is None
    assert response.state == "working"

    edition.status = "ready"
    await db.commit()
    assert (await audiobook_views.imported_audiobook_response(edition, db)).matching_error


@pytest.mark.asyncio
async def test_background_alignment_stops_before_transcribing_bad_matches(db, monkeypatch):
    _book, edition, _chapters_list, _tracks_list = await _seed(db)
    db.add(AudiobookSettings(transcription_provider="whisperx", transcription_base_url="http://whisper:8002"))
    await db.commit()
    extract = AsyncMock()
    monkeypatch.setattr(audiobook_alignment, "_extract_track_clip", extract)
    assert await audiobook_alignment.process_alignment(edition.id, db) == "needs_review"
    assert edition.status == "ready"
    assert "numbered book chapters" in edition.match_review_reason
    # A review is not a Whisper failure, so repairing the matches leaves nothing to retry.
    assert edition.alignment_error is None
    extract.assert_not_called()


@pytest.mark.asyncio
async def test_manual_repairs_clear_the_review(db):
    _book, edition, chapters, tracks = await _seed(db)
    for chapter in chapters:
        db.add(
            AudiobookSentence(
                chapter_id=chapter.id, html_element_id=f"s-{chapter.id}", sequence_order=0, original_text="A sentence."
            )
        )
    await db.commit()
    assert await record_match_review(edition, db)
    await db.commit()
    await audiobook_import.rematch_track(tracks[5], chapters[5].id, db)
    assert edition.status == "ready"
    assert edition.match_review_reason is None
    assert edition.progress_detail == "Chapter matching repaired"
    assert await imported_matching_error(edition, db) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["rematch_imported_audiobook", "rebuild_imported_audiobook"])
async def test_rebuild_and_rematch_record_incomplete_matches_for_review(db, monkeypatch, operation):
    _book, edition, chapters, tracks = await _seed(db)
    tracks[5].title = "Unrecognized track"
    edition.source_manifest_sha256 = "a" * 64
    edition.derived_format_version = audiobook_import.CURRENT_DERIVED_FORMAT_VERSION
    edition.pipeline_version = audiobook_import.CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION
    await db.commit()
    monkeypatch.setattr(audiobook_import, "ensure_span_anchored_text", AsyncMock(return_value=chapters))
    await getattr(audiobook_import, operation)(edition.id, db)
    assert edition.status == "ready"
    assert edition.error is None
    assert edition.match_review_reason.startswith(MATCH_REVIEW_PREFIX)
    assert edition.progress_detail == "Ready to play; chapter matching needs review"


@pytest.mark.asyncio
async def test_rematch_keeps_manual_corrections(db, monkeypatch):
    _book, edition, chapters, tracks = await _seed(db)
    tracks[5].title = "Unrecognized track"
    tracks[5].matched_chapter_id = chapters[5].id
    tracks[5].match_method = "manual"
    tracks[6].matched_chapter_id = None
    tracks[6].match_method = "automatic"
    await db.commit()
    monkeypatch.setattr(audiobook_import, "ensure_span_anchored_text", AsyncMock(return_value=chapters))

    assert await audiobook_import.rematch_imported_audiobook(edition.id, db) == 20
    assert (tracks[5].matched_chapter_id, tracks[5].match_method) == (chapters[5].id, "manual")
    assert (tracks[6].matched_chapter_id, tracks[6].match_method) == (chapters[6].id, "automatic")
    assert edition.status == "ready"
    assert edition.match_review_reason is None


@pytest.mark.asyncio
async def test_retry_reimports_a_failed_import(db):
    _book, edition, _chapters_list, _tracks_list = await _seed(db)
    edition.status = "error"
    edition.error = "Could not read the uploaded audio."
    await db.commit()

    await audiobook_imports.retry_imported_audiobook(edition.id, db)

    assert (edition.status, edition.error) == ("queued", None)
    assert [job.job_type for job in (await db.scalars(select(ProcessingJob))).all()] == ["import_audiobook"]


@pytest.mark.asyncio
async def test_matches_cannot_be_changed_while_alignment_is_running(db):
    _book, edition, chapters, tracks = await _seed(db)
    edition.status = "aligning"
    await db.commit()
    from backend.app.audiobook_schemas import ImportedTrackMatchUpdate

    with pytest.raises(HTTPException) as exc:
        await audiobook_imports.match_imported_track(
            edition.id, tracks[5].id, ImportedTrackMatchUpdate(chapter_id=chapters[5].id), db
        )
    assert exc.value.status_code == 409
    assert tracks[5].matched_chapter_id is None


@pytest.mark.asyncio
async def test_audio_only_books_are_still_available(db):
    book, edition, _chapters_list, _tracks_list = await _seed(db)
    book.current_path = None
    await db.commit()
    assert await imported_matching_error(edition, db) is None
    assert (await audiobook_views.list_imported_audiobook_responses(1, db))[0].is_reader_default
