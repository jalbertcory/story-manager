import asyncio
import json
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
    def __init__(self, *, active_book_ids: set[int] | None = None):
        self.enqueued: list[int] = []
        self.active_book_ids = active_book_ids or set()
        self.preview_enqueued: list[tuple[int, int]] = []

    async def enqueue(self, book_id: int) -> bool:
        self.enqueued.append(book_id)
        return True

    def has_book_job(self, book_id: int) -> bool:
        return book_id in self.active_book_ids

    async def enqueue_preview(self, book_id: int, chapter_id: int) -> bool:
        self.preview_enqueued.append((book_id, chapter_id))
        return True


def test_default_roster_prompt_formats_voice_token_examples():
    prompt = audiobook_llm.DEFAULT_ROSTER_PROMPT.format(
        text="A story excerpt.",
        candidate_hints="- Harry: 12 mentions",
        series_roster="(none yet)",
    )

    assert "[gender-{male|female|neutral}]" in prompt
    assert "A story excerpt." in prompt


def test_tagged_text_sanitizer_only_accepts_supported_insertions():
    original = "Take your time, I said."

    assert audiobook_llm._sanitize_tagged_text(original, "[whisper] Take your time, I said.") == (
        "[whisper] Take your time, I said."
    )
    assert audiobook_llm._sanitize_tagged_text(original, "[fade in] Take your time, I said.") == original
    assert audiobook_llm._sanitize_tagged_text(original, "I completely rewrote this sentence.") == original


def test_speaker_guardrails_keep_prose_on_narrator_and_route_unnamed_dialogue():
    prose = audiobook_llm._apply_speaker_guardrails(
        text="I sat down and waited.",
        next_text="",
        character_id=20,
        narrator_id=10,
        minor_female_id=30,
        minor_male_id=40,
        reason="Action description by the protagonist.",
    )
    dialogue = audiobook_llm._apply_speaker_guardrails(
        text="“You coming or going?”",
        next_text="she asked without looking up.",
        character_id=10,
        narrator_id=10,
        minor_female_id=30,
        minor_male_id=40,
        reason="Dialogue attributed to the unnamed recruiter.",
    )
    setup = audiobook_llm._apply_speaker_guardrails(
        text="The recruiter looked up. “",
        next_text="Hello,” she said.",
        character_id=10,
        narrator_id=10,
        minor_female_id=30,
        minor_male_id=40,
        reason="Narration setting up dialogue.",
    )

    assert prose == (10, "Deterministic prose/narration guardrail", 0.98)
    assert dialogue == (30, "Deterministic she dialogue attribution to minor voice", 0.98)
    assert setup == (10, "Narration setting up dialogue.", None)


@pytest.mark.asyncio
async def test_ollama_call_requests_schema_constrained_non_thinking_json(monkeypatch):
    captured = {}

    class FakeResponse:
        is_error = False

        def json(self):
            return {"message": {"content": json.dumps({"status": "ready"})}}

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["request"] = kwargs
            return FakeResponse()

    monkeypatch.setattr(audiobook_llm.httpx, "AsyncClient", FakeClient)
    settings = models.AudiobookSettings(
        llm_provider="ollama",
        llm_base_url="http://127.0.0.1:11434",
        llm_model="qwen3.5:27b",
    )
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
    }

    raw = await audiobook_llm._call_llm(
        settings,
        [{"role": "user", "content": "ready?"}],
        response_schema=schema,
    )

    assert json.loads(raw) == {"status": "ready"}
    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    payload = captured["request"]["json"]
    assert payload["model"] == "qwen3.5:27b"
    assert payload["think"] is False
    assert payload["format"] == schema
    assert payload["options"]["temperature"] == 0


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
async def test_rebuild_rejects_an_active_pipeline(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True, audiobook_pipeline_status="diarizing")
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    with pytest.raises(audiobook_router.HTTPException) as exc_info:
        await audiobook_router.rebuild_pipeline(book.id, db)

    assert exc_info.value.status_code == 409
    assert queue.enqueued == []


