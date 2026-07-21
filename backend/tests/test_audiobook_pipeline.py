import asyncio
import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from bs4 import BeautifulSoup
from ebooklib import epub
from mutagen.mp3 import MP3

from backend.app import crud, models
from backend.app.routers import audiobook as audiobook_router
from backend.app.services import (
    audiobook_assembly,
    audiobook_ingestion,
    audiobook_llm,
    audiobook_publication,
    audiobook_tts,
    web_novel,
)
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
                "voice_prompt": "[gender-neutral][pitch-medium][speed-normal]",
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
        self.sentence_enqueued: list[tuple[int, int]] = []

    async def enqueue(self, book_id: int) -> bool:
        self.enqueued.append(book_id)
        return True

    def has_book_job(self, book_id: int) -> bool:
        return book_id in self.active_book_ids

    async def enqueue_preview(self, book_id: int, chapter_id: int) -> bool:
        self.preview_enqueued.append((book_id, chapter_id))
        return True

    async def enqueue_sentence_audio(self, book_id: int, sentence_id: int) -> bool:
        self.sentence_enqueued.append((book_id, sentence_id))
        return True


def test_default_roster_prompt_formats_voice_token_examples():
    prompt = audiobook_llm.DEFAULT_ROSTER_PROMPT.format(
        text="A story excerpt.",
        candidate_hints="- Harry: 12 mentions",
        series_roster="(none yet)",
    )

    assert "[gender-{male|female|neutral}]" in prompt
    assert "A story excerpt." in prompt


def test_diarization_schema_keeps_model_output_compact():
    properties = audiobook_llm.DIARIZATION_SCHEMA["properties"]["assignments"]["items"]["properties"]

    assert set(properties) == {"i", "c", "e"}
    assert "tagged_text" not in properties
    assert "confidence" not in properties
    assert "reason" not in properties
    assert properties["e"]["enum"] == [None, "laughter", "sigh", "whisper", "shout"]
    assert "chapter_summary" not in audiobook_llm.DIARIZATION_SCHEMA["properties"]


def test_diarization_schema_requires_exact_assignment_count():
    schema = audiobook_llm._diarization_schema(7)
    assignments = schema["properties"]["assignments"]

    assert assignments["minItems"] == 7
    assert assignments["maxItems"] == 7
    assert "minItems" not in audiobook_llm.DIARIZATION_SCHEMA["properties"]["assignments"]


def test_only_quoted_spans_require_model_diarization():
    sentences = [
        SimpleNamespace(id=1, original_text="Plain narration."),
        SimpleNamespace(id=2, original_text="“This dialogue starts"),
        SimpleNamespace(id=3, original_text="and continues across a sentence"),
        SimpleNamespace(id=4, original_text="before ending here.”"),
        SimpleNamespace(id=5, original_text="Narration resumes."),
    ]

    assert audiobook_llm._sentence_ids_requiring_diarization(sentences) == {
        2,
        3,
        4,
    }


def test_tagged_text_sanitizer_only_accepts_supported_insertions():
    original = "Take your time, I said."

    assert audiobook_llm._sanitize_tagged_text(original, "[whisper] Take your time, I said.") == (
        "[whisper] Take your time, I said."
    )
    assert audiobook_llm._sanitize_tagged_text(original, "[fade in] Take your time, I said.") == original
    assert audiobook_llm._sanitize_tagged_text(original, "I completely rewrote this sentence.") == original


def test_diarization_parser_deduplicates_repeated_sentence_ids():
    raw = json.dumps(
        {
            "assignments": [
                {"id": 7, "character_id": 1, "confidence": 0.4, "reason": "First"},
                {"id": 7, "character_id": 2, "confidence": 0.9, "reason": "Better"},
            ],
            "chapter_summary": "Summary",
        }
    )

    result, missing_ids, salvaged = audiobook_llm._parse_diarization_response(raw, [7])

    assert result["assignments"][0]["id"] == 7
    assert result["assignments"][0]["character_id"] == 2
    assert result["assignments"][0]["confidence"] == 0.9
    assert result["assignments"][0]["reason"] == "Better"
    assert missing_ids == set()
    assert salvaged is False


def test_diarization_parser_normalizes_compact_wire_keys():
    raw = json.dumps(
        {
            "assignments": [
                {"i": 7, "c": 11, "e": "whisper"},
            ]
        }
    )

    result, missing_ids, salvaged = audiobook_llm._parse_diarization_response(raw, [7])

    assert result["assignments"][0]["id"] == 7
    assert result["assignments"][0]["character_id"] == 11
    assert result["assignments"][0]["expression"] == "whisper"
    assert missing_ids == set()
    assert salvaged is False


