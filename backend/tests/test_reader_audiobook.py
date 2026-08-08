"""Reader API contract tests for modular generated audiobooks."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest

from backend.app import models
from backend.app.routers import reader
from backend.app.services import audiobook_publication


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root.parent))


@pytest.mark.asyncio
async def test_reader_audiobook_capability_and_assets(
    app_client,
    sqlite_sessionmaker,
    tmp_path,
    monkeypatch,
):
    library = tmp_path / "library"
    output = library / "audiobooks" / "839"
    output.mkdir(parents=True)
    text_path = output / "working.epub"
    audio_path = output / "ch0001.mp3"
    smil_path = output / "ch0001.smil"
    text_content = b"reader-text-epub"
    audio_content = b"0123456789abcdef"
    smil_content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <smil xmlns="http://www.w3.org/ns/SMIL" version="3.0"><body><seq>
      <par><text src="Text/chapter.xhtml#sentence-1"/>
      <audio src="ch0001.mp3" clipBegin="00:00:00.000" clipEnd="00:00:01.250"/></par>
    </seq></body></smil>"""
    text_path.write_bytes(text_content)
    audio_path.write_bytes(audio_content)
    smil_path.write_bytes(smil_content)
    reader_smil = audiobook_publication.reader_smil_bytes(smil_content, "Text/chapter.xhtml")

    monkeypatch.setattr(reader, "LIBRARY_PATH", library)
    monkeypatch.setattr(reader.audiobook_router, "LIBRARY_PATH", library)
    monkeypatch.setattr(audiobook_publication, "LIBRARY_PATH", library)

    async with sqlite_sessionmaker() as db:
        book = models.Book(
            id=839,
            title="Complete Audio",
            author="Reader",
            series="Reader Series",
            source_type=models.SourceType.epub,
            immutable_path="library/source.epub",
            current_path="library/current.epub",
            content_version=14,
            audiobook_enabled=True,
            audiobook_pipeline_status="complete",
            audiobook_revision=7,
            audiobook_source_content_version=14,
            audiobook_text_content_version=14,
            audiobook_publication_state="complete",
            audiobook_text_file_path=_relative(library, text_path),
            audiobook_text_size_bytes=len(text_content),
            audiobook_text_sha256=hashlib.sha256(text_content).hexdigest(),
        )
        db.add(book)
        db.add(
            models.AudiobookChapter(
                id=701,
                book_id=839,
                chapter_number=1,
                stable_chapter_key="src-chapter-one",
                source_href="Text/chapter.xhtml",
                content_file_name="Text/chapter.xhtml",
                title="Chapter One",
                spine_order=0,
                generation_state="ready",
                audio_revision=3,
                audio_file_path=_relative(library, audio_path),
                smil_file_path=_relative(library, smil_path),
                reader_audio_file_path=_relative(library, audio_path),
                reader_smil_file_path=_relative(library, smil_path),
                audio_size_bytes=len(audio_content),
                audio_sha256=hashlib.sha256(audio_content).hexdigest(),
                smil_size_bytes=len(reader_smil),
                smil_sha256=hashlib.sha256(reader_smil).hexdigest(),
                duration_ms=1250,
            )
        )
        db.add_all(
            [
                models.AudiobookSentence(
                    id=702,
                    chapter_id=701,
                    html_element_id="sentence-1",
                    sequence_order=0,
                    original_text="Chapter one.",
                ),
                models.AudiobookSentence(
                    id=703,
                    chapter_id=701,
                    html_element_id="sentence-2",
                    sequence_order=1,
                    original_text="Chapter two.",
                ),
            ]
        )
        db.add(
            models.ImportedAudiobook(
                id=70,
                book_id=839,
                name="Human narration",
                status="ready",
                created_at=datetime(2026, 7, 2, 15, 30, tzinfo=timezone.utc),
            )
        )
        db.add(
            models.ImportedAudiobook(
                id=69,
                book_id=839,
                name="Older human narration",
                status="ready",
                created_at=datetime(2026, 7, 1, 15, 30, tzinfo=timezone.utc),
            )
        )
        db.add(
            models.ImportedAudiobookTrack(
                id=71,
                imported_audiobook_id=70,
                matched_chapter_id=701,
                sequence_order=0,
                title="Chapter One",
                audio_file_path=_relative(library, audio_path),
                media_type="audio/mpeg",
                source_start_ms=0,
                source_end_ms=1250,
                duration_ms=1250,
            )
        )
        db.add(
            models.ImportedAudiobookTrack(
                id=72,
                imported_audiobook_id=70,
                matched_chapter_id=701,
                sequence_order=1,
                title="Chapter Two",
                audio_file_path=_relative(library, audio_path),
                media_type="audio/mpeg",
                source_start_ms=1250,
                source_end_ms=2500,
                duration_ms=1250,
            )
        )
        db.add_all(
            [
                models.ImportedAudiobookCue(
                    track_id=71,
                    sentence_id=702,
                    sequence_order=0,
                    clip_begin_ms=0,
                    clip_end_ms=1250,
                    method="estimated",
                ),
                models.ImportedAudiobookCue(
                    track_id=72,
                    sentence_id=703,
                    sequence_order=0,
                    clip_begin_ms=1250,
                    clip_end_ms=2500,
                    method="estimated",
                ),
            ]
        )
        db.add(
            models.Book(
                id=840,
                title="Complete Standalone Audio",
                author="Reader",
                source_type=models.SourceType.epub,
                immutable_path="library/standalone-source.epub",
                current_path="library/standalone-current.epub",
                content_version=14,
                audiobook_enabled=True,
                audiobook_pipeline_status="complete",
                audiobook_revision=7,
                audiobook_source_content_version=14,
                audiobook_text_content_version=14,
                audiobook_publication_state="complete",
                audiobook_text_file_path=_relative(library, text_path),
            )
        )
        db.add(
            models.AudiobookChapter(
                book_id=840,
                chapter_number=1,
                stable_chapter_key="src-chapter-one",
                source_href="Text/chapter.xhtml",
                generation_state="ready",
                audio_revision=3,
                reader_audio_file_path=_relative(library, audio_path),
                reader_smil_file_path=_relative(library, smil_path),
                audio_size_bytes=len(audio_content),
            )
        )
        await db.commit()

    protected_urls = [
        "/reader/books/839/audiobook/manifest",
        "/reader/books/839/audiobook/text",
        "/reader/books/839/audiobook/chapters/src-chapter-one/audio?version=3",
        "/reader/books/839/audiobook/chapters/src-chapter-one/smil?version=3",
    ]
    for url in protected_urls:
        assert app_client.get(url).status_code == 401

    key_response = app_client.post("/api/reader-keys", json={"label": "Audiobook Reader"})
    token = key_response.json()["token"]
    auth = ("reader", token)

    listing_urls = {
        "/reader/books/all": 839,
        "/reader/books/standalone": 840,
        "/reader/updates": 839,
        "/reader/series/Reader%20Series/books": 839,
    }
    for url, expected_book_id in listing_urls.items():
        payload = app_client.get(url, auth=auth).json()
        listed_book = next(item for item in payload if item["id"] == expected_book_id)
        audiobook = listed_book["audiobook"]
        assert audiobook == {
            "status": "complete",
            "revision": 7,
            "source_content_version": 14,
            "text_content_version": 14,
            "ready_chapter_count": 1,
            "total_chapter_count": 1,
            "ready_audio_bytes": len(audio_content),
            "manifest_url": f"/reader/books/{expected_book_id}/audiobook/manifest",
        }
        assert listed_book["audiobook_types"] == (
            ["ai_generated", "human_narrated"] if expected_book_id == 839 else ["ai_generated"]
        )
    single = app_client.get("/reader/books/839", auth=auth).json()
    assert single["audiobook"]["status"] == "complete"
    assert single["audiobook_types"] == ["ai_generated", "human_narrated"]
    human = app_client.get("/reader/books/839/human-audiobooks", auth=auth).json()
    assert [edition["id"] for edition in human] == [70, 69]
    assert [edition["is_reader_default"] for edition in human] == [True, False]
    assert human[0]["created_at"].startswith("2026-07-02T15:30:00")
    assert len(human[0]["tracks"]) == 2
    assert human[0]["audio_size_bytes"] == len(audio_content)
    canonical_audio_url = "/reader/human-audiobooks/70/tracks/71/audio"
    assert {track["audio_url"] for track in human[0]["tracks"]} == {canonical_audio_url}
    for track in human[0]["tracks"]:
        imported_smil = app_client.get(track["smil_url"], auth=auth)
        assert imported_smil.status_code == 200
        assert f'src="{canonical_audio_url}"'.encode() in imported_smil.content
        assert b'src="chapter.xhtml#' in imported_smil.content
    assert b'clipBegin="0.000s" clipEnd="1.250s"' in app_client.get(human[0]["tracks"][0]["smil_url"], auth=auth).content
    assert b'clipBegin="1.250s" clipEnd="2.500s"' in app_client.get(human[0]["tracks"][1]["smil_url"], auth=auth).content
    imported_audio = app_client.get(canonical_audio_url, auth=auth)
    assert imported_audio.content == audio_content
    assert imported_audio.headers["accept-ranges"] == "bytes"

    manifest_response = app_client.get(protected_urls[0], auth=auth)
    assert manifest_response.status_code == 200
    assert manifest_response.headers["content-type"].startswith("application/json")
    assert int(manifest_response.headers["content-length"]) == len(manifest_response.content)
    manifest = manifest_response.json()
    assert manifest["revision"] == 7
    assert manifest["text"]["sha256"] == hashlib.sha256(text_content).hexdigest()
    assert manifest["chapters"] == [
        {
            "key": "src-chapter-one",
            "title": "Chapter One",
            "href": "Text/chapter.xhtml",
            "state": "ready",
            "audio_version": 3,
            "duration_ms": 1250,
            "audio_size_bytes": len(audio_content),
            "audio_sha256": hashlib.sha256(audio_content).hexdigest(),
            "smil_size_bytes": len(reader_smil),
            "smil_sha256": hashlib.sha256(reader_smil).hexdigest(),
            "audio_url": "/reader/books/839/audiobook/chapters/src-chapter-one/audio?version=3",
            "smil_url": "/reader/books/839/audiobook/chapters/src-chapter-one/smil?version=3",
        }
    ]
    assert (
        app_client.get(
            protected_urls[0],
            auth=auth,
            headers={"If-None-Match": manifest_response.headers["etag"]},
        ).status_code
        == 304
    )

    text_response = app_client.get(protected_urls[1], auth=auth)
    assert text_response.content == text_content
    assert text_response.headers["content-type"].startswith("application/epub+zip")
    assert (
        app_client.get(
            protected_urls[1],
            auth=auth,
            headers={"If-None-Match": text_response.headers["etag"]},
        ).status_code
        == 304
    )

    audio_url = protected_urls[2]
    audio_response = app_client.get(audio_url, auth=auth)
    assert audio_response.content == audio_content
    assert audio_response.headers["accept-ranges"] == "bytes"
    partial = app_client.get(audio_url, auth=auth, headers={"Range": "bytes=2-5"})
    assert partial.status_code == 206
    assert partial.content == audio_content[2:6]
    assert partial.headers["content-range"] == f"bytes 2-5/{len(audio_content)}"
    suffix = app_client.get(audio_url, auth=auth, headers={"Range": "bytes=-4"})
    assert suffix.status_code == 206
    assert suffix.content == audio_content[-4:]
    invalid = app_client.get(audio_url, auth=auth, headers={"Range": "bytes=999-1000"})
    assert invalid.status_code == 416
    assert invalid.headers["content-range"] == f"bytes */{len(audio_content)}"
    stale = app_client.get(audio_url.replace("version=3", "version=2"), auth=auth)
    assert stale.status_code == 409
    assert stale.json() == {
        "error": "stale_audiobook_revision",
        "message": "Refresh the audiobook manifest before downloading this chapter.",
        "current_revision": 3,
    }

    smil_response = app_client.get(protected_urls[3], auth=auth)
    assert smil_response.content == reader_smil
    assert b'src="chapter.xhtml#sentence-1"' in smil_response.content
    assert b'src="audio.mp3"' in smil_response.content


