import asyncio
import shutil
import zipfile
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from ebooklib import epub

from backend.app import crud, models
from backend.app.routers import audiobook as audiobook_router
from backend.app.services import audiobook_assembly, audiobook_ingestion, audiobook_llm, audiobook_tts
from backend.app.services import audiobook_queue
from backend.app.services.audiobook_queue import AudiobookQueue


async def _make_book(db, **overrides):
    title = overrides.get("title", "Audio Book")
    slug = title.lower().replace(" ", "-")
    payload = {
        "title": title,
        "author": "Reader",
        "source_type": models.SourceType.epub,
        "immutable_path": f"library/{slug}-immutable.epub",
        "current_path": f"library/{slug}.epub",
    }
    payload.update(overrides)
    book = models.Book(**payload)
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


async def _seed_audio_chapter(db, book_id: int, *, sentence_status: str = "ready_for_audio"):
    chapter = await crud.audiobook.create_chapter(
        db,
        book_id=book_id,
        chapter_number=1,
        content_file_name="Text/chapter_1.xhtml",
    )
    characters = await crud.audiobook.create_characters_bulk(
        db,
        book_id=book_id,
        characters_data=[
            {
                "name": "Narrator",
                "description": "Primary narrator",
                "voice_design_prompt": "[gender-neutral][pitch-medium][speed-normal]",
                "is_narrator": True,
            }
        ],
    )
    await crud.audiobook.create_sentences_bulk(
        db,
        chapter_id=chapter.id,
        sentences_data=[
            {
                "html_element_id": "ch1_s0",
                "sequence_order": 0,
                "original_text": "One sentence.",
                "tagged_text": "One sentence.",
                "character_id": characters[0].id,
                "status": sentence_status,
            }
        ],
    )
    sentence = (await crud.audiobook.get_sentences_for_chapter(db, chapter.id))[0]
    return chapter, characters[0], sentence


class _FakeQueue:
    def __init__(self):
        self.enqueued: list[int] = []

    async def enqueue(self, book_id: int) -> bool:
        self.enqueued.append(book_id)
        return True


@pytest.mark.asyncio
async def test_queue_schedules_one_rerun_for_changes_during_processing(monkeypatch):
    queue = AudiobookQueue()
    processed: list[int] = []
    first_run_started = asyncio.Event()
    release_first_run = asyncio.Event()

    async def process(book_id: int) -> None:
        processed.append(book_id)
        if len(processed) == 1:
            first_run_started.set()
            await release_first_run.wait()

    monkeypatch.setattr(queue, "_process", process)
    await queue.start()
    try:
        assert await queue.enqueue(42) is True
        await first_run_started.wait()

        assert await queue.enqueue(42) is False
        assert await queue.enqueue(42) is False
        release_first_run.set()
        await queue._queue.join()

        assert processed == [42, 42]
    finally:
        await queue.stop()


