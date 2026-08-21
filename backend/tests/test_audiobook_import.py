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
    monkeypatch.setattr(audiobook_router, "LIBRARY_PATH", library)
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
    assert tracks[0].audio_file_path != tracks[1].audio_file_path
    assert all("/derived/revision-1/" in track.audio_file_path for track in tracks)
    assert all(track.source_audio_file_path.endswith(".mp3") for track in tracks)
    assert tracks[0].source_start_ms == tracks[1].source_start_ms == 0
    assert all((library.parent / track.audio_file_path).is_file() for track in tracks)
    assert len(cues) == 2
    assert cues[0].clip_begin_ms == 0
    assert cues[-1].clip_end_ms == tracks[0].source_end_ms

    response = await audiobook_router._imported_audiobook_response(edition, db)
    assert {track.audio_url for track in response.tracks} == {
        f"/api/imported-audiobooks/{edition.id}/tracks/{track.id}/audio" for track in tracks
    }
    smil = await audiobook_router.get_imported_track_smil(edition.id, tracks[0].id, db)
    assert f'src="/api/imported-audiobooks/{edition.id}/tracks/{tracks[0].id}/audio"'.encode() in smil.body
    assert b'clipBegin="0.000s"' in smil.body
    assert edition.source_manifest_sha256
    assert edition.source_size_bytes == source_mp3.stat().st_size + len(
        'FILE "Import Test.mp3" MP3\n'
        "TRACK 1 AUDIO\n"
        '  TITLE "Chapter 1"\n'
        "  INDEX 01 0:00:00\n"
        "TRACK 2 AUDIO\n"
        '  TITLE "End Credits"\n'
        "  INDEX 01 0:01:00\n"
    )
    assert edition.derived_revision == 1
    assert edition.derived_format_version == audiobook_import.CURRENT_DERIVED_FORMAT_VERSION