@pytest.mark.asyncio
async def test_rebuild_waits_for_a_paused_worker_to_exit(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True, audiobook_pipeline_status="paused")
    queue = _FakeQueue(active_book_ids={book.id})
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    with pytest.raises(audiobook_router.HTTPException) as exc_info:
        await audiobook_router.rebuild_pipeline(book.id, db)

    assert exc_info.value.status_code == 409
    assert queue.enqueued == []


@pytest.mark.asyncio
async def test_sentence_speaker_must_belong_to_the_same_book(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True)
    other_book = await _make_book(db, title="Other Audio", audiobook_enabled=True)
    _chapter, _character, sentence = await _seed_audio_chapter(db, book.id)
    _other_chapter, other_character, _other_sentence = await _seed_audio_chapter(db, other_book.id)
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    with pytest.raises(audiobook_router.HTTPException) as exc_info:
        await audiobook_router.update_sentence(
            sentence.id,
            audiobook_router.SentenceUpdate(character_id=other_character.id, tagged_text=sentence.original_text),
            db,
        )

    await db.refresh(sentence)
    assert exc_info.value.status_code == 404
    assert sentence.character_id != other_character.id
    assert queue.enqueued == []


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
async def test_run_batch_persists_one_unit_limit(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True, audiobook_pipeline_status="paused")
    await _seed_audio_chapter(db, book.id, sentence_status="ready_for_audio")
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    response = await audiobook_router.run_pipeline_batch(book.id, db)

    await db.refresh(book)
    assert response == {
        "status": "audio_gen",
        "queued": True,
        "batch_limit": 1,
    }
    assert book.audiobook_pipeline_status == "audio_gen"
    assert book.audiobook_batch_limit == 1
    assert queue.enqueued == [book.id]


@pytest.mark.asyncio
async def test_review_filter_excludes_pending_and_keeps_uncertain_assignments(db):
    book = await _make_book(db, audiobook_enabled=True)
    chapter, character, sentence = await _seed_audio_chapter(
        db,
        book.id,
        sentence_status="ready_for_audio",
    )
    sentence.speaker_confidence = 0.4
    sentence.speaker_reason = "Ambiguous dialogue turn"
    await crud.audiobook.create_sentences_bulk(
        db,
        chapter_id=chapter.id,
        sentences_data=[
            {
                "html_element_id": "ch1_s1",
                "sequence_order": 1,
                "original_text": "Pending.",
                "status": "pending_diarization",
            },
            {
                "html_element_id": "ch1_s2",
                "sequence_order": 2,
                "original_text": "Certain.",
                "tagged_text": "Certain.",
                "character_id": character.id,
                "speaker_confidence": 0.95,
                "status": "ready_for_audio",
            },
        ],
    )

    review, total = await crud.audiobook.get_sentences_paginated(
        db,
        book.id,
        review_only=True,
    )

    assert total == 1
    assert [item.original_text for item in review] == ["One sentence."]