@pytest.mark.asyncio
async def test_reader_book_omits_audiobook_for_legacy_book(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        db.add(
            models.Book(
                title="Legacy Book",
                author="Reader",
                source_type=models.SourceType.epub,
                immutable_path="library/legacy-source.epub",
                current_path="library/legacy.epub",
                content_version=1,
                audiobook_enabled=False,
            )
        )
        await db.commit()
    key_response = app_client.post("/api/reader-keys", json={"label": "Legacy Reader"})
    auth = ("reader", key_response.json()["token"])
    book = app_client.get("/reader/books/all", auth=auth).json()[0]
    assert book["audiobook"] is None
    assert book["audiobook_types"] == []
    assert app_client.get(f"/reader/books/{book['id']}/audiobook/manifest", auth=auth).status_code == 404


@pytest.mark.asyncio
async def test_reader_book_exposes_a_human_only_audiobook_type(app_client, sqlite_sessionmaker):
    async with sqlite_sessionmaker() as db:
        book = models.Book(
            title="Human Audio Book",
            author="Reader",
            source_type=models.SourceType.epub,
            immutable_path="library/human-source.epub",
            current_path="library/human.epub",
            content_version=1,
            audiobook_enabled=False,
        )
        db.add(book)
        await db.flush()
        db.add(
            models.ImportedAudiobook(
                book_id=book.id,
                name="Human narration",
                status="ready",
            )
        )
        await db.commit()
        book_id = book.id

    key_response = app_client.post("/api/reader-keys", json={"label": "Human Audio Reader"})
    auth = ("reader", key_response.json()["token"])
    payload = app_client.get(f"/reader/books/{book_id}", auth=auth).json()

    assert payload["audiobook"] is None
    assert payload["audiobook_types"] == ["human_narrated"]
    human_url = f"/reader/books/{book_id}/human-audiobooks"
    assert app_client.get(human_url).status_code == 401
    editions = app_client.get(human_url, auth=auth).json()
    assert len(editions) == 1
    assert editions[0]["name"] == "Human narration"
    assert editions[0]["status"] == "ready"
    assert (
        app_client.get(
            f"/reader/books/{book_id}/human-audiobooks/chapters",
            auth=auth,
        ).json()
        == []
    )


@pytest.mark.asyncio
async def test_human_only_audiobook_exposes_cues_and_downloads_anchored_text(
    app_client,
    sqlite_sessionmaker,
    tmp_path,
    monkeypatch,
):
    library = tmp_path / "library"
    current_path = library / "human.epub"
    reader_path = library / "audiobooks" / "841" / "reader" / "text-v1.epub"
    audio_path = library / "audiobooks" / "841" / "imports" / "70" / "human.m4b"
    current_path.parent.mkdir(parents=True)
    reader_path.parent.mkdir(parents=True)
    audio_path.parent.mkdir(parents=True)
    with ZipFile(current_path, "w") as archive:
        archive.writestr("EPUB/Text/chapter.xhtml", "<html><body><p>Human narration.</p></body></html>")
    with ZipFile(reader_path, "w") as archive:
        archive.writestr(
            "EPUB/Text/chapter.xhtml",
            '<html><body><p><span id="sentence-1">Human narration.</span></p></body></html>',
        )
    audio_path.write_bytes(b"human-audio")

    monkeypatch.setattr(reader, "LIBRARY_PATH", library)
    monkeypatch.setattr(reader.audiobook_router, "LIBRARY_PATH", library)
    monkeypatch.setattr(audiobook_publication, "LIBRARY_PATH", library)

    async with sqlite_sessionmaker() as db:
        book = models.Book(
            id=841,
            title="Human Audio With Text",
            author="Reader",
            source_type=models.SourceType.epub,
            immutable_path="library/human-source.epub",
            current_path=_relative(library, current_path),
            content_version=1,
            audiobook_enabled=False,
            audiobook_text_content_version=1,
            audiobook_text_file_path=_relative(library, reader_path),
        )
        chapter = models.AudiobookChapter(
            id=801,
            book_id=book.id,
            chapter_number=1,
            content_file_name="Text/chapter.xhtml",
            source_href="Text/chapter.xhtml",
            title="Chapter One",
        )
        sentence = models.AudiobookSentence(
            id=802,
            chapter_id=chapter.id,
            html_element_id="sentence-1",
            sequence_order=0,
            original_text="Human narration.",
        )
        edition = models.ImportedAudiobook(
            id=70,
            book_id=book.id,
            name="Human narration",
            status="ready",
            matched_content_version=1,
        )
        track = models.ImportedAudiobookTrack(
            id=71,
            imported_audiobook_id=edition.id,
            matched_chapter_id=chapter.id,
            sequence_order=1,
            title="Chapter One",
            audio_file_path=_relative(library, audio_path),
            media_type="audio/mp4",
            source_start_ms=0,
            source_end_ms=1250,
            duration_ms=1250,
        )
        cue = models.ImportedAudiobookCue(
            track_id=track.id,
            sentence_id=sentence.id,
            sequence_order=0,
            clip_begin_ms=0,
            clip_end_ms=1250,
            method="transcribed",
        )
        db.add_all([book, chapter, sentence, edition, track, cue])
        await db.commit()

    cues = app_client.get("/api/imported-audiobooks/70/tracks/71/cues")
    assert cues.status_code == 200
    assert cues.json() == [
        {
            "sentence_id": 802,
            "html_element_id": "sentence-1",
            "text": "Human narration.",
            "clip_begin_ms": 0,
            "clip_end_ms": 1250,
            "confidence": None,
            "method": "transcribed",
            "reading_block_index": 0,
            "reading_block_type": "paragraph",
        }
    ]

    key_response = app_client.post("/api/reader-keys", json={"label": "Human Audio Reader"})
    auth = ("reader", key_response.json()["token"])
    download = app_client.get("/reader/books/841/download", auth=auth)
    assert download.status_code == 200
    assert download.content == reader_path.read_bytes()
    assert download.headers["content-disposition"] == 'attachment; filename="human.epub"'
    assert b"sentence-1" in download.content

    editions = app_client.get("/reader/books/841/human-audiobooks", auth=auth).json()
    smil = app_client.get(editions[0]["tracks"][0]["smil_url"], auth=auth)
    assert smil.status_code == 200
    assert b'src="chapter.xhtml#sentence-1"' in smil.content

    async with sqlite_sessionmaker() as db:
        book = await db.get(models.Book, 841)
        book.content_version = 2
        await db.commit()
    stale_fallback = app_client.get("/reader/books/841/download", auth=auth)
    assert stale_fallback.content == current_path.read_bytes()


def test_reader_audiobook_capability_supports_all_publication_states():
    chapters = [
        models.AudiobookChapter(
            generation_state="pending",
            chapter_number=1,
        )
    ]
    for state in ("processing", "partial", "complete", "error"):
        book = models.Book(
            id=1,
            content_version=1,
            audiobook_enabled=True,
            audiobook_pipeline_status="audio_gen",
            audiobook_revision=2,
            audiobook_publication_state=state,
        )
        assert reader._reader_audiobook_capability(book, chapters)["status"] == state
