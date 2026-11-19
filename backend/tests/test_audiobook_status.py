"""One state and next step per audiobook source, and the library-wide overview."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select
from backend.app import crud

from backend.app.models import (
    AudiobookChapter,
    AudiobookSettings,
    Book,
    ImportedAudiobook,
    ImportedAudiobookTrack,
    ProcessingJob,
)
from backend.app.routers import audiobook_imports, dashboard, processing
from backend.app.services import audiobook_import, audiobook_views
from backend.app.services.audiobook_import import CURRENT_DERIVED_FORMAT_VERSION, CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION
from backend.app.services.audiobook_match_validation import MATCH_REVIEW_PREFIX
from backend.app.services.audiobook_status import audiobook_overview, human_edition_status, tts_status

_CURRENT = {
    "status": "ready",
    "alignment_method": "estimated",
    "source_manifest_sha256": "a" * 64,
    "derived_format_version": CURRENT_DERIVED_FORMAT_VERSION,
    "pipeline_version": CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION,
    "matched_content_version": 1,
}
_REVIEW = f"{MATCH_REVIEW_PREFIX} Only 3 of 20 narration tracks match."


def _edition(**fields):
    return ImportedAudiobook(book_id=1, name="Edition", source_type="upload", **{**_CURRENT, **fields})


@pytest.mark.parametrize(
    ("fields", "context", "state", "label", "action"),
    [
        ({"status": "queued"}, {}, "working", "Queued", None),
        ({"status": "importing"}, {}, "working", "Importing", None),
        ({"status": "stale"}, {}, "working", "Rematching", None),
        ({"status": "aligning"}, {}, "working", "Running Whisper", None),
        # A failed import stays retryable even when it wrote some tracks.
        ({"status": "error", "error": "ffprobe failed"}, {}, "import_failed", "Import failed", "retry_import"),
        ({"status": "error", "error": None}, {}, "import_failed", "Import failed", "retry_import"),
        # A match block leaves the edition ready, so an error is an import
        # that never produced tracks.
        ({"status": "error", "error": _REVIEW}, {}, "import_failed", "Import failed", "retry_import"),
        ({"match_review_reason": _REVIEW}, {"has_epub": False}, "audio_only", "Audio only", None),
        ({"match_review_reason": _REVIEW}, {}, "needs_review", "Needs match review", "review_matches"),
        ({"status": "aligning", "match_review_reason": _REVIEW}, {}, "working", "Running Whisper", None),
        ({"pipeline_version": 2}, {}, "outdated", "Needs rebuild", "rebuild"),
        ({"derived_format_version": 0}, {}, "outdated", "Needs rebuild", "rebuild"),
        ({"source_manifest_sha256": None}, {}, "outdated", "Needs rebuild", "rebuild"),
        ({}, {"content_version": 2}, "outdated", "Needs rebuild", "rebuild"),
        ({"matched_content_version": None}, {"content_version": 2}, "ready_estimated", "Human audio", "improve_with_whisper"),
        ({"alignment_error": "Whisper timed out"}, {}, "whisper_failed", "Whisper failed", "retry_whisper"),
        (
            {"alignment_error": "Configure a transcription provider in Audio Settings first."},
            {"transcription_configured": False},
            "ready_estimated",
            "Human audio",
            "set_up_transcription",
        ),
        ({"alignment_method": "transcribed"}, {}, "ready_whisper", "Human audio + Whisper", None),
        ({"alignment_method": "hybrid"}, {}, "ready_whisper", "Human audio + Whisper", None),
        ({}, {}, "ready_estimated", "Human audio", "improve_with_whisper"),
        ({}, {"transcription_configured": False}, "ready_estimated", "Human audio", "set_up_transcription"),
    ],
)
def test_human_edition_states(fields, context, state, label, action):
    options = {"has_epub": True, "content_version": 1, "transcription_configured": True}
    status = human_edition_status(_edition(**fields), **{**options, **context})
    assert (status.state, status.label, status.next_action) == (state, label, action)
    assert (status.action_label is None) == (action is None)


def test_partial_whisper_failure_says_which_timing_was_kept():
    options = {"has_epub": True, "content_version": 1, "transcription_configured": True}
    partial = human_edition_status(_edition(alignment_method="hybrid", alignment_error="Whisper timed out"), **options)
    total = human_edition_status(_edition(alignment_error="Whisper timed out"), **options)

    assert partial.state == total.state == "whisper_failed"
    assert partial.detail == ("Whisper timed out. Tracks Whisper finished keep its timing; the rest use estimated timing.")
    assert total.detail == "Whisper timed out"


@pytest.mark.parametrize(
    ("fields", "job_active", "state", "action"),
    [
        ({"audiobook_enabled": False, "audiobook_pipeline_status": "error"}, False, None, None),
        ({"audiobook_pipeline_status": "error", "audiobook_last_error": "TTS quota"}, True, "tts_failed", "open_generation"),
        ({"audiobook_pipeline_status": "audio_gen"}, True, "tts_running", None),
        ({"audiobook_pipeline_status": "paused"}, False, "tts_paused", "open_generation"),
        # A phase without a queued job stopped after a single step.
        ({"audiobook_pipeline_status": "diarizing"}, False, "tts_paused", "open_generation"),
        ({"audiobook_publication_state": "stale"}, False, "tts_outdated", "open_generation"),
        ({"audiobook_pending_content_version": 3}, False, "tts_outdated", "open_generation"),
        ({"audiobook_pipeline_status": "complete", "audiobook_publication_state": "complete"}, False, "tts_complete", None),
        ({"audiobook_publication_state": "partial"}, False, "tts_partial", "open_generation"),
        ({}, False, "tts_not_started", "open_generation"),
    ],
)
def test_ai_narration_states(fields, job_active, state, action):
    book = Book(title="Book", **{"audiobook_enabled": True, **fields})
    status = tts_status(book, job_active=job_active)
    if state is None:
        assert status is None
    else:
        assert status is not None
        assert (status.state, status.next_action) == (state, action)


def _matched_book(db, book_id: int, title: str, *, method: str = "transcribed", **book_fields):
    """A book whose single edition matches all three numbered chapters."""
    db.add(Book(id=book_id, title=title, author="Author", current_path=f"library/{book_id}.epub", **book_fields))
    edition = ImportedAudiobook(
        id=book_id, book_id=book_id, name=f"{title} audio", source_type="upload", **{**_CURRENT, "alignment_method": method}
    )
    db.add(edition)
    for number in range(1, 4):
        chapter_id = book_id * 100 + number
        db.add(
            AudiobookChapter(
                id=chapter_id,
                book_id=book_id,
                chapter_number=number,
                spine_order=number,
                logical_chapter_key=f"chapter-{number}",
                title=f"Chapter {number}",
            )
        )
        db.add(
            ImportedAudiobookTrack(
                id=chapter_id,
                imported_audiobook_id=book_id,
                sequence_order=number,
                title=f"Chapter {number}",
                matched_chapter_id=chapter_id,
                duration_ms=60_000,
                source_start_ms=0,
                source_end_ms=60_000,
                audio_file_path=f"library/{chapter_id}.m4a",
                media_type="audio/mp4",
            )
        )


async def _seed_library(db):
    db.add(AudiobookSettings(transcription_provider="whisperx", transcription_base_url="http://whisper:8002"))
    _matched_book(db, 1, "Bravo")
    db.add_all(
        [
            # Ready to play, but its chapter matches need review.
            Book(id=2, title="Alpha", author="Author", current_path="library/2.epub"),
            ImportedAudiobook(
                id=2, book_id=2, name="Alpha audio", source_type="upload", match_review_reason=_REVIEW, **_CURRENT
            ),
            Book(id=3, title="Charlie", author="Author", current_path="library/3.epub"),
            ImportedAudiobook(id=3, book_id=3, name="Charlie audio", source_type="upload", status="error", error="Bad file"),
            Book(id=4, title="Delta", author="Author"),
            ImportedAudiobook(id=4, book_id=4, name="Delta audio", source_type="upload", **_CURRENT),
            Book(
                id=5,
                title="Echo",
                author="Author",
                current_path="library/5.epub",
                audiobook_enabled=True,
                audiobook_pipeline_status="error",
                audiobook_last_error="TTS quota exceeded",
            ),
            ImportedAudiobook(id=5, book_id=5, name="Echo audio", source_type="upload", status="queued"),
            Book(id=6, title="Gone", author="Author", deleted_at=datetime.now(timezone.utc)),
            ImportedAudiobook(id=6, book_id=6, name="Gone audio", source_type="upload", status="error"),
            Book(id=7, title="No audio", author="Author", current_path="library/7.epub"),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_overview_lists_every_audio_source_most_urgent_first(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        await _seed_library(db)

    response = app_client.get("/api/audiobooks/overview")

    assert response.status_code == 200
    data = response.json()
    assert data["transcription_configured"] is True
    assert [(row["title"], row["state"]) for row in data["books"]] == [
        ("Charlie", "import_failed"),
        ("Echo", "tts_failed"),
        ("Alpha", "needs_review"),
        ("Bravo", "ready_whisper"),
        ("Delta", "audio_only"),
    ]
    assert data["total_count"] == 5
    assert data["attention_count"] == 3
    echo = data["books"][1]
    assert echo["audio_kind"] == "both"
    assert [(source["kind"], source["state"]) for source in echo["sources"]] == [
        ("tts", "tts_failed"),
        ("human", "working"),
    ]
    assert echo["sources"][0]["state_detail"] == "TTS quota exceeded"
    assert data["books"][0]["sources"][0] == {
        "kind": "human",
        "edition_id": 3,
        "name": "Charlie audio",
        "state": "import_failed",
        "state_label": "Import failed",
        "state_detail": "Bad file",
        "next_action": "retry_import",
        "next_action_label": "Retry import",
        "processing_job_id": None,
        "alignment_method": None,
        "progress_current": 0,
        "progress_total": 0,
        "updated_at": None,
    }
    assert {count["state"]: count["count"] for count in data["counts"]} == {
        "import_failed": 1,
        "tts_failed": 1,
        "needs_review": 1,
        "working": 1,
        "ready_whisper": 1,
        "audio_only": 1,
    }


@pytest.mark.asyncio
async def test_overview_query_count_does_not_grow_with_the_library(db):
    await _seed_library(db)
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args):
        statements.append(statement)

    engine = db.bind.sync_engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        await audiobook_overview(db)
        small = len(statements)
        for book_id in range(10, 20):
            _matched_book(db, book_id, f"Book {book_id}")
        await db.commit()
        statements.clear()
        overview = await audiobook_overview(db)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert overview.total_count == 15
    assert len(statements) == small


@pytest.mark.asyncio
async def test_edition_response_offers_retry_for_failed_import_with_tracks(db):
    _matched_book(db, 1, "Partial import")
    await db.commit()
    edition = await db.get(ImportedAudiobook, 1)
    assert edition is not None
    edition.status = "error"
    edition.error = "Audio extraction failed on track 4"
    await db.commit()

    [response] = await audiobook_views.list_imported_audiobook_responses(1, db)

    assert response.tracks
    assert (response.state, response.next_action) == ("import_failed", "retry_import")
    assert response.state_detail == "Audio extraction failed on track 4"


@pytest.mark.asyncio
async def test_rebuild_one_edition(db):
    _matched_book(db, 1, "Rebuild me")
    db.add(Book(id=2, title="Empty", current_path="library/2.epub"))
    db.add(ImportedAudiobook(id=2, book_id=2, name="Empty", source_type="upload", **_CURRENT))
    await db.commit()
    edition = await db.get(ImportedAudiobook, 1)
    assert edition is not None

    edition.status = "importing"
    await db.commit()
    with pytest.raises(HTTPException) as exc:
        await audiobook_imports.rebuild_imported_audiobook(1, db)
    assert exc.value.status_code == 409

    with pytest.raises(HTTPException) as exc:
        await audiobook_imports.rebuild_imported_audiobook(2, db)
    assert exc.value.status_code == 409
    assert "no imported audio tracks" in exc.value.detail

    edition.status = "ready"
    edition.pipeline_version = 2
    await db.commit()
    response = await audiobook_imports.rebuild_imported_audiobook(1, db)

    assert response.progress_detail == "Human audiobook rebuild queued"
    jobs = list((await db.scalars(select(ProcessingJob))).all())
    assert [(job.job_type, job.target_id) for job in jobs] == [("rebuild_imported_audiobook", 1)]
    assert jobs[0].payload == {"pipeline_version": CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION, "force": True}


@pytest.mark.asyncio
async def test_rebuild_status_tracks_queued_running_and_completed_jobs(db):
    _matched_book(db, 1, "Rebuild me", method="estimated")
    await db.commit()
    edition = await db.get(ImportedAudiobook, 1)
    edition.pipeline_version = 2
    await db.commit()

    response = await audiobook_imports.rebuild_imported_audiobook(1, db)
    job = (await db.scalars(select(ProcessingJob))).one()
    assert response.status == "ready"  # The rebuild worker requires this lifecycle state.
    assert (response.state, response.state_label, response.next_action) == ("working", "Queued", None)
    assert response.processing_job_id == job.id
    overview = await audiobook_overview(db)
    assert overview.books[0].state == "working"
    assert overview.attention_count == 0

    job = await crud.claim_processing_job(db, resource_lane="cpu", lease_owner="test", lease_seconds=60)
    assert job is not None
    await crud.update_processing_job_progress(db, job.id, current=1, total=3, detail="Rebuilt track 1 of 3")
    [response] = await audiobook_views.list_imported_audiobook_responses(1, db)
    source = (await audiobook_overview(db)).books[0].sources[0]
    for result in (response, source):
        assert (result.state, result.state_label, result.next_action) == ("working", "Rebuilding", None)
        assert (result.progress_current, result.progress_total) == (1, 3)
        assert result.state_detail == "Rebuilt track 1 of 3"

    edition.pipeline_version = CURRENT_HUMAN_AUDIOBOOK_PIPELINE_VERSION
    await db.commit()
    await crud.complete_processing_job(db, job.id)
    [response] = await audiobook_views.list_imported_audiobook_responses(1, db)
    assert response.state == "ready_estimated"
    assert (await audiobook_overview(db)).books[0].state == response.state


@pytest.mark.asyncio
async def test_failed_rematch_offers_retry_of_original_job(db, monkeypatch):
    _matched_book(db, 1, "Rematch me")
    await db.commit()
    await audiobook_imports.rematch_imported_audiobook(1, db)
    job = (await db.scalars(select(ProcessingJob))).one()
    job.max_attempts = 1
    await db.commit()
    await crud.claim_processing_job(db, resource_lane="cpu", lease_owner="test", lease_seconds=60)
    monkeypatch.setattr(audiobook_import, "ensure_span_anchored_text", AsyncMock(side_effect=ValueError("EPUB missing")))
    with pytest.raises(ValueError, match="EPUB missing"):
        await audiobook_import.rematch_imported_audiobook(1, db)
    assert await crud.fail_processing_job(db, job.id, "EPUB missing") == "error"

    [response] = await audiobook_views.list_imported_audiobook_responses(1, db)
    overview = await audiobook_overview(db)
    assert response.status == "importing"  # The service failed before clearing the lifecycle phase.
    assert overview.attention_count == 1
    assert (await dashboard._audiobook_problems(db, 10)).count == 1
    for result in (response, overview.books[0].sources[0]):
        assert (result.state, result.next_action, result.processing_job_id) == ("job_failed", "retry_processing", job.id)
        assert result.state_detail == "EPUB missing"

    retried = await processing.retry_processing_job(response.processing_job_id, db)
    assert (retried.id, retried.job_type, retried.status) == (job.id, "rematch_imported_audiobook", "queued")
    assert retried.payload == {"realign": True}
    assert len((await db.scalars(select(ProcessingJob))).all()) == 1
    [response] = await audiobook_views.list_imported_audiobook_responses(1, db)
    assert (response.state, response.next_action) == ("working", None)
    assert (await audiobook_overview(db)).attention_count == 0


@pytest.mark.asyncio
async def test_canceled_job_and_superseded_failure(db):
    _matched_book(db, 1, "Canceled rebuild")
    await db.commit()
    await audiobook_imports.rebuild_imported_audiobook(1, db)
    old = (await db.scalars(select(ProcessingJob))).one()
    await crud.request_processing_job_cancel(db, old.id)
    [response] = await audiobook_views.list_imported_audiobook_responses(1, db)
    assert (response.state, response.state_label, response.next_action) == (
        "job_failed",
        "Processing canceled",
        "retry_processing",
    )

    await audiobook_imports.rebuild_imported_audiobook(1, db)
    newer = (await db.scalars(select(ProcessingJob).order_by(ProcessingJob.id.desc()))).first()
    assert newer.id != old.id
    assert (await audiobook_overview(db)).books[0].state == "working"
    await crud.claim_processing_job(db, resource_lane="cpu", lease_owner="test", lease_seconds=60)
    await crud.complete_processing_job(db, newer.id)
    [response] = await audiobook_views.list_imported_audiobook_responses(1, db)
    assert response.state == "ready_whisper"
    assert (await audiobook_overview(db)).attention_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["canceled", "error"])
async def test_stopped_rematch_of_review_edition_offers_retry(db, outcome):
    # A rematch keeps the stored reason while it runs. If the job stops, the
    # edition must not look like it is still rematching.
    _matched_book(db, 1, "Stopped rematch")
    await db.flush()
    edition = await db.get(ImportedAudiobook, 1)
    edition.match_review_reason = _REVIEW
    await db.commit()
    await audiobook_imports.rematch_imported_audiobook(1, db)
    job = (await db.scalars(select(ProcessingJob))).one()
    if outcome == "canceled":
        await crud.request_processing_job_cancel(db, job.id)
        label = "Processing canceled"
    else:
        job.max_attempts = 1
        await db.commit()
        await crud.claim_processing_job(db, resource_lane="cpu", lease_owner="test", lease_seconds=60)
        await crud.fail_processing_job(db, job.id, "EPUB missing")
        label = "Processing failed"

    [response] = await audiobook_views.list_imported_audiobook_responses(1, db)
    assert response.status == "stale"
    assert (response.state, response.state_label, response.next_action, response.processing_job_id) == (
        "job_failed",
        label,
        "retry_processing",
        job.id,
    )
    assert (await audiobook_overview(db)).attention_count == 1


@pytest.mark.asyncio
async def test_job_history_keeps_match_review_action_and_manual_repair(db):
    _matched_book(db, 1, "Review matches")
    await db.commit()
    await audiobook_imports.rematch_imported_audiobook(1, db)
    job = (await db.scalars(select(ProcessingJob))).one()
    job.max_attempts = 1
    edition = await db.get(ImportedAudiobook, 1)
    edition.status = "ready"
    edition.match_review_reason = _REVIEW
    await db.commit()
    await crud.claim_processing_job(db, resource_lane="cpu", lease_owner="test", lease_seconds=60)
    # Jobs from before the reason was stored failed with it.
    await crud.fail_processing_job(db, job.id, _REVIEW)
    [response] = await audiobook_views.list_imported_audiobook_responses(1, db)
    assert (response.state, response.next_action) == ("needs_review", "review_matches")
    # A manual match correction can repair the edition without another job.
    track = await db.get(ImportedAudiobookTrack, 101)
    await audiobook_import.rematch_track(track, 101, db)
    assert (await audiobook_overview(db)).books[0].state == "ready_estimated"
