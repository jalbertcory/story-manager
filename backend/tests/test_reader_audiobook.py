"""Reader API contract tests for modular generated audiobooks."""

from __future__ import annotations

import hashlib
from pathlib import Path

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
        audiobook = next(item for item in payload if item["id"] == expected_book_id)["audiobook"]
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
    single = app_client.get("/reader/books/839", auth=auth).json()
    assert single["audiobook"]["status"] == "complete"

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
    assert app_client.get(f"/reader/books/{book['id']}/audiobook/manifest", auth=auth).status_code == 404


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