@pytest.mark.asyncio
async def test_upgrades_legacy_tracks_from_immutable_source_and_cleans_old_revisions(db, tmp_path, monkeypatch):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required")
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(audiobook_import, "LIBRARY_PATH", library)
    book, chapter = await _seed_book_text(db)
    edition = ImportedAudiobook(book_id=book.id, name="Legacy edition", status="ready")
    db.add(edition)
    await db.flush()
    edition_dir = audiobook_import.imported_audiobook_dir(book.id, edition.id)
    source = edition_dir / "source" / "legacy.m4b"
    source.parent.mkdir(parents=True)
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
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
    )
    (edition_dir / "source" / "legacy.cue").write_text("TRACK 01 AUDIO\n", encoding="utf-8")
    relative_source = audiobook_import.relative_library_path(source)
    tracks = [
        ImportedAudiobookTrack(
            imported_audiobook_id=edition.id,
            matched_chapter_id=chapter.id,
            sequence_order=index,
            title=f"Chapter {index}",
            audio_file_path=relative_source,
            media_type="audio/mp4",
            source_start_ms=(index - 1) * 1_000,
            source_end_ms=index * 1_000,
            duration_ms=1_000,
        )
        for index in (1, 2)
    ]
    db.add_all(tracks)
    await db.flush()
    sentence_ids = list(
        (
            await db.execute(
                select(AudiobookSentence.id)
                .where(AudiobookSentence.chapter_id == chapter.id)
                .order_by(AudiobookSentence.sequence_order)
            )
        ).scalars()
    )
    db.add_all(
        [
            ImportedAudiobookCue(
                track_id=track.id,
                sentence_id=sentence_ids[index - 1],
                sequence_order=0,
                clip_begin_ms=(index - 1) * 1_000 + 100,
                clip_end_ms=(index - 1) * 1_000 + 900,
                method="transcribed",
            )
            for index, track in enumerate(tracks, start=1)
        ]
    )
    obsolete = edition_dir / "derived" / "revision-0"
    obsolete.mkdir(parents=True)
    (obsolete / "old.m4a").write_bytes(b"old")
    await db.commit()
    track_ids = [track.id for track in tracks]

    revision = await audiobook_import.upgrade_imported_audiobook(edition.id, db)
    await db.refresh(edition)
    upgraded = list(
        (
            await db.execute(
                select(ImportedAudiobookTrack)
                .where(ImportedAudiobookTrack.imported_audiobook_id == edition.id)
                .order_by(ImportedAudiobookTrack.sequence_order)
            )
        ).scalars()
    )
    cues = list((await db.execute(select(ImportedAudiobookCue).order_by(ImportedAudiobookCue.track_id))).scalars())

    assert revision == edition.derived_revision == 1
    assert [track.id for track in upgraded] == track_ids
    assert {track.source_audio_file_path for track in upgraded} == {relative_source}
    assert [(track.source_start_ms, track.source_end_ms) for track in upgraded] == [(0, 1_000), (0, 1_000)]
    assert all("/derived/revision-1/" in track.audio_file_path for track in upgraded)
    assert [(cue.clip_begin_ms, cue.clip_end_ms) for cue in cues] == [(100, 900), (100, 900)]
    assert not obsolete.exists()
    assert (edition_dir / "source" / "manifest.json").is_file()
    assert source.is_file()

    second_revision = await audiobook_import.upgrade_imported_audiobook(edition.id, db)
    cues = list((await db.execute(select(ImportedAudiobookCue).order_by(ImportedAudiobookCue.track_id))).scalars())
    assert second_revision == 2
    assert not (edition_dir / "derived" / "revision-1").exists()
    assert (edition_dir / "derived" / "revision-2").is_dir()
    assert [(cue.clip_begin_ms, cue.clip_end_ms) for cue in cues] == [(100, 900), (100, 900)]


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
        other_edition = ImportedAudiobook(
            book_id=title_book.id,
            name="Uploaded narration",
            asin="B999999999",
            status="ready",
        )
        db.add_all([existing, other_edition])
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
    assert payload["existing_audio_match_count"] == 2
    assert payload["ignored_file_count"] == 1
    matches = {group["product_id"]: group for group in payload["groups"]}
    assert matches["1980085722"]["match_method"] == "identifier"
    assert matches["1980085722"]["book_title"] == "Different Store Title"
    assert matches["B012345678"]["match_method"] == "title"
    assert matches["B012345678"]["status"] == "matched"
    assert matches["B012345678"]["existing_audiobooks"] == [
        {
            "edition_id": other_edition.id,
            "name": "Uploaded narration",
            "status": "ready",
            "source_type": "upload",
            "product_id": "B999999999",
        }
    ]
    assert matches["1250759781"]["match_method"] == "title_variant"
    assert matches["1250759781"]["book_title"] == "Rhythm of War (The Stormlight Archive)"
    assert matches["B111111111"]["status"] == "already_imported"
    assert matches["B111111111"]["existing_edition_id"] is not None
    assert matches["B111111111"]["existing_audiobooks"][0]["name"] == "Prior Libation import"
    assert matches["B222222222"]["status"] == "unmatched"
    assert {book["book_title"] for book in payload["library_books"]} >= {
        "Different Store Title",
        "Rhythm of War (The Stormlight Archive)",
    }
    title_option = next(book for book in payload["library_books"] if book["book_title"] == "Title Match")
    assert title_option["existing_audiobooks"][0]["name"] == "Uploaded narration"


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
async def test_upgrade_endpoints_queue_legacy_editions_and_skip_current_or_active(
    app_client,
    sqlite_sessionmaker,
):
    async with sqlite_sessionmaker() as db:
        book, chapter = await _seed_book_text(db)
        legacy = ImportedAudiobook(book_id=book.id, name="Legacy", status="ready")
        current = ImportedAudiobook(
            book_id=book.id,
            name="Current",
            status="ready",
            source_manifest_sha256="a" * 64,
            derived_revision=2,
            derived_format_version=audiobook_import.CURRENT_DERIVED_FORMAT_VERSION,
        )
        active = ImportedAudiobook(book_id=book.id, name="Active", status="aligning")
        db.add_all([legacy, current, active])
        await db.flush()
        for edition in (legacy, current, active):
            db.add(
                ImportedAudiobookTrack(
                    imported_audiobook_id=edition.id,
                    matched_chapter_id=chapter.id,
                    sequence_order=1,
                    title="Chapter 1",
                    audio_file_path=f"library/{edition.id}.m4b",
                    media_type="audio/mp4",
                    source_start_ms=0,
                    source_end_ms=10_000,
                    duration_ms=10_000,
                )
            )
        await db.commit()
        legacy_id = legacy.id
        active_id = active.id

    response = app_client.post(f"/api/imported-audiobooks/{legacy_id}/upgrade")
    assert response.status_code == 200
    assert response.json()["needs_upgrade"] is True
    assert response.json()["progress_detail"] == "Chapter-audio upgrade queued"

    active_response = app_client.post(f"/api/imported-audiobooks/{active_id}/upgrade")
    assert active_response.status_code == 409

    bulk = app_client.post("/api/audiobook/imports/upgrade-all")
    assert bulk.status_code == 200
    assert bulk.json() == {"queued_count": 1, "skipped_count": 2}
    async with sqlite_sessionmaker() as db:
        jobs = list(
            (await db.execute(select(ProcessingJob).where(ProcessingJob.job_type == "upgrade_imported_audiobook"))).scalars()
        )
        assert len(jobs) == 1
        assert jobs[0].target_id == legacy_id
        assert jobs[0].payload == {"format_version": audiobook_import.CURRENT_DERIVED_FORMAT_VERSION}


@pytest.mark.asyncio
async def test_delete_imported_edition_removes_source_and_derived_files(
    app_client,
    sqlite_sessionmaker,
    tmp_path,
    monkeypatch,
):
    async with sqlite_sessionmaker() as db:
        book, _chapter = await _seed_book_text(db)
        edition = ImportedAudiobook(book_id=book.id, name="Disposable edition", status="ready")
        db.add(edition)
        await db.commit()
        await db.refresh(edition)
        edition_id = edition.id
        book_id = book.id

    monkeypatch.setattr(
        audiobook_router,
        "imported_audiobook_dir",
        lambda selected_book_id, selected_edition_id: tmp_path / str(selected_book_id) / str(selected_edition_id),
    )
    edition_dir = tmp_path / str(book_id) / str(edition_id)
    (edition_dir / "source").mkdir(parents=True)
    (edition_dir / "source" / "original.m4b").write_bytes(b"source")
    (edition_dir / "derived" / "revision-1").mkdir(parents=True)
    (edition_dir / "derived" / "revision-1" / "track.m4a").write_bytes(b"derived")

    response = app_client.delete(f"/api/imported-audiobooks/{edition_id}")

    assert response.status_code == 204
    assert not edition_dir.exists()
    async with sqlite_sessionmaker() as db:
        assert await db.get(ImportedAudiobook, edition_id) is None


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