@pytest.mark.asyncio
async def test_queue_persists_actionable_pipeline_error(db, sqlite_sessionmaker, monkeypatch):
    book = await _make_book(
        db,
        audiobook_enabled=True,
        audiobook_pipeline_status="ingesting",
    )
    queue = AudiobookQueue()

    async def fail(_book_id):
        raise RuntimeError("EPUB contains no narratable text")

    monkeypatch.setattr(audiobook_queue, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(queue, "_process", fail)
    await queue.start()
    try:
        await queue.enqueue(book.id)
        await queue._queue.join()
    finally:
        await queue.stop()

    await db.refresh(book)
    assert book.audiobook_pipeline_status == "error"
    assert book.audiobook_last_error == "EPUB contains no narratable text"


@pytest.mark.asyncio
async def test_books_default_audiobook_pipeline_disabled(db, monkeypatch):
    book = await _make_book(db)
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    with pytest.raises(audiobook_router.HTTPException) as exc_info:
        await audiobook_router.start_pipeline(book.id, db)

    await db.refresh(book)
    assert book.audiobook_enabled is False
    assert exc_info.value.status_code == 403
    assert queue.enqueued == []


@pytest.mark.asyncio
async def test_requeue_candidates_only_include_enabled_audiobooks(db):
    disabled = await _make_book(db)
    disabled.audiobook_pipeline_status = "audio_gen"
    enabled = await _make_book(db, title="Enabled Audio", audiobook_enabled=True)
    enabled.audiobook_pipeline_status = "audio_gen"
    await db.commit()

    pending = await crud.audiobook.get_in_progress_audiobook_books(db)

    assert [book.id for book in pending] == [enabled.id]


@pytest.mark.asyncio
async def test_empty_audio_state_is_not_considered_complete(db):
    book = await _make_book(db, audiobook_enabled=True)

    assert await crud.audiobook.all_sentences_audio_generated(db, book.id) is False


@pytest.mark.asyncio
async def test_paused_pipeline_resumes_from_persisted_audio_state(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True)
    await _seed_audio_chapter(db, book.id, sentence_status="ready_for_audio")
    await crud.audiobook.set_book_pipeline_status(db, book.id, "paused")
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    response = await audiobook_router.start_pipeline(book.id, db)

    await db.refresh(book)
    assert response == {"status": "audio_gen", "queued": True}
    assert book.audiobook_pipeline_status == "audio_gen"
    assert queue.enqueued == [book.id]


@pytest.mark.asyncio
async def test_error_pipeline_resets_failed_sentences_before_retry(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True)
    chapter, _character, sentence = await _seed_audio_chapter(db, book.id, sentence_status="error")
    await crud.audiobook.set_book_pipeline_status(db, book.id, "error")
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    response = await audiobook_router.start_pipeline(book.id, db)

    await db.refresh(book)
    await db.refresh(chapter)
    await db.refresh(sentence)
    assert response == {"status": "audio_gen", "queued": True}
    assert book.audiobook_pipeline_status == "audio_gen"
    assert sentence.status == "ready_for_audio"
    assert sentence.audio_file_path is None
    assert chapter.needs_reassembly is True


@pytest.mark.asyncio
async def test_step_pipeline_runs_only_next_recoverable_phase(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True)
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    response = await audiobook_router.step_pipeline(book.id, db)

    await db.refresh(book)
    assert response == {
        "status": "ingesting",
        "queued": True,
        "stop_after_phase": "ingesting",
    }
    assert book.audiobook_pipeline_status == "ingesting"
    assert book.audiobook_stop_after_phase == "ingesting"
    assert book.audiobook_last_error is None
    assert queue.enqueued == [book.id]


@pytest.mark.asyncio
async def test_queue_stops_for_review_after_requested_phase(db, sqlite_sessionmaker, monkeypatch):
    book = await _make_book(
        db,
        audiobook_enabled=True,
        audiobook_pipeline_status="ingesting",
        audiobook_stop_after_phase="ingesting",
    )
    phases: list[str] = []

    async def ingest(book_id, phase_db):
        phases.append("ingesting")
        await crud.audiobook.set_book_pipeline_status(phase_db, book_id, "roster_gen")

    async def unexpected(*_args):
        phases.append("unexpected")

    monkeypatch.setattr(audiobook_queue, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(audiobook_queue, "ingest_epub", ingest)
    monkeypatch.setattr(audiobook_queue, "generate_character_roster", unexpected)

    await AudiobookQueue()._process(book.id)

    await db.refresh(book)
    assert phases == ["ingesting"]
    assert book.audiobook_pipeline_status == "paused"
    assert book.audiobook_stop_after_phase is None


@pytest.mark.asyncio
async def test_pause_is_cooperative_and_status_exposes_error_context(db):
    book = await _make_book(
        db,
        audiobook_enabled=True,
        audiobook_pipeline_status="audio_gen",
        audiobook_last_error="Previous failure",
    )

    response = await audiobook_router.pause_pipeline(book.id, db)
    await db.refresh(book)

    assert response == {"status": "audio_gen", "pause_requested": True}
    assert book.audiobook_pipeline_status == "audio_gen"
    assert book.audiobook_pause_requested is True

    await crud.audiobook.pause_book_pipeline_if_requested(db, book.id)
    status = await audiobook_router.get_pipeline_status(book.id, db)

    assert status.pipeline_status == "paused"
    assert status.pause_requested is False
    assert status.next_phase == "ingesting"
    assert status.last_error == "Previous failure"


@pytest.mark.asyncio
async def test_tts_failure_marks_book_error_instead_of_advancing_to_assembly(db, monkeypatch):
    book = await _make_book(db)
    chapter, _character, _sentence = await _seed_audio_chapter(db, book.id, sentence_status="ready_for_audio")
    settings = models.AudiobookSettings(omnivoice_endpoint="http://tts.example.test")
    db.add(settings)
    await db.commit()

    async def fail_omnivoice(endpoint, voice_prompt, tagged_text):
        request = httpx.Request("POST", endpoint)
        raise httpx.ConnectError("connection failed", request=request)

    monkeypatch.setattr(audiobook_tts, "_call_omnivoice", fail_omnivoice)

    with pytest.raises(RuntimeError, match="TTS failed"):
        await audiobook_tts.generate_audio_for_book(book.id, db)

    sentence = (await crud.audiobook.get_sentences_for_chapter(db, chapter.id))[0]
    await db.refresh(book)
    await db.refresh(sentence)
    assert book.audiobook_pipeline_status == "error"
    assert sentence.status == "error"
    assert sentence.audio_file_path is None


def test_smil_uses_real_epub_content_file_name():
    chapter = models.AudiobookChapter(
        chapter_number=1,
        content_file_name="Text/real_chapter.xhtml",
    )
    sentence = models.AudiobookSentence(
        html_element_id="ch1_s0",
        audio_duration_ms=1250,
    )

    smil = audiobook_assembly._build_smil(chapter, [sentence], "ch0001.mp3")

    assert 'epub:textref="Text/real_chapter.xhtml"' in smil
    assert 'src="Text/real_chapter.xhtml#ch1_s0"' in smil
    assert 'src="ch0001.mp3"' in smil
    assert 'clipEnd="00:00:01.250"' in smil


def _write_nested_epub(path: Path) -> None:
    book = epub.EpubBook()
    book.set_identifier("nested-test")
    book.set_title("Nested")
    book.set_language("en")
    book.add_author("Author")
    chapter = epub.EpubHtml(title="One", file_name="Text/chapter_1.xhtml", lang="en")
    chapter.content = """
    <html xmlns="http://www.w3.org/1999/xhtml">
      <body>
        <div class="chapter">
          <h1>Chapter One</h1>
          <p>First sentence. <em>Second sentence.</em></p>
          <p><a href="next.xhtml">Linked sentence.</a></p>
        </div>
      </body>
    </html>
    """
    chapter_two = epub.EpubHtml(title="Two", file_name="Text/chapter_2.xhtml", lang="en")
    chapter_two.content = "<p>Third sentence.</p>"
    book.add_item(chapter)
    book.add_item(chapter_two)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", chapter, chapter_two]
    book.toc = (
        epub.Link("Text/chapter_1.xhtml", "One", "one"),
        epub.Link("Text/chapter_2.xhtml", "Two", "two"),
    )
    epub.write_epub(path, book, {})


def _simple_sentence_split(text: str) -> list[str]:
    if "." not in text:
        return [text.strip()]
    return [f"{chunk.strip()}." for chunk in text.split(".") if chunk.strip()]


@pytest.mark.asyncio
async def test_ingestion_preserves_nested_markup_and_records_spine_file(db, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    epub_path = library_path / "nested.epub"
    _write_nested_epub(epub_path)
    book = await _make_book(
        db,
        immutable_path=str(epub_path.relative_to(library_path.parent)),
        current_path=str(epub_path.relative_to(library_path.parent)),
    )
    monkeypatch.setattr(audiobook_ingestion, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_ingestion, "_tokenize_text", _simple_sentence_split)

    await audiobook_ingestion.ingest_epub(book.id, db)

    chapters = await crud.audiobook.get_chapters_for_book(db, book.id)
    assert [chapter.content_file_name for chapter in chapters] == [
        "Text/chapter_1.xhtml",
        "Text/chapter_2.xhtml",
    ]

    working_epub = library_path / "audiobooks" / str(book.id) / "working.epub"
    parsed = epub.read_epub(str(working_epub))
    item = parsed.get_item_with_href("Text/chapter_1.xhtml")
    soup = BeautifulSoup(item.get_content(), "html.parser")

    assert soup.find("div", class_="chapter") is not None
    assert soup.find("p") is not None
    assert soup.find("em") is not None
    assert soup.find("a", href="next.xhtml") is not None
    assert soup.find("span", id="ch1_s0") is not None
    assert soup.find("span", id="ch1_s1") is not None


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for MP3 assembly")
async def test_offline_harness_builds_downloadable_media_overlay_epub(db, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    epub_path = library_path / "offline.epub"
    _write_nested_epub(epub_path)
    book = await _make_book(
        db,
        audiobook_enabled=True,
        immutable_path=str(epub_path.relative_to(library_path.parent)),
        current_path=str(epub_path.relative_to(library_path.parent)),
    )
    for module in (audiobook_ingestion, audiobook_tts, audiobook_assembly):
        monkeypatch.setattr(module, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_ingestion, "_tokenize_text", _simple_sentence_split)

    await audiobook_ingestion.ingest_epub(book.id, db)
    await audiobook_llm.generate_character_roster(book.id, db)
    await audiobook_llm.diarize_sentences(book.id, db)
    await audiobook_tts.generate_audio_for_book(book.id, db)
    await audiobook_assembly.assemble_book(book.id, db)

    await db.refresh(book)
    characters = await crud.audiobook.get_characters_for_book(db, book.id)
    counts = await crud.audiobook.count_sentences_by_status(db, book.id)
    output_path = library_path / "audiobooks" / str(book.id) / "audiobook.epub"

    assert book.audiobook_pipeline_status == "complete"
    assert [(character.name, character.is_narrator) for character in characters] == [("Narrator", True)]
    assert counts == {"audio_generated": 5}
    assert output_path.exists()
    with zipfile.ZipFile(output_path) as archive:
        names = archive.namelist()
        assert "EPUB/ch0001.mp3" in names
        assert "EPUB/ch0001.smil" in names
        package = archive.read("EPUB/content.opf").decode("utf-8")
        assert 'media-type="application/smil+xml"' in package
        assert 'media-overlay="smil_ch0001"' in package

    monkeypatch.setattr(audiobook_router, "LIBRARY_PATH", library_path)
    response = await audiobook_router.download_audiobook(book.id, db)
    assert Path(response.path) == output_path
    assert response.media_type == "application/epub+zip"
