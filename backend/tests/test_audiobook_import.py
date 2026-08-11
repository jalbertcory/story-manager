"""Human-narrated audiobook import tests."""

from __future__ import annotations

import shutil
import subprocess
import zipfile

import pytest
from sqlalchemy import select

from backend.app.models import (
    AudiobookChapter,
    AudiobookSentence,
    AudiobookSettings,
    Book,
    ImportedAudiobook,
    ImportedAudiobookCue,
    ImportedAudiobookTrack,
    ProcessingJob,
)
from backend.app.routers import audiobook as audiobook_router
from backend.app.services import audiobook_import


async def _seed_book_text(db) -> tuple[Book, AudiobookChapter]:
    book = Book(
        title="Import Test",
        author="Narrator",
        immutable_path="library/import-test-immutable.epub",
        current_path="library/import-test.epub",
        content_version=1,
        audiobook_source_content_version=1,
        audiobook_text_content_version=1,
    )
    db.add(book)
    await db.flush()
    chapter = AudiobookChapter(
        book_id=book.id,
        chapter_number=1,
        title="1",
        content_file_name="text/chapter1.xhtml",
        stable_chapter_key="src-import-test",
        spine_order=0,
    )
    db.add(chapter)
    await db.flush()
    db.add_all(
        [
            AudiobookSentence(
                chapter_id=chapter.id,
                html_element_id="sentence-1",
                sequence_order=0,
                original_text="The first sentence.",
            ),
            AudiobookSentence(
                chapter_id=chapter.id,
                html_element_id="sentence-2",
                sequence_order=1,
                original_text="This second sentence is quite a bit longer than the first.",
            ),
        ]
    )
    await db.commit()
    return book, chapter


@pytest.mark.asyncio
async def test_existing_audiobook_text_is_reingested_when_book_content_is_newer(db, monkeypatch):
    book, chapter = await _seed_book_text(db)
    book.content_version = 2
    await db.commit()
    calls = []

    async def fake_ingest(book_id, selected_db):
        calls.append(book_id)
        selected_book = await selected_db.get(Book, book_id)
        selected_book.audiobook_source_content_version = selected_book.content_version
        selected_book.audiobook_text_content_version = selected_book.content_version
        selected_book.audiobook_pipeline_status = "roster_gen"
        await selected_db.commit()

    monkeypatch.setattr(audiobook_import, "ingest_epub", fake_ingest)

    chapters = await audiobook_import.ensure_span_anchored_text(book, db)

    assert calls == [book.id]
    assert [item.id for item in chapters] == [chapter.id]
    assert book.audiobook_pipeline_status is None
    assert book.audiobook_source_content_version == 2
    assert book.audiobook_text_content_version == 2


@pytest.mark.asyncio
async def test_processes_cue_zip_matches_chapter_and_builds_sentence_cues(db, tmp_path, monkeypatch):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required")
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(audiobook_import, "LIBRARY_PATH", library)
    book, chapter = await _seed_book_text(db)
    edition = ImportedAudiobook(
        book_id=book.id,
        name="Libation edition",
        status="queued",
        original_filenames=["Import Test [B012345678].zip"],
        asin="B012345678",
    )
    db.add(edition)
    await db.commit()
    await db.refresh(edition)

    source_mp3 = tmp_path / "source.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            "2",
            "-q:a",
            "9",
            str(source_mp3),
        ],
        check=True,
    )
    archive_path = audiobook_import.imported_audiobook_dir(book.id, edition.id) / "incoming" / "book.zip"
    archive_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
        archive.write(source_mp3, "Book/Import Test.mp3")
        archive.writestr(
            "Book/Import Test.cue",
            'FILE "Import Test.mp3" MP3\n'
            "TRACK 1 AUDIO\n"
            '  TITLE "Chapter 1"\n'
            "  INDEX 01 0:00:00\n"
            "TRACK 2 AUDIO\n"
            '  TITLE "End Credits"\n'
            "  INDEX 01 0:01:00\n",
        )

    await audiobook_import.process_import(edition.id, db)
    await db.refresh(edition)
    tracks = list(
        (
            await db.execute(
                select(ImportedAudiobookTrack)
                .where(ImportedAudiobookTrack.imported_audiobook_id == edition.id)
                .order_by(ImportedAudiobookTrack.sequence_order)
            )
        )
        .scalars()
        .all()
    )
    cues = list((await db.execute(select(ImportedAudiobookCue))).scalars().all())

    assert edition.status == "ready"
    assert edition.source_type == "libation"
    assert len(tracks) == 2
    assert tracks[0].matched_chapter_id == chapter.id
    assert tracks[1].matched_chapter_id is None
    assert len(cues) == 2
    assert cues[0].clip_begin_ms == 0
    assert cues[-1].clip_end_ms == tracks[0].source_end_ms


