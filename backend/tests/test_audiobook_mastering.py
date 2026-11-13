from dataclasses import replace
import shutil

import numpy as np
import pytest

from backend.app.services import audiobook_tts
from backend.app.services.audiobook_block_split import (
    BlockSplitError,
    estimated_block_boundaries,
    split_block,
)
from backend.app.services.audiobook_mastering import (
    PAUSE_CHAPTER_END_MS,
    PAUSE_CLAUSE_MS,
    PAUSE_CONTINUATION_MS,
    PAUSE_SENTENCE_MS,
    PAUSE_SPEAKER_CHANGE_MS,
    TARGET_SPEECH_DB,
    decode_clip,
    encode_mp3,
    master_clip,
    pause_after_ms,
)

RATE = 24_000


def _voiced(milliseconds: int, amplitude: float = 0.2) -> np.ndarray:
    time = np.arange(RATE * milliseconds // 1000) / RATE
    return (np.sin(2 * np.pi * 180 * time) * amplitude * 32767).astype(np.int16)


def _quiet(milliseconds: int) -> np.ndarray:
    return np.zeros(RATE * milliseconds // 1000, dtype=np.int16)


def _level_db(samples: np.ndarray) -> float:
    return float(10 * np.log10(np.mean((samples.astype(np.float64) / 32768) ** 2)))


@pytest.mark.parametrize("amplitude", [0.03, 0.1, 0.5])
def test_master_clip_brings_quiet_and_loud_speech_to_one_level(amplitude):
    clip = master_clip(np.concatenate([_quiet(400), _voiced(1000, amplitude), _quiet(700)]), RATE)

    assert clip.has_speech
    speech = clip.samples[slice(RATE // 10, -RATE // 10)]
    assert abs(_level_db(speech) - TARGET_SPEECH_DB) < 0.5


def test_master_clip_trims_surrounding_silence_but_keeps_the_speech():
    clip = master_clip(np.concatenate([_quiet(400), _voiced(1000), _quiet(700)]), RATE)

    duration_ms = len(clip.samples) * 1000 // RATE
    assert 1000 <= duration_ms <= 1120


def test_master_clip_never_clips_peaky_audio():
    samples = _voiced(1000, 0.01)
    samples[RATE // 2] = 30_000

    clip = master_clip(samples, RATE)

    assert int(np.max(np.abs(clip.samples.astype(np.int32)))) <= round(32768 * 10 ** (-1 / 20)) + 1


def test_master_clip_reports_a_speechless_clip_without_amplifying_it():
    clip = master_clip(_quiet(900), RATE)

    assert not clip.has_speech
    assert 0 < len(clip.samples) < RATE // 2
    assert not clip.samples.any()


@pytest.mark.parametrize(
    ("text", "speaker_changes", "last", "expected"),
    [
        ("She stopped.", False, False, PAUSE_SENTENCE_MS),
        ("“Is anyone there?”", False, False, PAUSE_SENTENCE_MS),
        ("“Is anyone there?”", True, False, PAUSE_SPEAKER_CHANGE_MS),
        ("“Wait,”", True, False, PAUSE_CLAUSE_MS),
        ("she said and", False, False, PAUSE_CONTINUATION_MS),
        ("The end.", False, True, PAUSE_CHAPTER_END_MS),
    ],
)
def test_pause_after_follows_how_the_sentence_ends(text, speaker_changes, last, expected):
    assert pause_after_ms(text, speaker_changes=speaker_changes, last_in_chapter=last) == expected


def test_block_boundaries_prefer_sentence_pauses_over_closer_clause_pauses():
    # Two sentences of equal length. The first has a comma pause very near the
    # proportional midpoint estimate; the real sentence break comes slightly
    # later and is longer.
    texts = ["Aaaa bbbb cccc, dddd eeee ffff gggg.", "Hhhh iiii jjjj kkkk llll mmmm nnnn."]
    boundaries = estimated_block_boundaries(6000, texts, [(0, 100), (2850, 2950), (3200, 3600), (5900, 6000)])

    assert boundaries == [0, 3400, 6000]


def test_block_boundaries_ignore_leading_silence_for_a_short_first_sentence():
    # Nearest-pause snapping used to hand "No." the block's leading silence.
    texts = ["No.", "The rest of the block is one long sentence that keeps going for a while."]
    boundaries = estimated_block_boundaries(5000, texts, [(0, 250), (700, 1000), (4800, 5000)])

    assert boundaries == [0, 850, 5000]


def test_block_boundaries_stay_in_step_when_one_sentence_has_inner_pauses():
    texts = [
        "Short one.",
        "A much longer sentence, with a clause, and another clause, that runs on.",
        "Short two.",
    ]
    silences = [(900, 1300), (2600, 2750), (3500, 3650), (5600, 6000), (6900, 7000)]
    boundaries = estimated_block_boundaries(7000, texts, silences)

    assert boundaries == [0, 1100, 5800, 7000]


def test_block_boundaries_fall_back_to_proportional_cuts_without_pauses():
    boundaries = estimated_block_boundaries(4000, ["Aaaa bbbb.", "Cccc dddd."], [])

    assert boundaries == [0, 2000, 4000]


def test_split_block_returns_one_spoken_slice_per_sentence():
    block = np.concatenate([_quiet(100), _voiced(1500), _quiet(400), _voiced(1500), _quiet(100)])

    first, second = split_block(block, RATE, ["Aaaa bbbb cccc dddd.", "Eeee ffff gggg hhhh."])

    assert len(first) + len(second) == len(block)
    assert abs(len(first) * 1000 // RATE - 1800) <= 20


def test_split_block_rejects_a_slice_with_no_speech():
    block = np.concatenate([_voiced(1000), _quiet(200), _voiced(40)])

    with pytest.raises(BlockSplitError, match="no speech"):
        split_block(block, RATE, ["A much longer first sentence here.", "No."])


@pytest.mark.asyncio
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for MP3 slicing")
async def test_split_block_audio_round_trips_through_mp3(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg
    block = np.concatenate([_quiet(100), _voiced(1500), _quiet(400), _voiced(900), _quiet(100)])
    await encode_mp3(ffmpeg, block, RATE, "96k", tmp_path / "block.mp3")
    block_mp3 = (tmp_path / "block.mp3").read_bytes()

    parts = await audiobook_tts._split_block_audio(block_mp3, ["Aaaa bbbb cccc dddd eeee.", "Ffff gggg hhhh."], "test")

    durations = []
    for index, part in enumerate(parts):
        path = tmp_path / f"{index}.mp3"
        path.write_bytes(part)
        durations.append(len(await decode_clip(ffmpeg, path, RATE)) * 1000 // RATE)
    assert len(parts) == 2
    assert abs(durations[0] - 1800) <= 5
    assert abs(durations[1] - 1200) <= 5


@pytest.mark.asyncio
async def test_unsplittable_block_regenerates_its_sentences_individually(monkeypatch):
    from backend.app import models

    sentences = [
        models.AudiobookSentence(
            id=index + 1,
            chapter_id=10,
            character_id=20,
            html_element_id=f"s{index}",
            sequence_order=index,
            original_text=f"Sentence {index}.",
        )
        for index in range(4)
    ]
    request = audiobook_tts.TTSRequest(text="", voice_id="voice-20", seed=7)
    blocks = [
        [(sentence, [replace(request, text=sentence.original_text)]) for sentence in sentences[:2]],
        [(sentence, [replace(request, text=sentence.original_text)]) for sentence in sentences[2:]],
    ]
    regenerated: list[tuple[int, str]] = []
    persisted: list[int] = []

    async def synthesize_batch(_settings, _sentence_id, requests):
        return [audiobook_tts.TTSResult(audio_bytes=request.text.encode()) for request in requests]

    async def split(audio_bytes, texts, _group_id):
        if b"Sentence 0" in audio_bytes:
            raise BlockSplitError("slice 2 of 2 has no speech")
        return [text.encode() for text in texts]

    async def generate_clip(_settings, _book_id, sentence, _db, requests=None):
        regenerated.append((sentence.id, requests[0].text))

    async def persist(_book_id, sentence, _result, _db, **_kwargs):
        persisted.append(sentence.id)

    monkeypatch.setattr(audiobook_tts, "_synthesize_batch_with_retries", synthesize_batch)
    monkeypatch.setattr(audiobook_tts, "_split_block_audio", split)
    monkeypatch.setattr(audiobook_tts, "_generate_sentence_clip", generate_clip)
    monkeypatch.setattr(audiobook_tts, "_persist_sentence_audio", persist)

    await audiobook_tts._generate_stable_blocks(None, 1, blocks, object())

    assert regenerated == [(1, "Sentence 0."), (2, "Sentence 1.")]
    assert persisted == [3, 4]