def test_diarization_parser_salvages_complete_assignments_from_truncated_json():
    raw = (
        '{"assignments":['
        '{"id":7,"character_id":1,"tagged_text":null,"confidence":0.9,"reason":"Narration"},'
        '{"id":8,"character_id":'
    )

    result, missing_ids, salvaged = audiobook_llm._parse_diarization_response(raw, [7, 8])

    assert [assignment["id"] for assignment in result["assignments"]] == [7]
    assert missing_ids == {8}
    assert salvaged is True


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
    assert payload["options"]["num_predict"] == 8192


@pytest.mark.asyncio
async def test_ollama_call_streams_progress_when_callback_is_provided(monkeypatch):
    captured = {}

    class FakeResponse:
        is_error = False
        status_code = 200
        text = ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def aiter_lines(self):
            yield json.dumps({"message": {"content": "a" * 1024}, "done": False})
            yield json.dumps({"message": {"content": "finished"}, "done": True})

        async def aread(self):
            return b""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def __init__(self, **_kwargs):
            pass

        def stream(self, method, url, **kwargs):
            captured["method"] = method
            captured["url"] = url
            captured["request"] = kwargs
            return FakeResponse()

    monkeypatch.setattr(audiobook_llm.httpx, "AsyncClient", FakeClient)
    settings = models.AudiobookSettings(
        llm_provider="ollama",
        llm_base_url="http://127.0.0.1:11434",
        llm_model="qwen3.5:9b",
    )
    progress = []

    raw = await audiobook_llm._call_llm(
        settings,
        [{"role": "user", "content": "stream"}],
        response_schema={"type": "object"},
        progress_callback=lambda received: _record_progress(progress, received),
    )

    assert raw == ("a" * 1024) + "finished"
    assert progress == [1024, 1032]
    assert captured["method"] == "POST"
    assert captured["request"]["json"]["stream"] is True


@pytest.mark.asyncio
async def test_ollama_call_preserves_retryable_http_status(monkeypatch):
    class FakeResponse:
        is_error = True

        def raise_for_status(self):
            request = httpx.Request("POST", "http://ollama.test/api/chat")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("service unavailable", request=request, response=response)

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(audiobook_llm.httpx, "AsyncClient", FakeClient)
    settings = models.AudiobookSettings(
        llm_provider="ollama",
        llm_base_url="http://ollama.test",
        llm_model="qwen-test",
    )

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await audiobook_llm._call_llm(
            settings,
            [{"role": "user", "content": "retry"}],
        )

    assert exc_info.value.response.status_code == 503


async def _record_progress(progress, received):
    progress.append(received)


