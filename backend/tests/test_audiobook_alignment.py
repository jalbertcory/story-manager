"""Timestamped transcription and canonical-text alignment tests."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from backend.app import models
from backend.app.services import audiobook_alignment, endpoint_pool, transcription_providers
from backend.app.services.transcription_providers import TranscriptWord


def _words(texts, first_start=1000, word_ms=300, gap_ms=80):
    words = []
    cursor = first_start
    for text in texts:
        words.append(
            TranscriptWord(
                text=text,
                start_ms=cursor,
                end_ms=cursor + word_ms,
                score=0.95,
            )
        )
        cursor += word_ms + gap_ms
    return words


def test_sequence_alignment_uses_real_word_boundaries_despite_asr_differences():
    sentences = [
        (11, "The quick brown fox jumped over the lazy dog."),
        (12, "She whispered, I cannot believe this is happening."),
        (13, "Chapter twenty ended here."),
    ]
    words = _words(
        [
            "Chapter",
            "One",
            "The",
            "quick",
            "brown",
            "fox",
            "leaped",  # Narration/ASR substitution.
            "over",
            "the",
            "lazy",
            "dog",
            "She",
            "whispered",
            "I",
            "can't",  # Canonical text says "cannot".
            "believe",
            "this",
            "is",
            "happening",
            "Chapter",
            "20",  # Number normalization maps "twenty" to "20".
            "ended",
            "here",
        ]
    )

    result = audiobook_alignment.align_transcript_to_sentences(
        sentences,
        words,
        duration_ms=12_000,
        source_start_ms=50_000,
    )

    assert result.score > 0.65
    assert [cue.method for cue in result.cues] == ["transcribed"] * 3
    assert result.cues[0].clip_begin_ms == 50_000
    assert result.cues[-1].clip_end_ms == 62_000
    assert result.cues[0].clip_end_ms == result.cues[1].clip_begin_ms
    assert result.cues[1].clip_end_ms == result.cues[2].clip_begin_ms
    # Boundary follows actual "dog" / "She" timestamps, not chapter-length proportion.
    expected_boundary = 50_000 + round((words[10].end_ms + words[11].start_ms) / 2)
    assert result.cues[0].clip_end_ms == expected_boundary


def test_unmatched_sentence_is_interpolated_between_transcribed_anchors():
    sentences = [
        (1, "First grounded sentence."),
        (2, "An entirely omitted sentence in this edition."),
        (3, "Final grounded sentence."),
    ]
    words = _words(["First", "grounded", "sentence", "Final", "grounded", "sentence"])

    result = audiobook_alignment.align_transcript_to_sentences(sentences, words, duration_ms=6_000)

    assert result.cues[0].method == "transcribed"
    assert result.cues[1].method == "estimated"
    assert result.cues[2].method == "transcribed"
    assert all(cue.clip_end_ms > cue.clip_begin_ms for cue in result.cues)
    assert result.cues[0].clip_end_ms == result.cues[1].clip_begin_ms
    assert result.cues[1].clip_end_ms == result.cues[2].clip_begin_ms


def test_alignment_detects_and_explains_a_large_unused_transcript_tail():
    transcript_text = ["1", "The", "body", "continues", "through", "the", "next", "physical", "spine", "file"]
    transcript_text += ["with", "many", "more", "spoken", "words", "that", "belong", "to", "this", "chapter"]
    words = _words(transcript_text, first_start=0)
    duration_ms = words[-1].end_ms

    heading_only = audiobook_alignment.align_transcript_to_sentences(
        [(1, "1")],
        words,
        duration_ms=duration_ms,
    )
    expanded = audiobook_alignment.align_transcript_to_sentences(
        [(1, "1"), (2, " ".join(transcript_text[1:]))],
        words,
        duration_ms=duration_ms,
    )

    assert heading_only.matched_transcript_token_count == 1
    assert heading_only.transcript_token_count == len(transcript_text)
    assert expanded.matched_transcript_token_count == len(transcript_text)
    assert audiobook_alignment._continuation_improves_alignment(heading_only, expanded, duration_ms)


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "language": "en",
            "duration": 2.0,
            "words": [
                {"word": "Hello", "start": 0.1, "end": 0.5, "score": 0.97},
                {"word": "world", "start": 0.6, "end": 1.0, "score": 0.93},
            ],
        }


class _Client:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response()


@pytest.mark.asyncio
async def test_whisperx_provider_sends_chapter_clip_and_parses_word_timestamps(tmp_path, monkeypatch):
    _Client.calls = []
    monkeypatch.setattr(transcription_providers.httpx, "AsyncClient", _Client)
    clip = tmp_path / "chapter.flac"
    clip.write_bytes(b"flac-data")
    settings = models.AudiobookSettings(
        transcription_provider="whisperx",
        transcription_api_key="local-key",
        transcription_base_url="http://whisper:8002/transcribe",
        transcription_model="large-v3",
        transcription_language="en",
    )

    result = await transcription_providers.transcribe_file(settings, clip)

    assert result.language == "en"
    assert result.duration_ms == 2_000
    assert result.words[0].start_ms == 100
    assert result.words[-1].end_ms == 1_000
    url, request = _Client.calls[0]
    assert url == "http://whisper:8002/transcribe"
    assert request["data"] == {"model": "large-v3", "language": "en"}
    assert request["headers"]["Authorization"] == "Bearer local-key"
    assert request["files"]["file"][0] == "chapter.flac"


@pytest.mark.asyncio
async def test_whisperx_provider_surfaces_service_error_detail(tmp_path, monkeypatch):
    endpoint_pool.reset_cooldowns("transcription")

    class ConflictClient(_Client):
        async def post(self, url, **kwargs):
            request = httpx.Request("POST", url)
            response = httpx.Response(
                409,
                request=request,
                json={"detail": "Service has 'large-v3' loaded, not requested model 'tiny.en'."},
            )
            return response

    monkeypatch.setattr(transcription_providers.httpx, "AsyncClient", ConflictClient)
    clip = tmp_path / "chapter.flac"
    clip.write_bytes(b"flac-data")
    settings = models.AudiobookSettings(
        transcription_provider="whisperx",
        transcription_base_url="http://whisper:8002",
        transcription_model="tiny.en",
    )

    with pytest.raises(
        RuntimeError,
        match="Service has 'large-v3' loaded, not requested model 'tiny.en'",
    ):
        await transcription_providers.transcribe_file(settings, clip)


@pytest.mark.asyncio
async def test_whisperx_health_rejects_configured_model_mismatch(monkeypatch):
    endpoint_pool.reset_cooldowns("transcription")

    class HealthResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ready", "model": "large-v3"}

    class HealthClient(_Client):
        async def get(self, _url, **_kwargs):
            return HealthResponse()

    monkeypatch.setattr(transcription_providers.httpx, "AsyncClient", HealthClient)
    settings = models.AudiobookSettings(
        transcription_provider="whisperx",
        transcription_base_url="http://whisper:8002",
        transcription_model="tiny.en",
    )

    with pytest.raises(
        RuntimeError,
        match="service has 'large-v3' loaded.*Audio Settings request 'tiny.en'",
    ):
        await transcription_providers.transcription_service_health(settings)


@pytest.mark.asyncio
async def test_alignment_selects_sentences_from_logical_chapter_continuations(db):
    book = models.Book(title="Split Book")
    db.add(book)
    await db.flush()
    heading = models.AudiobookChapter(
        book_id=book.id,
        chapter_number=1,
        title="Chapter 1",
        logical_chapter_key="logical-1",
        logical_part_order=0,
        spine_order=0,
    )
    body = models.AudiobookChapter(
        book_id=book.id,
        chapter_number=2,
        title="Phase One",
        logical_chapter_key="logical-1",
        logical_part_order=1,
        spine_order=1,
    )
    db.add_all([heading, body])
    await db.flush()
    db.add_all(
        [
            models.AudiobookSentence(
                chapter_id=heading.id,
                html_element_id="heading",
                sequence_order=0,
                original_text="1",
            ),
            models.AudiobookSentence(
                chapter_id=body.id,
                html_element_id="body",
                sequence_order=0,
                original_text="The body follows the split heading.",
            ),
        ]
    )
    edition = models.ImportedAudiobook(book_id=book.id, name="Human", status="ready")
    db.add(edition)
    await db.flush()
    track = models.ImportedAudiobookTrack(
        imported_audiobook_id=edition.id,
        matched_chapter_id=heading.id,
        sequence_order=1,
        title="Chapter 1",
        audio_file_path="library/chapter.m4a",
        media_type="audio/mp4",
        source_start_ms=0,
        source_end_ms=10_000,
        duration_ms=10_000,
    )
    db.add(track)
    await db.commit()

    sentences = await audiobook_alignment._sentences_for_track(track, db)

    assert [sentence.original_text for sentence in sentences] == ["1", "The body follows the split heading."]


@pytest.mark.asyncio
async def test_process_alignment_replaces_estimates_and_caches_transcript(db, tmp_path, monkeypatch):
    book = models.Book(
        title="Aligned Book",
        immutable_path="library/aligned-immutable.epub",
        current_path="library/aligned.epub",
    )
    settings = models.AudiobookSettings(
        transcription_provider="whisperx",
        transcription_base_url="http://whisper:8002",
        transcription_model="small",
        transcription_language="en",
    )
    db.add_all([book, settings])
    await db.flush()
    chapter = models.AudiobookChapter(
        book_id=book.id,
        chapter_number=1,
        stable_chapter_key="aligned-chapter",
        content_file_name="text/chapter.xhtml",
        spine_order=0,
    )
    db.add(chapter)
    await db.flush()
    sentences = [
        models.AudiobookSentence(
            chapter_id=chapter.id,
            html_element_id=f"sentence-{index}",
            sequence_order=index,
            original_text=text,
        )
        for index, text in enumerate(("Hello brave new world.", "This timing is real."))
    ]
    db.add_all(sentences)
    edition = models.ImportedAudiobook(
        book_id=book.id,
        name="Human narration",
        status="aligning",
        alignment_method="estimated",
    )
    db.add(edition)
    await db.flush()
    track = models.ImportedAudiobookTrack(
        imported_audiobook_id=edition.id,
        matched_chapter_id=chapter.id,
        sequence_order=1,
        title="Chapter 1",
        audio_file_path="library/source.m4b",
        media_type="audio/mp4",
        source_start_ms=20_000,
        source_end_ms=25_000,
        duration_ms=5_000,
    )
    db.add(track)
    await db.flush()
    for index, sentence in enumerate(sentences):
        db.add(
            models.ImportedAudiobookCue(
                track_id=track.id,
                sentence_id=sentence.id,
                sequence_order=index,
                clip_begin_ms=20_000 + index * 2_500,
                clip_end_ms=22_500 + index * 2_500,
                confidence=0.25,
                method="estimated",
            )
        )
    await db.commit()

    edition_dir = tmp_path / "edition"
    monkeypatch.setattr(audiobook_alignment, "imported_audiobook_dir", lambda *_args: edition_dir)
    monkeypatch.setattr(audiobook_alignment, "relative_library_path", lambda path: str(path))

    async def fake_extract(_track, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"flac")

    transcription_calls = []

    async def fake_transcribe(_settings, _path):
        transcription_calls.append(
            (
                _settings.transcription_language,
                _settings.transcription_base_url,
            )
        )
        return transcription_providers.TranscriptResult(
            language="en",
            duration_ms=5_000,
            words=_words(
                ["Hello", "brave", "new", "world", "This", "timing", "is", "real"],
                first_start=500,
            ),
        )

    monkeypatch.setattr(audiobook_alignment, "_extract_track_clip", fake_extract)
    monkeypatch.setattr(audiobook_alignment, "transcribe_file", fake_transcribe)

    await audiobook_alignment.process_alignment(edition.id, db)
    await db.refresh(edition)
    await db.refresh(track)
    cues = list(
        (
            await db.execute(
                select(models.ImportedAudiobookCue)
                .where(models.ImportedAudiobookCue.track_id == track.id)
                .order_by(models.ImportedAudiobookCue.sequence_order)
            )
        )
        .scalars()
        .all()
    )

    assert edition.status == "ready"
    assert edition.alignment_method == "transcribed"
    assert edition.alignment_error is None
    assert track.alignment_score > 0.8
    assert track.transcript_file_path.endswith("track-1.json.gz")
    assert cues[0].method == "transcribed"
    assert cues[0].clip_begin_ms == 20_000
    assert cues[-1].clip_end_ms == 25_000
    assert (edition_dir / "alignment" / "transcripts" / f"track-{track.id}.json.gz").is_file()
    assert transcription_calls == [("en", "http://whisper:8002")]

    edition.status = "aligning"
    await db.commit()

    await audiobook_alignment.process_alignment(edition.id, db)

    assert transcription_calls == [("en", "http://whisper:8002")]

    settings.transcription_language = "fr"
    edition.status = "aligning"
    await db.commit()

    await audiobook_alignment.process_alignment(edition.id, db)

    assert transcription_calls == [
        ("en", "http://whisper:8002"),
        ("fr", "http://whisper:8002"),
    ]

    settings.transcription_base_url = "http://replacement-whisper:8002/transcribe"
    edition.status = "aligning"
    await db.commit()

    await audiobook_alignment.process_alignment(edition.id, db)

    assert transcription_calls == [
        ("en", "http://whisper:8002"),
        ("fr", "http://whisper:8002"),
        ("fr", "http://replacement-whisper:8002/transcribe"),
    ]