@pytest.mark.asyncio
async def test_manual_track_rematch_rebuilds_cues(db):
    book, chapter = await _seed_book_text(db)
    edition = ImportedAudiobook(book_id=book.id, name="Manual", status="ready")
    db.add(edition)
    await db.flush()
    track = ImportedAudiobookTrack(
        imported_audiobook_id=edition.id,
        sequence_order=1,
        title="Track One",
        audio_file_path="library/audio.mp3",
        media_type="audio/mpeg",
        source_start_ms=1_000,
        source_end_ms=11_000,
        duration_ms=10_000,
    )
    db.add(track)
    await db.commit()
    await db.refresh(track)

    cue_count = await audiobook_import.rematch_track(track, chapter.id, db)
    cues = list(
        (
            await db.execute(
                select(ImportedAudiobookCue)
                .where(ImportedAudiobookCue.track_id == track.id)
                .order_by(ImportedAudiobookCue.sequence_order)
            )
        )
        .scalars()
        .all()
    )
    assert cue_count == 2
    assert cues[0].clip_begin_ms == 1_000
    assert cues[-1].clip_end_ms == 11_000


def test_prepare_sources_reuses_extracted_files_on_retry(tmp_path, monkeypatch):
    edition_dir = tmp_path / "edition"
    incoming_dir = edition_dir / "incoming"
    source_dir = edition_dir / "source"
    incoming_dir.mkdir(parents=True)
    source_dir.mkdir()
    extracted_audio = source_dir / "existing.m4b"
    extracted_cue = source_dir / "existing.cue"
    extracted_audio.write_bytes(b"audio")
    extracted_cue.write_text('TITLE "Existing"\n', encoding="utf-8")
    (incoming_dir / "original.zip").write_bytes(b"the retained upload")

    def fail_if_reextracted(*_args):
        raise AssertionError("retry should reuse already extracted source files")

    monkeypatch.setattr(audiobook_import, "_extract_archive_sources", fail_if_reextracted)

    audio_paths, cue_paths = audiobook_import._prepare_sources(edition_dir)

    assert audio_paths == [extracted_audio]
    assert cue_paths == [extracted_cue]


def test_prepare_sources_prefers_m4b_from_unzipped_libation_folder(tmp_path):
    edition_dir = tmp_path / "edition"
    incoming_dir = edition_dir / "incoming"
    incoming_dir.mkdir(parents=True)
    (incoming_dir / "Book [B012345678].m4b").write_bytes(b"m4b")
    (incoming_dir / "Book [B012345678].mp3").write_bytes(b"mp3")
    (incoming_dir / "Book [B012345678].cue").write_text(
        'TITLE "Book"\n',
        encoding="utf-8",
    )

    audio_paths, cue_paths = audiobook_import._prepare_sources(edition_dir)

    assert [path.suffix for path in audio_paths] == [".m4b"]
    assert [path.suffix for path in cue_paths] == [".cue"]


def test_libation_backup_groups_supports_audible_and_isbn_folders():
    groups, ignored = audiobook_import.libation_backup_groups(
        [
            "Libation/A Court of Mist and Fury [B01DYO4QRQ]/book.m4b",
            "Libation/A Court of Mist and Fury [B01DYO4QRQ]/book.cue",
            "Libation/A Court of Silver Flames [1980085722]/book.mp3",
            "Libation/A Court of Silver Flames [1980085722]/cover.jpg",
        ]
    )

    assert ignored == 1
    assert [(group.title, group.product_id, len(group.source_paths)) for group in groups] == [
        ("A Court of Mist and Fury", "B01DYO4QRQ", 2),
        ("A Court of Silver Flames", "1980085722", 1),
    ]