@pytest.mark.asyncio
async def test_diarization_retries_truncated_output_with_smaller_batches(db, monkeypatch):
    monkeypatch.setattr(audiobook_llm, "DIARIZATION_BATCH_SIZE", 40)
    book = await _make_book(
        db,
        audiobook_enabled=True,
        audiobook_pipeline_status="diarizing",
    )
    settings = models.AudiobookSettings(
        llm_provider="ollama",
        llm_base_url="http://ollama.test",
        llm_model="qwen-test",
    )
    db.add(settings)
    chapter = await crud.audiobook.create_chapter(db, book.id, 1, "story.xhtml")
    narrator = (
        await crud.audiobook.create_characters_bulk(
            db,
            book.id,
            [
                {
                    "name": "Narrator",
                    "description": "Primary narrator",
                    "voice_prompt": "[gender-neutral][pitch-medium][speed-normal]",
                    "is_narrator": True,
                }
            ],
        )
    )[0]
    await crud.audiobook.create_sentences_bulk(
        db,
        chapter.id,
        [
            {
                "html_element_id": f"story_{index}",
                "sequence_order": index,
                "original_text": f"“Story sentence {index}.”",
                "status": "pending_diarization",
            }
            for index in range(80)
        ],
    )
    request_sizes = []

    async def fake_call(_settings, messages, **_kwargs):
        prompt = messages[0]["content"]
        sentences_text = prompt.split(
            "Sentences to process (JSON array with id, text, and its immediate previous/next context):\n",
            1,
        )[1].split("\n\nFor each sentence", 1)[0]
        sentences = json.loads(sentences_text)
        request_sizes.append(len(sentences))
        if len(sentences) == 40 and request_sizes.count(40) == 1:
            return '{"assignments":[{"id":' + str(sentences[0]["id"]) + ',"reason":"truncated'
        return json.dumps(
            {
                "assignments": [
                    {
                        "id": sentence["id"],
                        "character_id": narrator.id,
                        "tagged_text": None,
                        "confidence": 0.95,
                        "reason": "Narration",
                    }
                    for sentence in sentences
                ],
                "chapter_summary": "The story continues.",
            }
        )

    monkeypatch.setattr(audiobook_llm, "_call_llm", fake_call)
    ready_batches = []

    async def record_ready(sentence_ids):
        ready_batches.append(sentence_ids)

    await audiobook_llm.diarize_sentences(
        book.id,
        db,
        on_sentences_ready=record_ready,
    )

    await db.refresh(book)
    sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
    assert request_sizes == [40, 20, 40, 20]
    assert {sentence.status for sentence in sentences} == {"ready_for_audio"}
    assert {sentence.character_id for sentence in sentences} == {narrator.id}
    assert book.audiobook_pipeline_status == "audio_gen"
    assert book.audiobook_llm_requests == 4
    assert [len(sentence_ids) for sentence_ids in ready_batches] == [20, 40, 20]


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
async def test_queue_stop_cancels_long_running_pipeline_work(monkeypatch):
    queue = AudiobookQueue()
    started = asyncio.Event()
    never_finishes = asyncio.Event()

    async def process(_book_id: int) -> None:
        started.set()
        await never_finishes.wait()

    monkeypatch.setattr(queue, "_process", process)
    await queue.start()
    await queue.enqueue(42)
    await started.wait()

    await asyncio.wait_for(queue.stop(), timeout=1)

    assert queue._worker_task is None
    assert queue._background_audio_tasks == []


@pytest.mark.asyncio
async def test_manual_sentence_audio_uses_independent_tts_lane():
    queue = AudiobookQueue()

    assert await queue.enqueue_sentence_audio(7, 42) is True

    assert queue._queue.empty()
    assert (await queue._background_audio_queue.get())[2] == (7, [42], True)
    queue._background_audio_queue.task_done()


@pytest.mark.asyncio
async def test_pipeline_audio_is_queued_in_model_batches(monkeypatch):
    monkeypatch.setattr(audiobook_queue, "TTS_BATCH_SIZE", 3)
    queue = AudiobookQueue()

    await queue.enqueue_background_audio(7, [10, 11, 12, 13, 14, 15, 16])

    batches = [(await queue._background_audio_queue.get())[2] for _ in range(3)]
    assert batches == [
        (7, [10, 11, 12], False),
        (7, [13, 14, 15], False),
        (7, [16], False),
    ]
    assert queue._background_audio_ids == {7: {10, 11, 12, 13, 14, 15, 16}}
    for _ in batches:
        queue._background_audio_queue.task_done()


@pytest.mark.asyncio
async def test_waiting_audio_lane_publishes_phase_accurate_progress(
    db,
    sqlite_sessionmaker,
    monkeypatch,
):
    book = await _make_book(
        db,
        audiobook_enabled=True,
        audiobook_pipeline_status="audio_gen",
    )
    _chapter, _character, sentence = await _seed_audio_chapter(
        db,
        book.id,
        sentence_status="ready_for_audio",
    )
    monkeypatch.setattr(audiobook_queue, "SessionLocal", sqlite_sessionmaker)
    queue = AudiobookQueue()
    queue._background_audio_ids = {book.id: {sentence.id}}

    waiter = asyncio.create_task(queue._wait_for_background_audio(book.id))
    try:
        for _ in range(50):
            await db.refresh(book)
            if book.audiobook_progress_detail and book.audiobook_progress_detail.startswith("Generating speech:"):
                break
            await asyncio.sleep(0.01)

        assert book.audiobook_progress_current == 0
        assert book.audiobook_progress_total == 1
        assert book.audiobook_progress_detail == "Generating speech: 0 of 1 clips (1 queued)"
    finally:
        async with queue._background_audio_condition:
            queue._background_audio_ids.pop(book.id, None)
            queue._background_audio_condition.notify_all()
        await waiter


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
    refreshed = await _make_book(
        db,
        title="Refreshed Audio",
        audiobook_enabled=True,
        audiobook_pipeline_status="complete",
        audiobook_source_content_version=1,
    )
    await crud.touch_book_content(db, refreshed)
    await db.commit()

    pending = await crud.audiobook.get_in_progress_audiobook_books(db)

    assert [book.id for book in pending] == [enabled.id, refreshed.id]
    assert refreshed.audiobook_pending_content_version == refreshed.content_version