@pytest.mark.asyncio
async def test_roster_rebuild_preserves_ingestion_and_clears_derived_analysis(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True, audiobook_pipeline_status="paused")
    chapter, _character, sentence = await _seed_audio_chapter(
        db,
        book.id,
        sentence_status="audio_generated",
    )
    chapter.summary = "Old summary"
    sentence.speaker_confidence = 0.9
    sentence.audio_file_path = "library/audiobooks/1/snippets/1.mp3"
    await db.commit()
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    response = await audiobook_router.rebuild_character_roster(book.id, db)

    await db.refresh(book)
    await db.refresh(chapter)
    await db.refresh(sentence)
    assert response == {
        "status": "roster_gen",
        "queued": True,
        "stop_after_phase": "roster_gen",
    }
    assert book.audiobook_pipeline_status == "roster_gen"
    assert sentence.status == "pending_diarization"
    assert sentence.character_id is None
    assert sentence.speaker_confidence is None
    assert sentence.audio_file_path is None
    assert chapter.summary is None
    assert await crud.audiobook.get_characters_for_book(db, book.id) == []
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
async def test_roster_excerpt_skips_short_front_matter(db):
    book = await _make_book(db, audiobook_enabled=True)
    front = await crud.audiobook.create_chapter(db, book.id, 1, "front.xhtml")
    await crud.audiobook.create_sentences_bulk(
        db,
        front.id,
        [
            {
                "html_element_id": "front_0",
                "sequence_order": 0,
                "original_text": "Copyright page only.",
                "status": "pending_diarization",
            }
        ],
    )
    story = await crud.audiobook.create_chapter(db, book.id, 2, "story.xhtml")
    await crud.audiobook.create_sentences_bulk(
        db,
        story.id,
        [
            {
                "html_element_id": f"story_{index}",
                "sequence_order": index,
                "original_text": f"John and Kathy continue the story in sentence {index}.",
                "status": "pending_diarization",
            }
            for index in range(40)
        ],
    )

    excerpt = await audiobook_llm._build_roster_excerpt(
        await crud.audiobook.get_chapters_for_book(db, book.id),
        db,
    )

    assert "Copyright page only" not in excerpt
    assert "John and Kathy continue the story" in excerpt
    assert "### Chapter 2" in excerpt


@pytest.mark.asyncio
async def test_roster_keeps_first_person_protagonist_separate_from_narrator(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True)
    settings = models.AudiobookSettings(
        llm_provider="ollama",
        llm_base_url="http://ollama.test",
        llm_model="qwen-test",
    )
    db.add(settings)
    chapter = await crud.audiobook.create_chapter(db, book.id, 1, "story.xhtml")
    await crud.audiobook.create_sentences_bulk(
        db,
        chapter.id,
        [
            {
                "html_element_id": f"story_{index}",
                "sequence_order": index,
                "original_text": f'Harry said, "John, sentence {index}."',
                "status": "pending_diarization",
            }
            for index in range(40)
        ],
    )
    captured = {}

    async def fake_call(_settings, messages, **_kwargs):
        captured["prompt"] = messages[0]["content"]
        return json.dumps(
            {
                "book_summary": "John tells a story.",
                "characters": [
                    {
                        "name": "John Perry",
                        "aliases": ["Narrator"],
                        "description": "First-person protagonist.",
                        "evidence": ["John speaks."],
                        "voice_design_prompt": "[gender-male][pitch-medium][speed-normal]",
                        "is_narrator": True,
                    }
                ],
            }
        )

    monkeypatch.setattr(audiobook_llm, "_call_llm", fake_call)

    await audiobook_llm.generate_character_roster(book.id, db)

    characters = await crud.audiobook.get_characters_for_book(db, book.id)
    assert [(character.name, character.is_narrator) for character in characters] == [
        ("Narrator", True),
        ("Harry", False),
        ("John Perry", False),
        ("Minor Female Voice", False),
        ("Minor Male Voice", False),
    ]
    assert characters[2].aliases == []
    assert "40 explicit dialogue attributions" in characters[1].description
    assert "Harry: 40 mentions" in captured["prompt"]


