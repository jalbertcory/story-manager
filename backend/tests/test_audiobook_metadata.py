"""Identity extraction never treats chapter labels or narrators as book authors."""

import shutil
import subprocess
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.app.models import Book, ImportedAudiobook, SourceType, ProcessingJob
from backend.app.services import audiobook_import, audiobook_metadata


def test_filename_metadata_uses_libation_folder_and_series():
    assert audiobook_metadata.filename_metadata(
        [
            "Backup/Artemis Fowl Movie Tie-In Edition_ Artemis Fowl, Book 1 [B002V8MYYE]/audio.m4b",
        ]
    ) == {
        "title": "Artemis Fowl Movie Tie-In Edition",
        "series": "Artemis Fowl",
        "series_index": 1.0,
        "asin": "B002V8MYYE",
    }
    assert audiobook_metadata.filename_metadata(["Dr. Example.m4b"])["title"] == "Dr. Example"


def test_cue_metadata_stops_at_first_track(tmp_path):
    cue = tmp_path / "book.cue"
    cue.write_text(
        'TITLE "Book Title"\nPERFORMER "Book Author"\nTRACK 01 AUDIO\n TITLE "Chapter 1"\n PERFORMER "Someone else"'
    )
    assert audiobook_metadata.cue_metadata(cue) == {"title": "Book Title", "author": "Book Author"}


def test_tags_use_album_for_multiple_tracks_and_do_not_invent_author():
    payload = {"format": {"tags": {"TITLE": "Chapter 1", "ALBUM": "Full Book", "NARRATOR": "Narrator", "series-part": "2"}}}
    assert audiobook_metadata.tag_metadata(payload, single_file=False) == {
        "title": "Full Book",
        "narrator": "Narrator",
        "series_index": 2.0,
    }
    del payload["format"]["tags"]["ALBUM"]
    assert "title" not in audiobook_metadata.tag_metadata(payload, single_file=False)
    assert "author" not in audiobook_metadata.tag_metadata(payload, single_file=True)


@pytest.mark.asyncio
async def test_tagged_audio_fills_missing_metadata_and_cover_but_preserves_edits(db, tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg and ffprobe are required")
    library = tmp_path / "library"
    source = library / "audiobooks" / "metadata-test" / "source"
    source.mkdir(parents=True)
    monkeypatch.setattr(audiobook_import, "LIBRARY_PATH", library)
    audio = source / "book.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=32x32",
            "-t",
            "2",
            "-map",
            "0:a",
            "-map",
            "1:v",
            "-c:a",
            "libmp3lame",
            "-c:v",
            "mjpeg",
            "-frames:v",
            "1",
            "-id3v2_version",
            "3",
            "-metadata",
            "album=Tagged Book",
            "-metadata",
            "artist=Tagged Author",
            "-metadata",
            "series=Tagged Series",
            "-metadata",
            "series-part=3",
            str(audio),
        ],
        check=True,
    )
    book = Book(
        title="Fallback",
        author="Unknown author",
        source_type=SourceType.audiobook,
        metadata_details={"audiobook_import": {"inferred_title": "Fallback"}},
    )
    db.add(book)
    await db.flush()
    edition = ImportedAudiobook(book_id=book.id, name="Recording", status="queued", asin="B002V8MYYE")
    db.add(edition)
    await db.commit()
    await audiobook_metadata.enrich_audio_only_book(book, edition, [audio], [], db)
    assert (book.title, book.author, book.series, float(book.series_index)) == (
        "Tagged Book",
        "Tagged Author",
        "Tagged Series",
        3,
    )
    assert book.metadata_remote_ids == {"asin": "B002V8MYYE"}
    assert (library.parent / book.cover_path).read_bytes().startswith(b"\xff\xd8")
    assert "audio_tags" in book.metadata_details["audiobook_import"]["sources"]
    book.title, book.author, book.series = "My title", "My author", "My series"
    book.cover_path = "library/my-cover.jpg"
    await db.commit()
    await audiobook_metadata.enrich_audio_only_book(book, edition, [audio], [], db)
    assert (book.title, book.author, book.series, book.cover_path) == (
        "My title",
        "My author",
        "My series",
        "library/my-cover.jpg",
    )
    await audiobook_metadata.queue_audio_metadata_lookup(book, db)
    await audiobook_metadata.queue_audio_metadata_lookup(book, db)
    jobs = list((await db.execute(select(ProcessingJob).where(ProcessingJob.job_type == "metadata_sync"))).scalars())
    assert len(jobs) == 1


@pytest.mark.asyncio
async def test_bad_tags_fall_back_to_cue_without_failing_audio(db, tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook_metadata, "_run", AsyncMock(side_effect=ValueError("broken tags")))
    cue = tmp_path / "book.cue"
    cue.write_text('TITLE "CUE title"\nPERFORMER "CUE author"\nTRACK 1 AUDIO\n TITLE "First chapter"')
    book = Book(
        title="Fallback",
        author="Unknown author",
        source_type=SourceType.audiobook,
        metadata_details={"audiobook_import": {"inferred_title": "Fallback"}},
    )
    db.add(book)
    await db.flush()
    edition = ImportedAudiobook(book_id=book.id, name="Recording", status="queued")
    db.add(edition)
    await db.commit()
    await audiobook_metadata.enrich_audio_only_book(book, edition, [tmp_path / "book.mp3"], [cue], db)
    assert (book.title, book.author) == ("CUE title", "CUE author")


@pytest.mark.asyncio
async def test_metadata_lookup_failure_does_not_fail_ready_audio(db, monkeypatch):
    from backend.app.services import metadata_jobs

    book = Book(title="Ready book", author="Author", source_type=SourceType.audiobook)
    db.add(book)
    await db.flush()
    edition = ImportedAudiobook(book_id=book.id, name="Recording", status="ready")
    db.add(edition)
    await db.commit()
    monkeypatch.setattr(metadata_jobs, "queue_metadata_sync_job", AsyncMock(side_effect=RuntimeError("queue unavailable")))
    await audiobook_metadata.queue_audio_metadata_lookup(book, db)
    await db.refresh(edition)
    assert edition.status == "ready"


@pytest.mark.asyncio
async def test_upload_without_title_uses_libation_identity(app_client, sqlite_sessionmaker, tmp_path, monkeypatch):
    from backend.app.routers import audiobook

    monkeypatch.setattr(
        audiobook, "imported_audiobook_dir", lambda book_id, edition_id: tmp_path / str(book_id) / str(edition_id)
    )
    response = app_client.post(
        "/api/audiobooks/upload",
        files={"files": ("Artemis Fowl_ Artemis Fowl, Book 1 [B002V8MYYE].m4b", b"staged")},
    )
    assert response.status_code == 200, response.text
    async with sqlite_sessionmaker() as db:
        book = await db.get(Book, response.json()["book_id"])
        assert book.title == "Artemis Fowl"
        assert book.metadata_remote_ids == {"asin": "B002V8MYYE"}
        assert book.metadata_details["audiobook_import"]["inferred_title"] == book.title