@pytest.mark.asyncio
async def test_queue_restarts_ingestion_for_refresh_received_during_generation(db, sqlite_sessionmaker, monkeypatch):
    book = await _make_book(
        db,
        audiobook_enabled=True,
        audiobook_pipeline_status="audio_gen",
        audiobook_source_content_version=1,
    )
    await crud.touch_book_content(db, book)
    await db.commit()
    monkeypatch.setattr(audiobook_queue, "SessionLocal", sqlite_sessionmaker)

    restarted = await AudiobookQueue()._restart_for_pending_content(book.id)

    await db.refresh(book)
    assert restarted is True
    assert book.audiobook_pipeline_status == "ingesting"
    assert book.audiobook_pending_content_version == book.content_version


@pytest.mark.asyncio
async def test_web_refresh_enqueues_enabled_audiobook_without_duplicate_active_job(db, monkeypatch):
    queued_book = await _make_book(
        db,
        audiobook_enabled=True,
        audiobook_pipeline_status="complete",
        audiobook_source_content_version=1,
    )
    active_book = await _make_book(
        db,
        title="Already Building",
        audiobook_enabled=True,
        audiobook_pipeline_status="diarizing",
        audiobook_source_content_version=1,
    )
    await crud.touch_book_content(db, queued_book)
    await crud.touch_book_content(db, active_book)
    await db.commit()
    queue = _FakeQueue(active_book_ids={active_book.id})
    monkeypatch.setattr(audiobook_queue, "get_audiobook_queue", lambda: queue)

    await web_novel._enqueue_audiobook_refresh(queued_book, db)
    await web_novel._enqueue_audiobook_refresh(active_book, db)

    await db.refresh(queued_book)
    await db.refresh(active_book)
    assert queued_book.audiobook_pipeline_status == "ingesting"
    assert active_book.audiobook_pipeline_status == "diarizing"
    assert queue.enqueued == [queued_book.id]


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
async def test_restarted_audio_phase_rebuilds_length_bucketed_background_queue(
    db,
    sqlite_sessionmaker,
    monkeypatch,
):
    book = await _make_book(
        db,
        audiobook_enabled=True,
        audiobook_pipeline_status="audio_gen",
        audiobook_stop_after_phase="audio_gen",
    )
    _chapter, _character, sentence = await _seed_audio_chapter(
        db,
        book.id,
        sentence_status="ready_for_audio",
    )
    queue = AudiobookQueue()
    enqueued: list[tuple[int, list[int]]] = []

    async def record_background_audio(book_id, sentence_ids):
        enqueued.append((book_id, sentence_ids))

    async def finish_audio(book_id, phase_db):
        await crud.audiobook.set_book_pipeline_status(phase_db, book_id, "assembling")

    async def wait_for_audio(_book_id):
        return None

    monkeypatch.setattr(audiobook_queue, "SessionLocal", sqlite_sessionmaker)
    monkeypatch.setattr(queue, "enqueue_background_audio", record_background_audio)
    monkeypatch.setattr(queue, "_wait_for_background_audio", wait_for_audio)
    monkeypatch.setattr(audiobook_queue, "generate_audio_for_book", finish_audio)

    await queue._process(book.id)

    assert enqueued == [(book.id, [sentence.id])]


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
    settings = models.AudiobookSettings(
        tts_provider="omnivoice",
        tts_base_url="http://tts.example.test",
    )
    db.add(settings)
    await db.commit()

    async def fail_tts(_settings, _request):
        request = httpx.Request("POST", "http://tts.example.test/generate")
        raise httpx.ConnectError("connection failed", request=request)

    monkeypatch.setattr(audiobook_tts, "synthesize_speech", fail_tts)

    with pytest.raises(RuntimeError, match="TTS failed"):
        await audiobook_tts.generate_audio_for_book(book.id, db)

    sentence = (await crud.audiobook.get_sentences_for_chapter(db, chapter.id))[0]
    await db.refresh(book)
    await db.refresh(sentence)
    assert book.audiobook_pipeline_status == "error"
    assert sentence.status == "error"
    assert sentence.audio_file_path is None