@pytest.mark.asyncio
async def test_libation_backup_preview_matches_identifiers_titles_and_skips_existing(
    app_client,
    sqlite_sessionmaker,
):
    async with sqlite_sessionmaker() as db:
        identifier_book = Book(
            title="Different Store Title",
            author="Author One",
            immutable_path="library/identifier-immutable.epub",
            current_path="library/identifier.epub",
            metadata_remote_ids={"isbn_13": "9781980085720"},
        )
        title_book = Book(
            title="Title Match",
            author="Author Two",
            immutable_path="library/title-immutable.epub",
            current_path="library/title.epub",
        )
        title_variant_book = Book(
            title="Rhythm of War (The Stormlight Archive)",
            author="Brandon Sanderson",
            immutable_path="library/rhythm-immutable.epub",
            current_path="library/rhythm.epub",
        )
        existing_book = Book(
            title="Already Here",
            author="Author Three",
            immutable_path="library/existing-immutable.epub",
            current_path="library/existing.epub",
        )
        db.add_all([identifier_book, title_book, title_variant_book, existing_book])
        await db.flush()
        existing = ImportedAudiobook(
            book_id=existing_book.id,
            name="Prior Libation import",
            asin="B111111111",
            status="ready",
        )
        db.add(existing)
        await db.commit()

    response = app_client.post(
        "/api/audiobook/libation-backup/preview",
        json={
            "source_paths": [
                "Backup/Store Name [1980085722]/book.m4b",
                "Backup/Title Match [B012345678]/book.m4b",
                "Backup/Rhythm of War [1250759781]/book.m4b",
                "Backup/Already Here [B111111111]/book.m4b",
                "Backup/Not In Library [B222222222]/book.m4b",
                "Backup/Not In Library [B222222222]/cover.jpg",
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["matched_count"] == 3
    assert payload["unmatched_count"] == 1
    assert payload["already_imported_count"] == 1
    assert payload["ignored_file_count"] == 1
    matches = {group["product_id"]: group for group in payload["groups"]}
    assert matches["1980085722"]["match_method"] == "identifier"
    assert matches["1980085722"]["book_title"] == "Different Store Title"
    assert matches["B012345678"]["match_method"] == "title"
    assert matches["1250759781"]["match_method"] == "title_variant"
    assert matches["1250759781"]["book_title"] == "Rhythm of War (The Stormlight Archive)"
    assert matches["B111111111"]["status"] == "already_imported"
    assert matches["B111111111"]["existing_edition_id"] is not None
    assert matches["B222222222"]["status"] == "unmatched"
    assert {book["book_title"] for book in payload["library_books"]} >= {
        "Different Store Title",
        "Rhythm of War (The Stormlight Archive)",
    }


@pytest.mark.asyncio
async def test_libation_backup_preview_requires_review_for_ambiguous_title_variants(
    app_client,
    sqlite_sessionmaker,
):
    async with sqlite_sessionmaker() as db:
        db.add_all(
            [
                Book(
                    title="Shared Title (Series One)",
                    author="Author One",
                    immutable_path="library/shared-one-immutable.epub",
                    current_path="library/shared-one.epub",
                ),
                Book(
                    title="Shared Title: Anniversary Edition",
                    author="Author Two",
                    immutable_path="library/shared-two-immutable.epub",
                    current_path="library/shared-two.epub",
                ),
            ]
        )
        await db.commit()

    response = app_client.post(
        "/api/audiobook/libation-backup/preview",
        json={"source_paths": ["Backup/Shared Title [B012345678]/book.m4b"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ambiguous_count"] == 1
    assert payload["matched_count"] == 0
    assert {candidate["book_author"] for candidate in payload["groups"][0]["candidates"]} == {
        "Author One",
        "Author Two",
    }


@pytest.mark.asyncio
async def test_upload_endpoint_streams_large_format_to_staging(
    app_client,
    sqlite_sessionmaker,
    tmp_path,
    monkeypatch,
):
    class FakeQueue:
        async def enqueue(self, _edition_id):
            return True

    async with sqlite_sessionmaker() as db:
        book, _chapter = await _seed_book_text(db)
        book_id = book.id
    monkeypatch.setattr(
        audiobook_router,
        "imported_audiobook_dir",
        lambda selected_book_id, edition_id: tmp_path / str(selected_book_id) / str(edition_id),
    )
    monkeypatch.setattr(audiobook_router, "get_audiobook_import_queue", lambda: FakeQueue())

    response = app_client.post(
        f"/api/books/{book_id}/audiobook/imports",
        files={"files": ("Import Test [B012345678].m4b", b"not-buffered-by-the-handler", "audio/mp4")},
        data={
            "source_paths": "Import Test [B012345678]/Import Test.m4b",
            "auto_align": "true",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["asin"] == "B012345678"
    assert payload["name"] == "Import Test"
    assert (
        tmp_path / str(book_id) / str(payload["id"]) / "incoming" / "Import Test [B012345678].m4b"
    ).read_bytes() == b"not-buffered-by-the-handler"
    async with sqlite_sessionmaker() as db:
        job = (
            await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.job_type == "import_audiobook",
                    ProcessingJob.target_id == payload["id"],
                )
            )
        ).scalar_one()
        assert job.payload == {"auto_align": True}


@pytest.mark.asyncio
async def test_alignment_endpoint_durably_queues_ready_edition(
    app_client,
    sqlite_sessionmaker,
    monkeypatch,
):
    class FakeAlignmentQueue:
        queued = []

        async def enqueue(self, edition_id):
            self.queued.append(edition_id)
            return True

    queue = FakeAlignmentQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_alignment_queue", lambda: queue)
    async with sqlite_sessionmaker() as db:
        book, chapter = await _seed_book_text(db)
        db.add(
            ImportedAudiobook(
                book_id=book.id,
                name="Ready edition",
                status="ready",
                alignment_method="estimated",
            )
        )
        await db.flush()
        edition = (await db.execute(select(ImportedAudiobook).where(ImportedAudiobook.book_id == book.id))).scalar_one()
        db.add(
            ImportedAudiobookTrack(
                imported_audiobook_id=edition.id,
                matched_chapter_id=chapter.id,
                sequence_order=1,
                title="Chapter 1",
                audio_file_path="library/audio.m4b",
                media_type="audio/mp4",
                source_start_ms=0,
                source_end_ms=10_000,
                duration_ms=10_000,
            )
        )
        db.add(
            AudiobookSettings(
                transcription_provider="whisperx",
                transcription_base_url="http://whisper:8002",
            )
        )
        await db.commit()
        edition_id = edition.id

    response = app_client.post(f"/api/imported-audiobooks/{edition_id}/align")

    assert response.status_code == 200
    assert response.json()["status"] == "aligning"
    assert response.json()["progress_total"] == 1
    assert queue.queued == [edition_id]


@pytest.mark.asyncio
async def test_rematch_endpoint_queues_cue_recovery_without_reimporting_audio(
    app_client,
    sqlite_sessionmaker,
):
    async with sqlite_sessionmaker() as db:
        book, _chapter = await _seed_book_text(db)
        edition = ImportedAudiobook(
            book_id=book.id,
            name="Damaged alignment",
            status="ready",
            alignment_method="transcribed",
        )
        db.add(edition)
        await db.flush()
        db.add(
            ImportedAudiobookTrack(
                imported_audiobook_id=edition.id,
                sequence_order=0,
                title="Chapter 1",
                audio_file_path="library/audio.m4b",
                media_type="audio/mp4",
                source_start_ms=0,
                source_end_ms=10_000,
                duration_ms=10_000,
            )
        )
        await db.commit()
        edition_id = edition.id

    response = app_client.post(f"/api/imported-audiobooks/{edition_id}/rematch")

    assert response.status_code == 200
    assert response.json()["status"] == "stale"
    async with sqlite_sessionmaker() as db:
        edition = await db.get(ImportedAudiobook, edition_id)
        job = (
            await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.job_type == "rematch_imported_audiobook",
                    ProcessingJob.target_id == edition_id,
                )
            )
        ).scalar_one()
        assert edition.status == "stale"
        assert job.payload == {"realign": True}