@pytest.mark.asyncio
async def test_series_roster_reuses_and_propagates_voice_profiles(db):
    first = await _make_book(db, title="Saga One", series="Shared Saga", audiobook_enabled=True)
    second = await _make_book(db, title="Saga Two", series="Shared Saga", audiobook_enabled=True)
    first_character = (
        await crud.audiobook.create_characters_bulk(
            db,
            first.id,
            [
                {
                    "name": "Captain Vale",
                    "description": "Series captain.",
                    "voice_design_prompt": "[gender-female][pitch-low][speed-normal]",
                    "is_narrator": False,
                    "aliases": ["Vale"],
                    "evidence": [],
                }
            ],
        )
    )[0]
    second_character = (
        await crud.audiobook.create_characters_bulk(
            db,
            second.id,
            [
                {
                    "name": "Captain Vale",
                    "description": "Book-specific guess.",
                    "voice_design_prompt": "[gender-neutral][pitch-high][speed-fast]",
                    "is_narrator": False,
                    "aliases": [],
                    "evidence": [],
                }
            ],
        )
    )[0]

    await crud.audiobook.sync_book_roster_with_series(db, first, [first_character])
    await crud.audiobook.sync_book_roster_with_series(db, second, [second_character])
    await db.refresh(second_character)

    assert second_character.series_character_id == first_character.series_character_id
    assert second_character.voice_design_prompt == "[gender-female][pitch-low][speed-normal]"

    first_character.voice_design_prompt = "[gender-female][pitch-medium][speed-slow]"
    await db.commit()
    linked = await crud.audiobook.propagate_character_profile_across_series(db, first_character)
    await db.refresh(second_character)

    assert {character.book_id for character in linked} == {first.id, second.id}
    assert second_character.voice_design_prompt == "[gender-female][pitch-medium][speed-slow]"

    # Renaming onto an existing canonical identity merges the shared profiles
    # instead of violating the series/name uniqueness constraint.
    other_character = (
        await crud.audiobook.create_characters_bulk(
            db,
            first.id,
            [
                {
                    "name": "Commander Vale",
                    "voice_design_prompt": "[gender-female][pitch-high][speed-normal]",
                    "is_narrator": False,
                }
            ],
        )
    )[0]
    await crud.audiobook.sync_book_roster_with_series(db, first, [other_character])
    other_character.name = "Captain Vale"
    await db.commit()
    await crud.audiobook.propagate_character_profile_across_series(db, other_character)
    await db.refresh(other_character)
    assert other_character.series_character_id == first_character.series_character_id


@pytest.mark.asyncio
async def test_manual_chapter_preview_requires_analysis_and_queues_work(db, monkeypatch):
    book = await _make_book(db, audiobook_enabled=True, audiobook_pipeline_status="paused")
    chapter, _character, sentence = await _seed_audio_chapter(db, book.id)
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)

    response = await audiobook_router.generate_chapter_preview(book.id, chapter.id, db)
    await db.refresh(chapter)

    assert response == {"status": "queued", "queued": True, "chapter_id": chapter.id}
    assert queue.preview_enqueued == [(book.id, chapter.id)]
    assert chapter.preview_status == "queued"

    sentence.status = "pending_diarization"
    chapter.preview_status = None
    await db.commit()
    with pytest.raises(audiobook_router.HTTPException) as exc_info:
        await audiobook_router.generate_chapter_preview(book.id, chapter.id, db)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for MP3 assembly")
async def test_manual_chapter_preview_generates_playable_audio(db, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    book = await _make_book(db, audiobook_enabled=True, audiobook_pipeline_status="paused")
    chapter, _character, _sentence = await _seed_audio_chapter(db, book.id)
    monkeypatch.setattr(audiobook_tts, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_assembly, "LIBRARY_PATH", library_path)

    await audiobook_tts.generate_audio_for_chapter_preview(book.id, chapter.id, db)
    await audiobook_assembly.assemble_chapter_preview(book.id, chapter.id, db)
    await db.refresh(chapter)

    assert chapter.audio_file_path
    assert (library_path.parent / chapter.audio_file_path).exists()
    assert chapter.smil_file_path


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

    output_path.unlink()
    monkeypatch.setattr(crud.audiobook, "LIBRARY_PATH", library_path)
    assert await crud.audiobook.infer_audiobook_resume_status(db, book.id) == "assembling"

    await audiobook_assembly.assemble_book(book.id, db)

    await db.refresh(book)
    assert output_path.exists()
    assert book.audiobook_pipeline_status == "complete"