@pytest.mark.asyncio
async def test_provider_change_clears_stored_tts_api_key(db):
    settings = models.AudiobookSettings(
        tts_provider="openai",
        tts_api_key="openai-secret",
        tts_model="tts-1",
        tts_default_voice="alloy",
    )
    db.add(settings)
    await db.commit()

    response = await audiobook_router.update_settings(
        audiobook_router.SettingsUpdate(
            tts_provider="openai-compatible",
            tts_base_url="http://127.0.0.1:8880",
            tts_model="kokoro",
            tts_default_voice="af_heart",
        ),
        db,
    )
    await db.refresh(settings)

    assert response.tts_provider == "openai-compatible"
    assert response.tts_api_key_set is False
    assert settings.tts_api_key is None


@pytest.mark.asyncio
async def test_character_voice_id_is_tagged_and_used_only_for_its_provider(db):
    book = await _make_book(db, audiobook_enabled=True)
    character = (
        await crud.audiobook.create_characters_bulk(
            db,
            book.id,
            [
                {
                    "name": "Narrator",
                    "voice_prompt": "[gender-neutral][pitch-medium][speed-normal]",
                    "is_narrator": True,
                }
            ],
        )
    )[0]
    settings = models.AudiobookSettings(
        tts_provider="elevenlabs",
        tts_api_key="secret",
        tts_default_voice="default-id",
    )
    db.add(settings)
    await db.commit()

    updated = await audiobook_router.update_character(
        character.id,
        audiobook_router.CharacterUpdate(tts_voice_id="character-id"),
        db,
    )
    await db.refresh(character)

    assert updated.tts_voice_provider == "elevenlabs"
    assert character.tts_voice_provider == "elevenlabs"
    assert audiobook_tts._voice_id_for_provider(settings, character) == "character-id"

    settings.tts_provider = "openai"
    assert audiobook_tts._voice_id_for_provider(settings, character) is None


@pytest.mark.asyncio
async def test_tts_settings_invalidate_only_unfinished_books_below_eighty_percent(db, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    monkeypatch.setattr(crud.audiobook, "LIBRARY_PATH", library_path)

    async def seed_book(title: str, pipeline_status: str, generated: int):
        book = await _make_book(
            db,
            title=title,
            audiobook_enabled=True,
            audiobook_pipeline_status=pipeline_status,
        )
        chapter = await crud.audiobook.create_chapter(
            db,
            book_id=book.id,
            chapter_number=1,
            content_file_name="Text/chapter.xhtml",
        )
        chapter.needs_reassembly = False
        await crud.audiobook.create_sentences_bulk(
            db,
            chapter.id,
            [
                {
                    "html_element_id": f"{book.id}-{index}",
                    "sequence_order": index,
                    "original_text": f"Sentence {index}.",
                    "tagged_text": f"Sentence {index}.",
                    "status": "audio_generated" if index < generated else "ready_for_audio",
                    "audio_file_path": f"library/audiobooks/{book.id}/snippets/{index}.mp3" if index < generated else None,
                    "audio_duration_ms": 1000 if index < generated else None,
                }
                for index in range(5)
            ],
        )
        return book, chapter

    low_book, low_chapter = await seed_book("Low Progress", "paused", 3)
    edge_book, edge_chapter = await seed_book("Edge Progress", "paused", 4)
    complete_book, complete_chapter = await seed_book("Complete Book", "complete", 3)

    invalidated = await crud.audiobook.invalidate_generated_audio_for_tts_change(db)

    assert invalidated == [low_book.id]
    assert await crud.audiobook.count_sentences_by_status(db, low_book.id) == {"ready_for_audio": 5}
    assert await crud.audiobook.count_sentences_by_status(db, edge_book.id) == {
        "audio_generated": 4,
        "ready_for_audio": 1,
    }
    assert await crud.audiobook.count_sentences_by_status(db, complete_book.id) == {
        "audio_generated": 3,
        "ready_for_audio": 2,
    }
    await db.refresh(low_chapter)
    await db.refresh(edge_chapter)
    await db.refresh(complete_chapter)
    assert low_chapter.needs_reassembly is True
    assert edge_chapter.needs_reassembly is False
    assert complete_chapter.needs_reassembly is False


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


def _write_incremental_epub(path: Path, chapters: list[tuple[str, str, str]]) -> None:
    book = epub.EpubBook()
    book.set_identifier("incremental-test")
    book.set_title("Incremental")
    book.set_language("en")
    book.add_author("Author")
    spine = ["nav"]
    toc = []
    for index, (href, title, content) in enumerate(chapters, start=1):
        chapter = epub.EpubHtml(title=title, file_name=href, lang="en")
        chapter.content = f"<html><body><h1>{title}</h1><p>{content}</p></body></html>"
        book.add_item(chapter)
        spine.append(chapter)
        toc.append(epub.Link(href, title, f"chapter-{index}"))
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine
    book.toc = tuple(toc)
    epub.write_epub(path, book, {})


async def _mark_incremental_chapter_ready(db, library_path: Path, chapter, revision: int) -> tuple[Path, Path]:
    chapter_dir = library_path / "audiobooks" / str(chapter.book_id) / "seed" / chapter.stable_chapter_key
    chapter_dir.mkdir(parents=True, exist_ok=True)
    audio_path = chapter_dir / "audio.mp3"
    smil_path = chapter_dir / "overlay.smil"
    audio_path.write_bytes(f"audio-{chapter.id}".encode())
    smil_path.write_text("<smil/>", encoding="utf-8")
    chapter.audio_file_path = str(audio_path.relative_to(library_path.parent))
    chapter.smil_file_path = str(smil_path.relative_to(library_path.parent))
    chapter.reader_audio_file_path = chapter.audio_file_path
    chapter.reader_smil_file_path = chapter.smil_file_path
    chapter.audio_revision = revision
    chapter.generation_state = "ready"
    chapter.audio_size_bytes = audio_path.stat().st_size
    chapter.audio_sha256 = "a" * 64
    chapter.smil_size_bytes = smil_path.stat().st_size
    chapter.smil_sha256 = "b" * 64
    chapter.duration_ms = 1000
    sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
    for sentence in sentences:
        sentence.status = "audio_generated"
        sentence.audio_duration_ms = 1000
    await db.commit()
    return audio_path, smil_path


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
    monkeypatch.setattr(audiobook_publication, "LIBRARY_PATH", library_path)
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
    sentences = await crud.audiobook.get_sentences_for_chapter(db, chapters[0].id)
    assert len(sentences) >= 2
    assert all(sentence.html_element_id.startswith(f"{chapters[0].stable_chapter_key}-") for sentence in sentences)
    assert all(soup.find("span", id=sentence.html_element_id) is not None for sentence in sentences)


@pytest.mark.asyncio
async def test_incremental_ingestion_appends_chapter_without_invalidating_ready_audio(db, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    epub_path = library_path / "incremental.epub"
    initial = [
        ("Text/one.xhtml", "One", "First original sentence."),
        ("Text/two.xhtml", "Two", "Second original sentence."),
    ]
    _write_incremental_epub(epub_path, initial)
    book = await _make_book(
        db,
        audiobook_enabled=True,
        immutable_path=str(epub_path.relative_to(library_path.parent)),
        current_path=str(epub_path.relative_to(library_path.parent)),
    )
    monkeypatch.setattr(audiobook_ingestion, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_publication, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_ingestion, "_tokenize_text", _simple_sentence_split)

    await audiobook_ingestion.ingest_epub(book.id, db)
    original = await crud.audiobook.get_chapters_for_book(db, book.id)
    original_state = []
    for revision, chapter in enumerate(original, start=4):
        await _mark_incremental_chapter_ready(db, library_path, chapter, revision)
        sentence_ids = [
            sentence.html_element_id for sentence in await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        ]
        original_state.append((chapter.id, chapter.stable_chapter_key, revision, chapter.audio_file_path, sentence_ids))

    _write_incremental_epub(
        epub_path,
        [*initial, ("Text/three.xhtml", "Three", "A newly appended sentence.")],
    )
    await crud.touch_book_content(db, book)
    await db.commit()
    await audiobook_ingestion.ingest_epub(book.id, db)

    chapters = await crud.audiobook.get_chapters_for_book(db, book.id)
    assert len(chapters) == 3
    for chapter, expected in zip(chapters[:2], original_state, strict=True):
        chapter_id, key, revision, audio_path, sentence_ids = expected
        assert (chapter.id, chapter.stable_chapter_key, chapter.audio_revision) == (chapter_id, key, revision)
        assert chapter.audio_file_path == audio_path
        assert chapter.generation_state == "ready"
        assert [
            sentence.html_element_id for sentence in await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
        ] == sentence_ids
    assert chapters[2].generation_state == "pending"


@pytest.mark.asyncio
async def test_incremental_ingestion_invalidates_only_edited_chapter(db, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    epub_path = library_path / "incremental.epub"
    initial = [
        ("Text/one.xhtml", "One", "First original sentence."),
        ("Text/two.xhtml", "Two", "Second original sentence."),
    ]
    _write_incremental_epub(epub_path, initial)
    book = await _make_book(
        db,
        audiobook_enabled=True,
        immutable_path=str(epub_path.relative_to(library_path.parent)),
        current_path=str(epub_path.relative_to(library_path.parent)),
    )
    monkeypatch.setattr(audiobook_ingestion, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_publication, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_ingestion, "_tokenize_text", _simple_sentence_split)

    await audiobook_ingestion.ingest_epub(book.id, db)
    original = await crud.audiobook.get_chapters_for_book(db, book.id)
    first_assets = await _mark_incremental_chapter_ready(db, library_path, original[0], 7)
    edited_assets = await _mark_incremental_chapter_ready(db, library_path, original[1], 8)

    _write_incremental_epub(
        epub_path,
        [initial[0], ("Text/two.xhtml", "Two", "This sentence was edited.")],
    )
    await crud.touch_book_content(db, book)
    await db.commit()
    await audiobook_ingestion.ingest_epub(book.id, db)

    chapters = await crud.audiobook.get_chapters_for_book(db, book.id)
    assert chapters[0].id == original[0].id
    assert chapters[0].audio_revision == 7
    assert chapters[0].generation_state == "ready"
    assert all(path.exists() for path in first_assets)
    assert chapters[1].id == original[1].id
    assert chapters[1].audio_revision == 8
    assert chapters[1].generation_state == "pending"
    assert chapters[1].audio_file_path is None
    assert chapters[1].reader_audio_file_path is None
    assert all(not path.exists() for path in edited_assets)


@pytest.mark.asyncio
async def test_incremental_ingestion_removes_deleted_chapter_and_assets(db, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    epub_path = library_path / "incremental.epub"
    initial = [
        ("Text/one.xhtml", "One", "First original sentence."),
        ("Text/two.xhtml", "Two", "Second original sentence."),
    ]
    _write_incremental_epub(epub_path, initial)
    book = await _make_book(
        db,
        audiobook_enabled=True,
        immutable_path=str(epub_path.relative_to(library_path.parent)),
        current_path=str(epub_path.relative_to(library_path.parent)),
    )
    monkeypatch.setattr(audiobook_ingestion, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_publication, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_ingestion, "_tokenize_text", _simple_sentence_split)

    await audiobook_ingestion.ingest_epub(book.id, db)
    original = await crud.audiobook.get_chapters_for_book(db, book.id)
    await _mark_incremental_chapter_ready(db, library_path, original[0], 2)
    removed_assets = await _mark_incremental_chapter_ready(db, library_path, original[1], 3)

    _write_incremental_epub(epub_path, initial[:1])
    await crud.touch_book_content(db, book)
    await db.commit()
    await audiobook_ingestion.ingest_epub(book.id, db)

    chapters = await crud.audiobook.get_chapters_for_book(db, book.id)
    assert [chapter.id for chapter in chapters] == [original[0].id]
    assert chapters[0].generation_state == "ready"
    assert all(not path.exists() for path in removed_assets)


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
                        "voice_prompt": "[gender-male][pitch-medium][speed-normal]",
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
                    "voice_prompt": "[gender-female][pitch-low][speed-normal]",
                    "tts_voice_id": "captain",
                    "tts_voice_provider": "elevenlabs",
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
                    "voice_prompt": "[gender-neutral][pitch-high][speed-fast]",
                    "tts_voice_id": "wrong-voice",
                    "tts_voice_provider": "openai",
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
    assert second_character.voice_prompt == "[gender-female][pitch-low][speed-normal]"
    assert second_character.tts_voice_id == "captain"
    assert second_character.tts_voice_provider == "elevenlabs"

    first_character.voice_prompt = "[gender-female][pitch-medium][speed-slow]"
    first_character.tts_voice_id = "captain-v2"
    first_character.tts_voice_provider = "elevenlabs"
    await db.commit()
    linked = await crud.audiobook.propagate_character_profile_across_series(db, first_character)
    await db.refresh(second_character)

    assert {character.book_id for character in linked} == {first.id, second.id}
    assert second_character.voice_prompt == "[gender-female][pitch-medium][speed-slow]"
    assert second_character.tts_voice_id == "captain-v2"
    assert second_character.tts_voice_provider == "elevenlabs"

    # Renaming onto an existing canonical identity merges the shared profiles
    # instead of violating the series/name uniqueness constraint.
    other_character = (
        await crud.audiobook.create_characters_bulk(
            db,
            first.id,
            [
                {
                    "name": "Commander Vale",
                    "voice_prompt": "[gender-female][pitch-high][speed-normal]",
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
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for MP3 generation")
async def test_manual_sentence_audio_queues_and_generates_only_that_sentence(db, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    book = await _make_book(db, audiobook_enabled=True, audiobook_pipeline_status="paused")
    chapter, _character, sentence = await _seed_audio_chapter(db, book.id)
    chapter.preview_status = "ready"
    chapter.audio_file_path = "library/audiobooks/old-preview.mp3"
    await db.commit()
    queue = _FakeQueue()
    monkeypatch.setattr(audiobook_router, "get_audiobook_queue", lambda: queue)
    monkeypatch.setattr(audiobook_tts, "LIBRARY_PATH", library_path)

    response = await audiobook_router.generate_sentence_audio(book.id, sentence.id, db)
    await db.refresh(sentence)

    assert response == {
        "status": "audio_queued",
        "queued": True,
        "sentence_id": sentence.id,
    }
    assert sentence.status == "audio_queued"
    assert queue.sentence_enqueued == [(book.id, sentence.id)]

    await audiobook_tts.generate_audio_for_sentence(book.id, sentence.id, db)
    await db.refresh(sentence)
    await db.refresh(chapter)

    assert sentence.status == "audio_generated"
    assert sentence.audio_file_path
    assert (library_path.parent / sentence.audio_file_path).exists()
    assert chapter.needs_reassembly is True
    assert chapter.preview_status is None


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for MP3 assembly")
async def test_manual_chapter_preview_generates_playable_audio(db, tmp_path, monkeypatch):
    library_path = tmp_path / "library"
    library_path.mkdir()
    book = await _make_book(db, audiobook_enabled=True, audiobook_pipeline_status="complete")
    chapter, character, _sentence = await _seed_audio_chapter(db, book.id)
    await crud.audiobook.create_sentences_bulk(
        db,
        chapter.id,
        [
            {
                "html_element_id": "ch1_s1",
                "sequence_order": 1,
                "original_text": "A second sentence verifies concatenated timing.",
                "tagged_text": "A second sentence verifies concatenated timing.",
                "character_id": character.id,
                "status": "ready_for_audio",
            }
        ],
    )
    monkeypatch.setattr(audiobook_tts, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(audiobook_assembly, "LIBRARY_PATH", library_path)
    monkeypatch.setattr(crud.audiobook, "LIBRARY_PATH", library_path)
    packaged_epub = library_path / "audiobooks" / str(book.id) / "audiobook.epub"
    packaged_epub.parent.mkdir(parents=True)
    packaged_epub.write_bytes(b"stale package")

    await audiobook_tts.generate_audio_for_chapter_preview(book.id, chapter.id, db)
    legacy_sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
    for legacy_sentence in legacy_sentences:
        legacy_sentence.audio_duration_ms += 50
    await db.commit()
    await audiobook_assembly.assemble_chapter_preview(book.id, chapter.id, db)
    await db.refresh(chapter)
    await db.refresh(book)

    assert chapter.audio_file_path
    chapter_audio_path = library_path.parent / chapter.audio_file_path
    assert chapter_audio_path.exists()
    assert chapter.smil_file_path
    sentences = await crud.audiobook.get_sentences_for_chapter(db, chapter.id)
    expected_duration_ms = sum(sentence.audio_duration_ms for sentence in sentences)
    actual_duration_ms = round(MP3(chapter_audio_path).info.length * 1000)
    assert abs(actual_duration_ms - expected_duration_ms) <= 1
    smil_xml = (library_path.parent / chapter.smil_file_path).read_text(encoding="utf-8")
    assert f'clipEnd="{audiobook_assembly._ms_to_clock(expected_duration_ms)}"' in smil_xml
    assert packaged_epub.exists() is False
    assert book.audiobook_pipeline_status == "paused"


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
    for module in (audiobook_ingestion, audiobook_publication, audiobook_tts, audiobook_assembly):
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
        assert "EPUB/nav.xhtml" in names
        package = archive.read("EPUB/content.opf").decode("utf-8")
        assert 'media-type="application/smil+xml"' in package
        assert 'media-overlay="smil_ch0001"' in package
        assert 'properties="nav"' in package
        assert package.count('property="media:duration"') == 3
        assert 'property="media:duration">00:00:' in package

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
